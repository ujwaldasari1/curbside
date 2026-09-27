"""Reversible upstream faults injected into the raw layer (data chaos engineering).

Each fault swaps a raw table for a corrupted copy:
  inject:  ALTER TABLE t RENAME TO t__chaos_orig;  CREATE TABLE t AS <corrupted copy>
  restore: DROP TABLE t CASCADE;  ALTER TABLE t__chaos_orig RENAME TO t;  dbt build --full-refresh

The real data is never modified. Every fault names its ground truth (root-cause table,
column and category) so the incident agent's diagnosis can be scored automatically.

  python -m evals.chaos.faults list | inject <name> | restore <name> | restore-all
"""

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg

from shared.env import ROOT, load_dotenv

load_dotenv()

ETL_DSN = "postgresql://curbside_etl:curbside_etl@localhost:5432/curbside"
SUFFIX = "__chaos_orig"


@dataclass(frozen=True)
class Fault:
    name: str
    table: str  # raw table that is swapped (schema.table)
    category: str
    root_cause_column: str | None
    story: str
    # (columns of the original table, original table name) -> SELECT for the corrupted copy
    corrupt: Callable[[list[str], str], str]
    accepted_categories: frozenset = field(default_factory=frozenset)

    @property
    def root_cause_asset(self) -> str:
        return self.table

    def categories(self) -> set[str]:
        return {self.category, *self.accepted_categories}


def _select(columns: list[str], replacements: dict[str, str]) -> str:
    return ", ".join(f"{replacements[c]} AS {c}" if c in replacements else c for c in columns)


def _latest(orig: str) -> str:
    return f"(SELECT max(month) FROM {orig})"


def _pounds_in_latest_month(cols: list[str], orig: str) -> str:
    pounds = "(refusetonscollected::numeric * 2000)::text"
    return f"SELECT {_select(cols, {
        'refusetonscollected': f'CASE WHEN month = {_latest(orig)} THEN {pounds} ELSE refusetonscollected END',
    })} FROM {orig}"


def _null_complaint_types(cols: list[str], orig: str) -> str:
    # Touch source_updated_at too, so the incremental fct_service_requests picks the rows up.
    recent = f"created_date >= (SELECT max(created_date) FROM {orig}) - interval '3 days'"
    return f"SELECT {_select(cols, {
        'complaint_type': f'CASE WHEN {recent} THEN NULL ELSE complaint_type END',
        'source_updated_at': f'CASE WHEN {recent} THEN now() ELSE source_updated_at END',
    })} FROM {orig}"


def _rename_missed_collection(cols: list[str], orig: str) -> str:
    renamed = ("complaint_type = 'Missed Collection' AND "
               f"created_date >= (SELECT max(created_date) FROM {orig}) - interval '10 days'")
    return f"SELECT {_select(cols, {
        'complaint_type': f"CASE WHEN {renamed} THEN 'Missed Collection (All Materials)' ELSE complaint_type END",
        'source_updated_at': f'CASE WHEN {renamed} THEN now() ELSE source_updated_at END',
    })} FROM {orig}"


