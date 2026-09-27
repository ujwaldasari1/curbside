"""Runtime configuration shared by the ingestion pipelines (read from environment / .env)."""

import os

import dlt


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def warehouse_url() -> str:
    return (
        f"postgresql://{env('CURBSIDE_ETL_USER', 'curbside_etl')}:"
        f"{env('CURBSIDE_ETL_PASSWORD', 'curbside_etl')}@"
        f"{env('CURBSIDE_PG_HOST', 'localhost')}:{env('CURBSIDE_PG_PORT', '5432')}/"
        f"{env('CURBSIDE_PG_DB', 'curbside')}"
    )


def postgres_destination():
    return dlt.destinations.postgres(credentials=warehouse_url())


# Earliest 311 request (by created_date) to keep locally. 2025-01-01 is ~600k DSNY rows.
SR_START_DATE = env("CURBSIDE_311_START_DATE", "2025-01-01")
SOCRATA_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN") or None
