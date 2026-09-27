"""Agent evals with a scorecard.

  python -m evals.run_evals analyst [--limit N]    # golden questions, live reference answers
  python -m evals.run_evals steward                # PII tagging vs labels, vs OpenMetadata baseline
  python -m evals.run_evals chaos [fault ...]      # incident root-cause accuracy (see run_chaos)

Every run calls the model and costs money: start with --limit 1 to measure cost per item.
"""

import argparse
import dataclasses
import datetime as dt
import json
import re
import subprocess

import anyio
import psycopg
import yaml

from agents import analyst, steward
from agents.common import run_agent
from shared.env import ROOT, load_dotenv
from shared.openmetadata import OpenMetadataClient

load_dotenv()
EVALS = ROOT / "evals"
REPORTS = EVALS / "reports"
RO_DSN = "postgresql://curbside_agent_ro:curbside_agent_ro@localhost:5432/curbside"
ETL_DSN = "postgresql://curbside_etl:curbside_etl@localhost:5432/curbside"
SERVICE_DB = "curbside_warehouse.curbside"


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _write(name: str, results: dict, markdown: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    stamp = _stamp()
    (REPORTS / f"{name}-{stamp}.json").write_text(json.dumps(results, indent=2, default=str))
    (REPORTS / f"{name}-{stamp}.md").write_text(markdown + "\n")
    print("\n" + markdown)


# ------------------------------------------------------------------------ analyst
def _number_matches(value: float, expected: float, tolerance: float) -> bool:
    candidates = [value]
    if 0 < abs(expected) <= 1:
        candidates.append(value / 100)  # 19.07 (%) vs 0.1907
    for v in candidates:
        if tolerance == 0 and round(v) == round(expected):
            return True
        if expected and abs(v - expected) <= tolerance * abs(expected):
            return True
    return False


def _label_matches(answer: str, expected: str) -> bool:
    answer = answer.lower()
    expected = expected.lower()
    if expected in answer or expected.replace("_", " ") in answer:
        return True
    first = re.split(r"[,/]", expected)[0].strip()  # "Stapleton, Port Richmond" -> "stapleton"
    return len(first) > 3 and first in answer


def score_analyst(item: dict, output: dict, expected) -> bool:
    numbers = [n.get("value") for n in output.get("key_numbers", []) if isinstance(n.get("value"), int | float)]
    if item["kind"] == "no_data":
        return not numbers
    if item["kind"] == "number":
        return any(_number_matches(float(n), float(expected), item.get("tolerance", 0.01)) for n in numbers)
    return _label_matches(output.get("answer_markdown", ""), str(expected))


def eval_analyst(limit: int | None) -> None:
    items = yaml.safe_load((EVALS / "analyst_golden.yaml").read_text())[: limit or None]
    results = []
    with psycopg.connect(RO_DSN) as conn:
        for item in items:
            expected = None if item["kind"] == "no_data" else conn.execute(item["reference_sql"]).fetchone()[0]
            result = anyio.run(analyst.ask, item["question"], "eval")
            output = result.output or {}
            passed = score_analyst(item, output, expected)
            print(f"{'PASS' if passed else 'FAIL'} {item['id']:40s} expected={expected} "
                  f"got={[n.get('value') for n in output.get('key_numbers', [])][:3]} ${result.cost_usd or 0:.3f}",
                  flush=True)
            results.append({"id": item["id"], "kind": item["kind"], "passed": passed,
                            "expected": expected, "output": output, "turns": result.num_turns,
                            "cost_usd": result.cost_usd, "duration_s": result.duration_ms / 1000,
                            "trace": result.trace_path})
    n = len(results)
    passed = sum(r["passed"] for r in results)
    cost = sum(r["cost_usd"] or 0 for r in results)
    rows = "\n".join(f"| {r['id']} | {r['kind']} | {'pass' if r['passed'] else 'FAIL'} | {r['turns']} | "
                     f"${r['cost_usd'] or 0:.3f} |" for r in results)
    _write("analyst", {"results": results}, (
        f"# Analyst eval\n\n**{passed}/{n} correct ({passed / n:.0%})**, total cost ${cost:.2f}, "
        f"mean ${cost / n:.3f}/question.\n\n"
        f"| question | kind | result | turns | cost |\n|---|---|---|---|---|\n{rows}"))


# ------------------------------------------------------------------------ steward
def _prf(predicted: set[str], labels: dict) -> dict:
    sensitive, clean = set(labels["sensitive"]), set(labels["not_sensitive"])
    scored = predicted & (sensitive | clean)
    tp = len(scored & sensitive)
    precision = tp / len(scored) if scored else 0.0
    recall = tp / len(sensitive)
    return {"predicted": sorted(scored), "precision": round(precision, 3), "recall": round(recall, 3),
            "false_positives": sorted(scored & clean), "missed": sorted(sensitive - predicted)}


def _om_pii_columns(om: OpenMetadataClient, table_fqn: str, automated_only: bool) -> set[str]:
    table = om.get_by_name("tables", table_fqn, fields="columns,tags")
    return {c["name"] for c in table["columns"] for t in c.get("tags", [])
            if t["tagFQN"] == "PII.Sensitive" and (not automated_only or t.get("labelType") == "Automated")}


def _remove_automated_tags(om: OpenMetadataClient, table_fqn: str) -> None:
    table = om.get_by_name("tables", table_fqn, fields="columns,tags")
    ops = []
    for i, column in enumerate(table["columns"]):
        kept = [t for t in column.get("tags", []) if t.get("labelType") != "Automated"]
        if len(kept) != len(column.get("tags", [])):
            ops.append({"op": "add", "path": f"/columns/{i}/tags", "value": kept})
    if ops:
        om.patch(f"/v1/tables/{table['id']}", ops)


def eval_steward() -> None:
    labels = yaml.safe_load((EVALS / "pii_labels.yaml").read_text())
    table_fqn = f"{SERVICE_DB}.{labels['table']}"
    om = OpenMetadataClient()
    already_tagged = _om_pii_columns(om, table_fqn, automated_only=False)
    if already_tagged:
        print(f"note: columns already tagged PII.Sensitive before the eval: {sorted(already_tagged)}")

    spec = dataclasses.replace(steward.SPEC, name="steward_eval")
    prompt = ("Review this table and queue proposals for personal-data tags and missing descriptions:\n"
              f"- {labels['table']}")
    result = anyio.run(run_agent, spec, prompt, "eval")
    with psycopg.connect(ETL_DSN) as conn:
        proposals = conn.execute(
            "select change_type, column_name, proposed_value from ops.metadata_proposals where agent = 'steward_eval'"
        ).fetchall()
        conn.execute("delete from ops.metadata_proposals where agent = 'steward_eval'")
    agent_pii = {col for change, col, value in proposals if change == "column_tag" and value == "PII.Sensitive"}
    agent = _prf(agent_pii | already_tagged, labels)

    # Baseline: OpenMetadata's built-in auto-classification on the same table.
    subprocess.run(["make", "om-classify"], cwd=ROOT, capture_output=True, text=True)
    baseline = _prf(_om_pii_columns(om, table_fqn, automated_only=True) | already_tagged, labels)
    _remove_automated_tags(om, table_fqn)

    descriptions = sum(1 for change, _, _ in proposals if change == "column_description")
    _write("steward", {"agent": agent, "baseline": baseline, "proposals": proposals,
                       "cost_usd": result.cost_usd, "turns": result.num_turns}, (
        "# Steward eval: personal-data tagging on marts.fct_service_requests\n\n"
        "| classifier | precision | recall | false positives | missed |\n|---|---|---|---|---|\n"
        f"| Steward agent (Claude) | {agent['precision']:.0%} | {agent['recall']:.0%} | "
        f"{', '.join(agent['false_positives']) or '-'} | {', '.join(agent['missed']) or '-'} |\n"
        f"| OpenMetadata auto-classification | {baseline['precision']:.0%} | {baseline['recall']:.0%} | "
        f"{', '.join(baseline['false_positives']) or '-'} | {', '.join(baseline['missed']) or '-'} |\n\n"
        f"The agent also proposed {descriptions} column descriptions ({len(proposals)} proposals total). "
        f"Cost ${result.cost_usd or 0:.2f}, {result.num_turns} turns."))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["analyst", "steward", "chaos"])
    parser.add_argument("faults", nargs="*")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.suite == "analyst":
        eval_analyst(args.limit)
    elif args.suite == "steward":
        eval_steward()
    else:
        from evals import run_chaos
        from evals.chaos.faults import FAULTS
        run_chaos.main(args.faults or list(FAULTS)[: args.limit or None])


if __name__ == "__main__":
    main()
