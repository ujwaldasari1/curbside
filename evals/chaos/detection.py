"""Data-quality coverage check (free, no LLM): is every chaos fault caught by at least one
dbt test or model error? A fault nobody detects is a gap in the test suite.

  python -m evals.chaos.detection [fault ...]
"""

import json
import os
import subprocess
import sys

from evals.chaos.faults import FAULTS, inject, restore
from shared.env import ROOT

DBT_DIR = ROOT / "transform"


def dbt_build_failures() -> list[dict]:
    subprocess.run(["dbt", "build", "--quiet"], cwd=DBT_DIR, capture_output=True, text=True,
                   env={**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)})
    results = json.loads((DBT_DIR / "target" / "run_results.json").read_text())["results"]
    return [
        {"node": r["unique_id"].split(".")[-1] if r["unique_id"].startswith("model") else r["unique_id"].split(".")[2],
         "status": r["status"], "failures": r.get("failures"), "message": (r.get("message") or "")[:300]}
        for r in results if r["status"] in ("fail", "error")
    ]


def check(names: list[str]) -> dict:
    report = {}
    for name in names:
        fault = FAULTS[name]
        inject(fault)
        try:
            caught = dbt_build_failures()
        finally:
            restore(fault)
        report[name] = caught
        verdict = "CAUGHT" if caught else "MISSED"
        print(f"{verdict:7s} {name:30s} by {[c['node'] for c in caught][:4]}", flush=True)
    return report


if __name__ == "__main__":
    selected = sys.argv[1:] or list(FAULTS)
    report = check(selected)
    missed = [n for n, caught in report.items() if not caught]
    print(f"\n{len(selected) - len(missed)}/{len(selected)} faults detected by the test suite")
    sys.exit(1 if missed else 0)
