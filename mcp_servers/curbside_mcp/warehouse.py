"""Warehouse access for the MCP server: read-only queries as curbside_agent_ro, and writes
to the ops schema (proposals, incidents) as curbside_app. Agents never get either DSN."""

import datetime as dt
import decimal
import json
import os
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _dsn(user_var: str, default_user: str, password_var: str) -> str:
    user = os.environ.get(user_var, default_user)
    password = os.environ.get(password_var, default_user)
    host = os.environ.get("CURBSIDE_PG_HOST", "localhost")
    port = os.environ.get("CURBSIDE_PG_PORT", "5432")
    db = os.environ.get("CURBSIDE_PG_DB", "curbside")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def readonly_dsn() -> str:
    return _dsn("CURBSIDE_AGENT_RO_USER", "curbside_agent_ro", "CURBSIDE_AGENT_RO_PASSWORD")


def app_dsn() -> str:
    return _dsn("CURBSIDE_APP_USER", "curbside_app", "CURBSIDE_APP_PASSWORD")


def _jsonable(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    return value


def run_readonly_query(sql: str, max_rows: int, timeout_s: int = 15) -> dict:
    """Execute validated SQL in a read-only transaction; fetch at most max_rows rows."""
    with psycopg.connect(readonly_dsn(), connect_timeout=5) as conn:
        conn.read_only = True
        with conn.transaction():
            conn.execute(f"SET LOCAL statement_timeout = '{int(timeout_s)}s'")
            # A server-side cursor streams rows, so a huge result is never fully fetched.
            with conn.cursor(name="agent_query") as cur:
                cur.execute(sql)
                rows = cur.fetchmany(max_rows + 1)
                columns = [c.name for c in cur.description]
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return {
        "columns": columns,
        "rows": [[_jsonable(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def insert_proposal(agent: str, entity_type: str, entity_fqn: str, change_type: str,
                    column_name: str | None, proposed_value: str, rationale: str,
                    evidence: dict | None) -> tuple[int, bool]:
    """Returns (proposal_id, created). An identical pending proposal is reused, not duplicated."""
    with psycopg.connect(app_dsn(), connect_timeout=5) as conn:
        row = conn.execute(
            """
            INSERT INTO ops.metadata_proposals
                (agent, entity_type, entity_fqn, change_type, column_name, proposed_value,
                 rationale, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_fqn, change_type, coalesce(column_name, ''), proposed_value)
                WHERE status = 'pending'
            DO NOTHING
            RETURNING id
            """,
            (agent, entity_type, entity_fqn, change_type, column_name, proposed_value,
             rationale, Jsonb(evidence) if evidence else None),
        ).fetchone()
        if row:
            return row[0], True
        existing = conn.execute(
            """
            SELECT id FROM ops.metadata_proposals
            WHERE status = 'pending' AND entity_fqn = %s AND change_type = %s
              AND coalesce(column_name, '') = coalesce(%s, '') AND proposed_value = %s
            """,
            (entity_fqn, change_type, column_name, proposed_value),
        ).fetchone()
        return existing[0], False


def pending_proposals(entity_fqn: str | None = None) -> list[dict]:
    with psycopg.connect(readonly_dsn(), connect_timeout=5) as conn:
        cur = conn.execute(
            """
            SELECT id, agent, entity_fqn, change_type, column_name, proposed_value, created_at
            FROM ops.metadata_proposals
            WHERE status = 'pending' AND (%s::text IS NULL OR entity_fqn = %s)
            ORDER BY id
            """,
            (entity_fqn, entity_fqn),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, map(_jsonable, r), strict=True)) for r in cur.fetchall()]


def insert_incident(agent: str, failed_asset: str, title: str, severity: str, root_cause: str,
                    root_cause_asset: str | None, fault_category: str | None,
                    evidence: dict | None, suggested_fix: str | None,
                    dagster_run_id: str | None) -> int:
    with psycopg.connect(app_dsn(), connect_timeout=5) as conn:
        return conn.execute(
            """
            INSERT INTO ops.incidents
                (agent, dagster_run_id, failed_asset, title, severity, root_cause_asset,
                 fault_category, root_cause, evidence, suggested_fix)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (agent, dagster_run_id, failed_asset, title, severity, root_cause_asset,
             fault_category, root_cause, Jsonb(evidence) if evidence else None, suggested_fix),
        ).fetchone()[0]


def to_json(obj: Any) -> str:
    return json.dumps(obj, default=_jsonable)
