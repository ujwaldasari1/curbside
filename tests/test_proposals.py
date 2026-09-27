"""Live test of the approval path: queue -> approve -> OpenMetadata patched -> revert."""

import os

import psycopg
import pytest
import requests

from shared.env import load_dotenv

load_dotenv()


def _stack_up() -> bool:
    try:
        requests.get("http://localhost:8585/api/v1/system/version", timeout=2)
        return bool(os.environ.get("OPENMETADATA_JWT_TOKEN"))
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack_up(), reason="live stack not running")

TABLE = "curbside_warehouse.curbside.marts.fct_district_daily_sanitation"
COLUMN = "illegal_dumping_requests"
ETL = "postgresql://curbside_etl:curbside_etl@localhost:5432/curbside"


def test_approve_applies_column_description_and_tag():
    from governance import proposals
    from mcp_servers.curbside_mcp import warehouse
    from shared.openmetadata import OpenMetadataClient

    om = OpenMetadataClient()

    def column():
        table = om.get_by_name("tables", TABLE, fields="columns,tags")
        return next(c for c in table["columns"] if c["name"] == COLUMN), table["id"]

    before, table_id = column()
    try:
        desc_id, _ = warehouse.insert_proposal(
            "pytest", "table", TABLE, "column_description", COLUMN,
            "pytest: 311 illegal dumping complaints opened that day in the district.",
            "test rationale", None)
        tag_id, _ = warehouse.insert_proposal(
            "pytest", "table", TABLE, "column_tag", COLUMN, "Sanitation.Service Request",
            "test rationale", None)

        assert proposals.approve(desc_id, "pytest") == "applied"
        assert proposals.approve(tag_id, "pytest") == "applied"

        after, _ = column()
        assert after["description"].startswith("pytest:")
        assert "Sanitation.Service Request" in {t["tagFQN"] for t in after.get("tags", [])}
        with pytest.raises(ValueError, match="already applied"):
            proposals.approve(desc_id, "pytest")
    finally:
        # restore the column exactly as it was
        _, _ = column()
        table = om.get_by_name("tables", TABLE, fields="columns,tags")
        index = next(i for i, c in enumerate(table["columns"]) if c["name"] == COLUMN)
        restore = [{"op": "add", "path": f"/columns/{index}/tags", "value": before.get("tags", [])}]
        restore.append({"op": "add", "path": f"/columns/{index}/description",
                        "value": before.get("description") or ""})
        om.patch(f"/v1/tables/{table_id}", restore)
        with psycopg.connect(ETL) as conn:
            conn.execute("delete from ops.metadata_proposals where agent = 'pytest'")
