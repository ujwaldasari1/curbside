import pytest

from mcp_servers.curbside_mcp.sql_guard import UnsafeSQLError, validate_readonly_sql

MARTS = ["marts"]
ALL = ["marts", "staging", "intermediate", "raw_*", "ops"]


@pytest.mark.parametrize(
    "sql",
    [
        "select * from marts.fct_monthly_tonnage",
        "with t as (select boro_cd from marts.dim_community_district) select * from t",
        "select boro_cd from marts.fct_monthly_tonnage union select boro_cd from marts.dim_community_district",
        "select d from generate_series(1, 3) as d",
        "select column_name from information_schema.columns where table_schema = 'marts'",
        "select count(*) from curbside.marts.fct_service_requests",
    ],
)
def test_allows_read_only_queries(sql):
    assert validate_readonly_sql(sql, MARTS)


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("insert into marts.x values (1)", "only SELECT"),
        ("update marts.fct_monthly_tonnage set refuse_tons = 0", "only SELECT"),
        ("delete from marts.fct_monthly_tonnage", "only SELECT"),
        ("drop table marts.fct_monthly_tonnage", "only SELECT"),
        ("select 1; drop table marts.fct_monthly_tonnage", "exactly one statement"),
        ("with x as (delete from marts.fct_monthly_tonnage returning *) select * from x", "Delete"),
        ("select * into marts.copy from marts.fct_monthly_tonnage", "Into"),
        ("select * from marts.fct_monthly_tonnage for update", "Lock"),
        ("copy marts.fct_monthly_tonnage to '/tmp/x.csv'", "only SELECT"),
        ("select pg_sleep(30)", "pg_sleep"),
        ("select pg_read_file('/etc/passwd')", "pg_read_file"),
        ("select set_config('role', 'postgres', false)", "set_config"),
        ("set role postgres", "only SELECT"),
        ("select * from fct_monthly_tonnage", "schema-qualified"),
        ("select * from raw_nyc311.service_requests", "outside this agent's scope"),
        ("select * from pg_catalog.pg_authid", "outside this agent's scope"),
        ("select * from other_db.marts.fct_monthly_tonnage", "cross-database"),
    ],
)
def test_rejects_unsafe_queries(sql, reason):
    with pytest.raises(UnsafeSQLError, match=reason):
        validate_readonly_sql(sql, MARTS)


def test_wildcard_scopes_allow_raw_for_incident_agent():
    assert validate_readonly_sql("select * from raw_nyc311.service_requests limit 1", ALL)
    with pytest.raises(UnsafeSQLError):
        validate_readonly_sql("select * from public.anything", ALL)
