"""Incident agent: root-cause analysis for failed Dagster runs / data checks.

  python -m agents.incident <dagster_run_id>
  python -m agents.incident            # triage the most recent failed run
"""

import json
import sys

import anyio

from agents.common import AgentResult, AgentSpec, run_agent

FAULT_CATEGORIES = [
    "schema_drift", "null_spike", "duplicate_records", "stale_source", "unit_change",
    "referential_break", "late_data", "distribution_shift", "upstream_api", "code_change",
    "other",
]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "incident_id": {"type": ["integer", "null"]},
        "failed_asset": {"type": "string"},
        "root_cause_asset": {"type": "string", "description": "<schema>.<table> where it originated"},
        "root_cause_column": {"type": ["string", "null"]},
        "fault_category": {"type": "string", "enum": FAULT_CATEGORIES},
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "root_cause": {"type": "string"},
        "suggested_fix": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["failed_asset", "root_cause_asset", "fault_category", "severity",
                 "root_cause", "suggested_fix", "confidence"],
}

SPEC = AgentSpec(
    name="incident",
    prompt_file="incident.md",
    curbside_tools=["get_run_failure", "diagnose_asset", "run_readonly_sql",
                    "impact_of_change", "record_incident"],
    sql_schemas="marts,staging,intermediate,raw_*",
    effort="high",
    max_turns=50,
    max_budget_usd=3.0,
    output_schema=OUTPUT_SCHEMA,
)


async def triage(run_id: str | None = None, trigger: str = "manual") -> AgentResult:
    if run_id:
        prompt = f"Dagster run {run_id} failed. Find the root cause and file the incident."
    else:
        prompt = ("Find the most recent failed Dagster run (get_run_failure without a run id), "
                  "then find the root cause and file the incident.")
    return await run_agent(SPEC, prompt, trigger=trigger)


if __name__ == "__main__":
    result = anyio.run(triage, sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(result.output or result.text, indent=2, default=str))
    print(f"\nturns={result.num_turns} cost=${result.cost_usd} trace={result.trace_path}", file=sys.stderr)
