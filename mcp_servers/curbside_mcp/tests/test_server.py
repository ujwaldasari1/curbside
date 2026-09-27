"""Integration tests: drive curbside-mcp in-process through a real MCP client against the
live stack (Postgres, OpenMetadata, Dagster). Skipped when the stack is not running."""

import json
import os

import psycopg
import pytest
import requests
from mcp import Client

pytestmark = pytest.mark.anyio


def _stack_up() -> bool:
    try:
        requests.get("http://localhost:8585/api/v1/system/version", timeout=2)
        psycopg.connect("postgresql://curbside_agent_ro:curbside_agent_ro@localhost:5432/curbside",
                        connect_timeout=2).close()
        return bool(os.environ.get("OPENMETADATA_JWT_TOKEN"))
    except Exception:
        return False


if not _stack_up():
    pytest.skip("live stack not running (make up, make om-token)", allow_module_level=True)

os.environ.setdefault("CURBSIDE_AGENT_NAME", "pytest")
os.environ["CURBSIDE_SQL_SCHEMAS"] = "marts"

from mcp_servers.curbside_mcp.server import mcp  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(name: str, args: dict | None = None):
    async with Client(mcp) as client:
        result = await client.call_tool(name, args or {})
    payload = result.structured_content
    if payload is None and result.content:
        text = result.content[0].text
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = text
    return result.is_error, payload


async def test_exposes_platform_tools():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"run_readonly_sql", "query_metric", "diagnose_asset", "impact_of_change",
            "propose_metadata_change", "record_incident", "get_run_failure"} <= set(tools)
    assert tools["run_readonly_sql"].annotations.read_only_hint is True


async def test_sql_reads_marts():
    is_error, result = await call("run_readonly_sql",
                                  {"sql": "select count(*) as n from marts.dim_community_district"})
    assert not is_error
    assert result["rows"] == [[59]]
    assert len(result["query_id"]) == 8


async def test_sql_guard_blocks_writes_and_out_of_scope_schemas():
    is_error, message = await call("run_readonly_sql", {"sql": "delete from marts.dim_community_district"})
    assert is_error and "rejected by SQL guard" in str(message)
    is_error, message = await call("run_readonly_sql", {"sql": "select * from raw_dsny.monthly_tonnage"})
    assert is_error and "outside this agent's scope" in str(message)


async def test_query_metric_uses_semantic_layer():
    is_error, result = await call("query_metric", {
        "metrics": ["diversion_rate"],
        "group_by": ["community_district__borough"],
        "order_by": ["community_district__borough"],
    })
    assert not is_error, result
    assert result["row_count"] == 5
    assert all(0 < row[1] < 1 for row in result["rows"])
    assert "fct_monthly_tonnage" in result["sql"]
    assert len(result["query_id"]) == 8


async def test_diagnose_asset_reports_known_warning_and_upstream():
    is_error, result = await call("diagnose_asset", {"table": "marts.fct_service_requests"})
    assert not is_error, result
    tests = {t["test"] for t in result["asset"]["tests_not_passing"]}
    assert "not_before_fct_service_requests_closed_at__created_at" in tests
    upstream = {u.get("table") for u in result["upstream"]}
    assert "intermediate.int_311__requests_enriched" in upstream


async def test_impact_of_change_follows_lineage_to_certified_marts():
    is_error, result = await call("impact_of_change", {"table": "raw_dsny.monthly_tonnage"})
    assert not is_error, result
    downstream = {d["table"]: d for d in result["downstream"]}
    assert "marts.mart_district_monthly_scorecard" in downstream
    assert downstream["marts.fct_monthly_tonnage"]["tier"] == "Tier.Tier1"


async def test_proposals_are_validated_and_queued():
    is_error, message = await call("propose_metadata_change", {
        "table": "marts.fct_service_requests", "change_type": "column_tag",
        "column": "no_such_column", "proposed_value": "PII.Sensitive",
        "rationale": "test rationale text",
    })
    assert is_error and "does not exist" in str(message)

    args = {
        "table": "marts.fct_service_requests", "change_type": "column_tag",
        "column": "incident_address", "proposed_value": "PII.Sensitive",
        "rationale": "pytest: street address of the reporter's incident location",
    }
    try:
        is_error, first = await call("propose_metadata_change", args)
        assert not is_error, first
        _, second = await call("propose_metadata_change", args)
        assert second["proposal_id"] == first["proposal_id"] and second["duplicate_of_existing"]
    finally:
        with psycopg.connect("postgresql://curbside_etl:curbside_etl@localhost:5432/curbside") as conn:
            conn.execute("delete from ops.metadata_proposals where agent = 'pytest'")
