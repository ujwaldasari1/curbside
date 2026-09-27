"""Human-in-the-loop review of agent metadata proposals (ops.metadata_proposals).

  python -m governance.proposals list
  python -m governance.proposals approve <id> [--by NAME] [--note TEXT]
  python -m governance.proposals reject <id> [--by NAME] [--note TEXT]

Approval builds an RFC 6902 JSON Patch against the entity *as it is now* in
OpenMetadata (column positions can change between proposal and approval), applies it
with the platform's bot credentials, and records reviewer, time and outcome.
"""

import argparse
import getpass

import psycopg
from psycopg.rows import dict_row

from mcp_servers.curbside_mcp.warehouse import app_dsn
from shared.env import load_dotenv
from shared.openmetadata import OpenMetadataClient, OpenMetadataError


def list_proposals(status: str | None = "pending") -> list[dict]:
    with psycopg.connect(app_dsn(), row_factory=dict_row) as conn:
        return conn.execute(
            "SELECT * FROM ops.metadata_proposals WHERE %s::text IS NULL OR status = %s ORDER BY id",
            (status, status),
        ).fetchall()


def _label(om: OpenMetadataClient, fqn: str) -> dict:
    source = "Classification" if om.get_by_name("tags", fqn) else "Glossary"
    return {"tagFQN": fqn, "source": source, "labelType": "Manual", "state": "Confirmed"}


def build_patch(om: OpenMetadataClient, proposal: dict) -> list[dict]:
    table = om.get_by_name("tables", proposal["entity_fqn"], fields="columns,tags")
    if table is None:
        raise ValueError(f"{proposal['entity_fqn']} no longer exists in OpenMetadata")
    change, value = proposal["change_type"], proposal["proposed_value"]

    if change == "table_description":
        return [{"op": "add", "path": "/description", "value": value}]
    if change == "table_tag":
        if any(t["tagFQN"] == value for t in table.get("tags", [])):
            return []
        return [{"op": "add", "path": "/tags/-", "value": _label(om, value)}]

    index = next((i for i, c in enumerate(table["columns"]) if c["name"] == proposal["column_name"]), None)
    if index is None:
        raise ValueError(f"column {proposal['column_name']} no longer exists")
    column = table["columns"][index]
    if change == "column_description":
        return [{"op": "add", "path": f"/columns/{index}/description", "value": value}]
    if change == "column_tag":
        tags = column.get("tags") or []
        if any(t["tagFQN"] == value for t in tags):
            return []
        if not tags:
            return [{"op": "add", "path": f"/columns/{index}/tags", "value": [_label(om, value)]}]
        return [{"op": "add", "path": f"/columns/{index}/tags/-", "value": _label(om, value)}]
    raise ValueError(f"unsupported change_type {change}")


def _set_status(proposal_id: int, status: str, reviewer: str, note: str | None, error: str | None = None):
    with psycopg.connect(app_dsn()) as conn:
        conn.execute(
            """
            UPDATE ops.metadata_proposals
            SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s, apply_error = %s
            WHERE id = %s
            """,
            (status, reviewer, note, error, proposal_id),
        )


def _get(proposal_id: int) -> dict:
    with psycopg.connect(app_dsn(), row_factory=dict_row) as conn:
        row = conn.execute("SELECT * FROM ops.metadata_proposals WHERE id = %s", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"proposal {proposal_id} not found")
    if row["status"] != "pending":
        raise ValueError(f"proposal {proposal_id} is already {row['status']}")
    return row


def approve(proposal_id: int, reviewer: str, note: str | None = None) -> str:
    proposal = _get(proposal_id)
    om = OpenMetadataClient()
    try:
        patch = build_patch(om, proposal)
        if patch:
            table = om.get_by_name("tables", proposal["entity_fqn"])
            om.patch(f"/v1/tables/{table['id']}", patch)
    except (OpenMetadataError, ValueError) as err:
        _set_status(proposal_id, "failed", reviewer, note, str(err)[:1000])
        return "failed"
    _set_status(proposal_id, "applied", reviewer, note)
    return "applied"


def reject(proposal_id: int, reviewer: str, note: str | None = None) -> str:
    _get(proposal_id)
    _set_status(proposal_id, "rejected", reviewer, note)
    return "rejected"


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["list", "approve", "reject"])
    parser.add_argument("id", nargs="?", type=int)
    parser.add_argument("--by", default=getpass.getuser())
    parser.add_argument("--note")
    args = parser.parse_args()
    if args.action == "list":
        for p in list_proposals():
            target = p["entity_fqn"].split(".", 2)[-1] + (f".{p['column_name']}" if p["column_name"] else "")
            print(f"#{p['id']:<4} {p['agent']:<9} {p['change_type']:<19} {target:<55} -> {p['proposed_value'][:70]}")
        return
    if args.id is None:
        parser.error("id is required")
    action = approve if args.action == "approve" else reject
    print(f"proposal {args.id}: {action(args.id, args.by, args.note)}")


if __name__ == "__main__":
    main()
