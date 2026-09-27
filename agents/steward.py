"""Data Steward agent: finds documentation, PII and glossary gaps in OpenMetadata and
queues proposals for human approval.

  python -m agents.steward [schema.table ...]
"""

import json
import sys

import anyio

from agents.common import AgentResult, AgentSpec, run_agent

DEFAULT_TABLES = [
    "marts.fct_service_requests",
    "marts.fct_district_daily_sanitation",
    "marts.mart_district_monthly_scorecard",
]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tables_reviewed": {"type": "array", "items": {"type": "string"}},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "integer"},
                    "table": {"type": "string"},
                    "column": {"type": ["string", "null"]},
                    "change_type": {"type": "string"},
                    "proposed_value": {"type": "string"},
                },
                "required": ["proposal_id", "table", "change_type", "proposed_value"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["tables_reviewed", "proposals", "summary"],
}

SPEC = AgentSpec(
    name="steward",
    prompt_file="steward.md",
    curbside_tools=["run_readonly_sql", "propose_metadata_change", "list_pending_proposals"],
    sql_schemas="marts,staging,intermediate",
    effort="medium",
    max_turns=60,
    max_budget_usd=3.0,
    output_schema=OUTPUT_SCHEMA,
)


async def review(tables: list[str] | None = None, trigger: str = "manual") -> AgentResult:
    tables = tables or DEFAULT_TABLES
    prompt = (
        "Review these tables and queue proposals for missing descriptions, personal-data "
        "tags and glossary links:\n" + "\n".join(f"- {t}" for t in tables)
    )
    return await run_agent(SPEC, prompt, trigger=trigger)


if __name__ == "__main__":
    result = anyio.run(review, sys.argv[1:] or None)
    print(json.dumps(result.output or result.text, indent=2, default=str))
    print(f"\nturns={result.num_turns} cost=${result.cost_usd} trace={result.trace_path}", file=sys.stderr)
