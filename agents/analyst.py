"""Analyst agent: answers questions from certified metrics and marts only.

  python -m agents.analyst "Which borough had the highest diversion rate last month?"
"""

import json
import sys

import anyio

from agents.common import AgentResult, AgentSpec, run_agent

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_markdown": {"type": "string", "description": "Direct answer first, then a short table if useful"},
        "key_numbers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "value": {"type": "number"},
                               "unit": {"type": "string"}},
                "required": ["label", "value"],
            },
        },
        "metrics_used": {"type": "array", "items": {"type": "string"}},
        "tables_used": {"type": "array", "items": {"type": "string"}},
        "sql": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer_markdown", "key_numbers", "metrics_used", "tables_used"],
}

SPEC = AgentSpec(
    name="analyst",
    prompt_file="analyst.md",
    curbside_tools=["list_metrics", "query_metric", "run_readonly_sql"],
    om_tools=["search_metadata", "get_entity_details"],
    sql_schemas="marts",
    effort="medium",
    max_turns=25,
    max_budget_usd=1.0,
    output_schema=OUTPUT_SCHEMA,
)


async def ask(question: str, trigger: str = "manual") -> AgentResult:
    return await run_agent(SPEC, question, trigger=trigger)


if __name__ == "__main__":
    result = anyio.run(ask, " ".join(sys.argv[1:]) or "Which borough diverts the most waste?")
    print(json.dumps(result.output or result.text, indent=2, default=str))
    print(f"\nturns={result.num_turns} cost=${result.cost_usd} trace={result.trace_path}", file=sys.stderr)
