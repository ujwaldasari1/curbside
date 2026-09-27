import json

import anyio

from agents import analyst
from agents.common import AgentResult, _executed_query, executed_sql


def _blocks(payload) -> list[dict]:
    """How an MCP tool result reaches the PostToolUse hook."""
    return [{"type": "text", "text": json.dumps(payload, indent=2)}]


def test_query_metric_records_the_sql_metricflow_generated():
    response = _blocks({"columns": ["x"], "rows": [[1]], "sql": "SELECT 1 AS x FROM marts.t", "query_id": "ab12cd34"})
    assert _executed_query("mcp__curbside__query_metric", {"metrics": ["m"]}, response) == {
        "sql": "SELECT 1 AS x FROM marts.t", "query_id": "ab12cd34"}


def test_readonly_sql_is_recorded_only_when_it_returned_rows():
    sql = {"sql": "select borough from marts.dim_community_district"}
    ok = _blocks({"columns": ["borough"], "rows": [["Bronx"]], "row_count": 1, "truncated": False, "query_id": "q1"})
    assert _executed_query("mcp__curbside__run_readonly_sql", sql, ok) == {"sql": sql["sql"], "query_id": "q1"}
    failed = [{"type": "text", "text": "rejected by SQL guard: schema 'raw' is outside this agent's scope"}]
    assert _executed_query("mcp__curbside__run_readonly_sql", sql, failed) == {}


def test_other_tools_record_no_sql():
    response = _blocks({"metrics": [], "sql": "not from a warehouse tool"})
    assert _executed_query("mcp__curbside__list_metrics", {}, response) == {}
    assert _executed_query("mcp__openmetadata__search_metadata", {"query": "x"}, response) == {}
    assert _executed_query("mcp__curbside__query_metric", {}, None) == {}


def test_executed_sql_keeps_order_and_drops_repeats():
    calls = [{"tool": "a", "sql": "q1"}, {"tool": "b"}, {"tool": "c", "sql": "q2"}, {"tool": "d", "sql": "q1"}]
    assert executed_sql(calls) == ["q1", "q2"]


def test_only_cited_queries_are_evidence_and_the_rest_stay_visible():
    calls = [
        {"tool": "mcp__curbside__query_metric", "sql": "SELECT 13 months", "query_id": "aaaa"},
        {"tool": "mcp__curbside__query_metric", "sql": "SELECT latest month", "query_id": "bbbb"},
        {"tool": "mcp__curbside__query_metric", "sql": "SELECT 12 months", "query_id": "cccc"},
    ]
    output = {"evidence_query_ids": ["cccc", "made-up-id"], "sql": ["SELECT model_written"]}
    analyst.attach_sql(output, calls)
    assert output["sql"] == ["SELECT 12 months"]
    assert output["other_sql_run"] == ["SELECT 13 months", "SELECT latest month"]


def test_nothing_is_evidence_when_the_answer_cites_no_query():
    output = {"evidence_query_ids": []}
    analyst.attach_sql(output, [{"tool": "mcp__curbside__query_metric", "sql": "SELECT 1", "query_id": "aaaa"}])
    assert output["sql"] == []
    assert output["other_sql_run"] == ["SELECT 1"]


def test_analyst_reports_the_sql_that_ran_not_the_models_version(monkeypatch):
    async def fake_run_agent(spec, prompt, trigger="manual"):
        return AgentResult(
            agent="analyst", output={"answer_markdown": "Queens", "evidence_query_ids": ["r1"],
                                     "sql": ["SELECT made_up"]}, text=None,
            is_error=False, num_turns=2, duration_ms=10, cost_usd=0.0, session_id="s",
            tool_calls=[{"tool": "mcp__curbside__query_metric", "sql": "SELECT real FROM marts.t", "query_id": "r1"}],
            trace_path="t.jsonl",
        )

    monkeypatch.setattr(analyst, "run_agent", fake_run_agent)
    result = anyio.run(analyst.ask, "Which borough?")
    assert result.output["sql"] == ["SELECT real FROM marts.t"]
    assert result.output["other_sql_run"] == []
    assert "sql" not in analyst.OUTPUT_SCHEMA["properties"]
    assert "evidence_query_ids" in analyst.OUTPUT_SCHEMA["required"]
