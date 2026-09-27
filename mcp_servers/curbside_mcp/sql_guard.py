"""Static validation for agent-authored SQL. First of three layers of defence:

  1. this guard (parse with sqlglot, allow exactly one read-only query over allowed schemas)
  2. the curbside_agent_ro Postgres role (SELECT-only grants, default_transaction_read_only)
  3. per-session statement_timeout and a row cap in warehouse.py

Note: sqlglot parses data-modifying CTEs, SELECT ... INTO and SELECT ... FOR UPDATE as
`Select`, so checking the root node type alone is not enough; the whole tree is walked.
"""

import fnmatch

import sqlglot
from sqlglot import exp

WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Command,  # anything sqlglot cannot model: VACUUM, SET ROLE, DO blocks, ...
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Into,  # SELECT ... INTO creates a table
    exp.Lock,  # SELECT ... FOR UPDATE takes row locks
)

# Server-side functions that sleep, touch the filesystem, reach other databases or
# change session state. Lower-case names.
FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "set_config",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "txid_current",
}

ALWAYS_ALLOWED_SCHEMAS = {"information_schema"}


class UnsafeSQLError(ValueError):
    """Raised when a query is not a single read-only statement over allowed schemas."""


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() or "").lower()


def validate_readonly_sql(sql: str, allowed_schemas: list[str]) -> str:
    """Return normalised SQL if safe, else raise UnsafeSQLError.

    allowed_schemas supports shell-style wildcards, e.g. ["marts", "raw_*"].
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as err:
        raise UnsafeSQLError(f"could not parse SQL: {err}") from err
    if len(statements) != 1:
        raise UnsafeSQLError(f"expected exactly one statement, got {len(statements)}")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise UnsafeSQLError(f"only SELECT queries are allowed, got {type(statement).__name__}")

    for node in statement.walk():
        if isinstance(node, WRITE_NODES):
            raise UnsafeSQLError(f"write or session-changing clause not allowed: {type(node).__name__}")
        if isinstance(node, exp.Func) and _function_name(node) in FORBIDDEN_FUNCTIONS:
            raise UnsafeSQLError(f"function not allowed: {_function_name(node)}")

    cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        if not table.name:  # table-valued functions such as generate_series
            continue
        if not table.db:
            if table.name in cte_names:
                continue
            raise UnsafeSQLError(f"table '{table.name}' must be schema-qualified (e.g. marts.{table.name})")
        if table.catalog and table.catalog != "curbside":
            raise UnsafeSQLError(f"cross-database reference not allowed: {table.catalog}")
        schema = table.db
        if schema in ALWAYS_ALLOWED_SCHEMAS:
            continue
        if not any(fnmatch.fnmatch(schema, pattern) for pattern in allowed_schemas):
            raise UnsafeSQLError(
                f"schema '{schema}' is outside this agent's scope (allowed: {', '.join(allowed_schemas)})"
            )

    return statement.sql(dialect="postgres")
