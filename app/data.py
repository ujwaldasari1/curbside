"""Data access for the Streamlit app (read-only role for reads, app role for ops writes)."""

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
import requests  # noqa: E402

from shared.env import load_dotenv  # noqa: E402

load_dotenv()

from mcp_servers.curbside_mcp.warehouse import app_dsn, readonly_dsn  # noqa: E402

OM_UI = "http://localhost:8585"
DAGSTER_UI = "http://127.0.0.1:3000"


def _frame(cur: psycopg.Cursor) -> pd.DataFrame:
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    # Postgres numeric arrives as Decimal and date as datetime.date: object columns that
    # st.line_chart silently draws as an empty chart. Convert them to float / datetime.
    for col in df.columns:
        first = df[col].dropna().iloc[0] if df[col].notna().any() else None
        if isinstance(first, Decimal):
            df[col] = df[col].astype(float)
        elif isinstance(first, dt.date) and not isinstance(first, dt.datetime):
            df[col] = pd.to_datetime(df[col])
    return df


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with psycopg.connect(readonly_dsn(), connect_timeout=5) as conn:
        return _frame(conn.execute(sql, params))


def app_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with psycopg.connect(app_dsn(), connect_timeout=5) as conn:
        return _frame(conn.execute(sql, params))


def service_up(url: str) -> bool:
    try:
        return requests.get(url, timeout=2).ok
    except requests.RequestException:
        return False


def latest_runs(limit: int = 5) -> list[dict]:
    q = f"{{ runsOrError(limit: {limit}) {{ ... on Runs {{ results {{ runId jobName status startTime }} }} }} }}"
    try:
        body = requests.post(f"{DAGSTER_UI}/graphql", json={"query": q}, timeout=5).json()
        return body["data"]["runsOrError"]["results"]
    except (requests.RequestException, KeyError, TypeError):
        return []
