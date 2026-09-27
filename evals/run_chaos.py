"""Chaos eval for the incident agent.

For each fault: inject it into the raw layer -> run Dagster `transform_only` (tagged so the
failure sensor stays out of it) -> push failing test results to OpenMetadata -> incident
agent investigates -> score its diagnosis against the fault's ground truth -> restore.

  python -m evals.run_chaos [fault ...]
"""

import datetime as dt
import json
import sys

import anyio

from agents import incident
from evals.chaos import dagster_runs
from evals.chaos.faults import FAULTS, Fault, inject, restore
from governance.catalog_sync import sync_dbt
from orchestration.agent_jobs import CHAOS_EVAL_TAG
from shared.env import ROOT

REPORTS = ROOT / "evals" / "reports"


def score(fault: Fault, diagnosis: dict) -> dict:
    asset = (diagnosis.get("root_cause_asset") or "").strip().lower()
    column = (diagnosis.get("root_cause_column") or "").strip().lower() or None
    return {
        "asset_correct": asset == fault.root_cause_asset,
        "category_correct": diagnosis.get("fault_category") in fault.categories(),
        "column_correct": None if fault.root_cause_column is None else column == fault.root_cause_column,
        "incident_filed": diagnosis.get("incident_id") is not None,
    }


def run_one(fault: Fault) -> dict:
    inject(fault)
    try:
        run_id = dagster_runs.launch("transform_only", {CHAOS_EVAL_TAG: "true"})
        status = dagster_runs.wait(run_id)
        if status != "FAILURE":
            return {"fault": fault.name, "detected": False, "run_status": status}
        sync_dbt()
        result = anyio.run(incident.triage, run_id, "chaos_eval")
        diagnosis = result.output or {}
        return {
            "fault": fault.name,
            "detected": True,
            "run_id": run_id,
            "expected": {"asset": fault.root_cause_asset, "column": fault.root_cause_column,
                         "categories": sorted(fault.categories())},
            "diagnosis": diagnosis,
            "score": score(fault, diagnosis),
            "turns": result.num_turns,
            "tool_calls": len(result.tool_calls),
            "duration_s": round(result.duration_ms / 1000, 1),
            "cost_usd": result.cost_usd,
            "trace": result.trace_path,
        }
    finally:
        restore(fault)
        sync_dbt()


def summarize(results: list[dict]) -> str:
    scored = [r for r in results if r.get("detected")]
    n = len(scored) or 1
    lines = [
        "| fault | detected | root-cause table | category | column | turns | cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        s = r.get("score", {})
        mark = lambda v: "n/a" if v is None else ("yes" if v else "NO")  # noqa: E731
        lines.append(f"| {r['fault']} | {mark(r.get('detected'))} | {mark(s.get('asset_correct'))} | "
                     f"{mark(s.get('category_correct'))} | {mark(s.get('column_correct'))} | "
                     f"{r.get('turns', '')} | ${r.get('cost_usd') or 0:.2f} |")
    asset_acc = sum(r["score"]["asset_correct"] for r in scored) / n
    cat_acc = sum(r["score"]["category_correct"] for r in scored) / n
    cost = sum(r.get("cost_usd") or 0 for r in scored)
    lines.append(f"\nRoot-cause table accuracy **{asset_acc:.0%}**, fault category accuracy "
                 f"**{cat_acc:.0%}** over {len(scored)} detected faults; total cost ${cost:.2f}.")
    return "\n".join(lines)


def main(names: list[str]) -> None:
    results = []
    for name in names:
        print(f"== {name}", flush=True)
        results.append(run_one(FAULTS[name]))
        print(json.dumps(results[-1].get("score", results[-1]), default=str), flush=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"chaos-{stamp}.json").write_text(json.dumps(results, indent=2, default=str))
    report = summarize(results)
    (REPORTS / f"chaos-{stamp}.md").write_text(f"# Incident agent chaos eval ({stamp})\n\n{report}\n")
    print("\n" + report)


if __name__ == "__main__":
    main(sys.argv[1:] or list(FAULTS))