FAULTS: dict[str, Fault] = {f.name: f for f in [
    Fault(
        "schema_drift_tonnage", "raw_dsny.monthly_tonnage", "schema_drift", "refusetonscollected",
        "The tonnage dataset renamed refusetonscollected to refuse_tons_collected.",
        lambda cols, orig: "SELECT " + ", ".join(
            "refusetonscollected AS refuse_tons_collected" if c == "refusetonscollected" else c
            for c in cols) + f" FROM {orig}",
    ),
    Fault(
        "unit_change_tonnage", "raw_dsny.monthly_tonnage", "unit_change", "refusetonscollected",
        "The latest month's refuse tonnage was published in pounds instead of tons.",
        _pounds_in_latest_month,
        frozenset({"distribution_shift"}),
    ),
    Fault(
        "duplicate_records_tonnage", "raw_dsny.monthly_tonnage", "duplicate_records", None,
        "The latest month was delivered twice.",
        lambda cols, orig: f"SELECT * FROM {orig} UNION ALL SELECT * FROM {orig} WHERE month = {_latest(orig)}",
    ),
    Fault(
        "partial_month_tonnage", "raw_dsny.monthly_tonnage", "late_data", None,
        "Only Manhattan and the Bronx reported the latest month; other boroughs are late.",
        lambda cols, orig: f"SELECT * FROM {orig} WHERE month <> {_latest(orig)} OR borough_id IN ('1', '2')",
        frozenset({"stale_source"}),
    ),
    Fault(
        "referential_break_districts", "raw_reference.community_district_population",
        "referential_break", None,
        "Bronx Community District 1 disappeared from the reference dataset.",
        lambda cols, orig: f"SELECT * FROM {orig} WHERE NOT (borough = 'Bronx' AND cd_number = '1')",
    ),
    Fault(
        "stale_weather", "raw_weather.weather_daily", "stale_source", None,
        "The weather feed stopped updating three weeks ago.",
        lambda cols, orig: f"SELECT * FROM {orig} WHERE date::date < current_date - 21",
        frozenset({"late_data", "upstream_api"}),
    ),
    Fault(
        "null_spike_311", "raw_nyc311.service_requests", "null_spike", "complaint_type",
        "complaint_type arrived null for every request created in the last three days.",
        _null_complaint_types,
    ),
    Fault(
        "renamed_complaint_type_311", "raw_nyc311.service_requests", "distribution_shift",
        "complaint_type",
        "311 renamed 'Missed Collection' to 'Missed Collection (All Materials)' ten days ago.",
        _rename_missed_collection,
        frozenset({"schema_drift", "upstream_api"}),
    ),
]}


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    schema, name = table.split(".")
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position", (schema, name)).fetchall()
    return [r[0] for r in rows]


def is_injected(conn: psycopg.Connection, table: str) -> bool:
    schema, name = table.split(".")
    return conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (schema, name + SUFFIX)).fetchone() is not None


def inject(fault: Fault) -> None:
    schema, name = fault.table.split(".")
    orig = f"{schema}.{name}{SUFFIX}"
    with psycopg.connect(ETL_DSN) as conn:
        if is_injected(conn, fault.table):
            raise RuntimeError(f"{fault.table} already has a fault injected; restore it first")
        columns = _columns(conn, fault.table)
        conn.execute(f"ALTER TABLE {fault.table} RENAME TO {name}{SUFFIX}")
        conn.execute(f"CREATE TABLE {fault.table} AS {fault.corrupt(columns, orig)}")


def restore_table(table: str) -> bool:
    schema, name = table.split(".")
    with psycopg.connect(ETL_DSN) as conn:
        if not is_injected(conn, table):
            return False
        conn.execute(f"DROP TABLE {table} CASCADE")  # dependent staging views are rebuilt by dbt
        conn.execute(f"ALTER TABLE {schema}.{name}{SUFFIX} RENAME TO {name}")
    return True


def rebuild_warehouse() -> None:
    """Rebuild every model from the restored raw layer (full refresh undoes incremental merges)."""
    subprocess.run(["dbt", "build", "--full-refresh", "--quiet"], cwd=ROOT / "transform", check=True,
                   env={**os.environ, "DBT_PROFILES_DIR": str(ROOT / "transform")})


def restore(fault: Fault, rebuild: bool = True) -> None:
    restore_table(fault.table)
    if rebuild:
        rebuild_warehouse()


def restore_all() -> list[str]:
    restored = [t for t in {f.table for f in FAULTS.values()} if restore_table(t)]
    rebuild_warehouse()
    return restored


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    if command == "list":
        for fault in FAULTS.values():
            print(f"{fault.name:30s} {fault.category:18s} {fault.table:42s} {fault.story}")
    elif command == "inject":
        inject(FAULTS[sys.argv[2]])
        print(f"injected {sys.argv[2]}")
    elif command == "restore":
        restore(FAULTS[sys.argv[2]])
        print(f"restored {sys.argv[2]} and rebuilt the warehouse")
    elif command == "restore-all":
        print(f"restored: {restore_all() or 'nothing was injected'}; warehouse rebuilt")
