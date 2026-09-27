# Research notes (September 2026)

These are the ecosystem facts behind Curbside's design choices, checked against primary
sources in late September 2026. Each one was fact-checked by a second, independent pass.

## OpenMetadata 2.0.2
- **Release:** 2.0.2 shipped 2026-09-16 (2.0.0 went GA 2026-08-24).
  [releases](https://github.com/open-metadata/OpenMetadata/releases)
- **Built-in MCP server:** on by default at `{OM}/mcp` over stateless Streamable HTTP.
  - 2.0.2 consolidated 24 tools down to **15** (11 read, 4 write). There is no SQL, delete
    or test-result push tool.
  - Auth is OAuth, a personal access token, or a bot JWT, with RBAC enforced. Login-form
    sessions expire after an hour, so headless agents should use a bot JWT.
  - [MCP docs](https://docs.open-metadata.org/v2.0.x/how-to-guides/mcp.md)
- **Ingestion without Airflow:** ingestion runs anywhere via the `metadata` CLI, and
  Airflow as the internal orchestrator is deprecated from 2.1.
  [external ingestion](https://docs.open-metadata.org/v2.0.x/deployment/ingestion/external)
- **Connectors:**
  - There is **no official DuckDB connector**, and the standalone Iceberg connector was
    removed in 1.13. That's why the warehouse is Postgres.
  - dbt Core ingestion is production-grade: dbt tests become OpenMetadata test cases with
    results.
  - [connectors](https://docs.open-metadata.org/v2.0.x/connectors)
- **Open-source vs. paid:** Collate sells the Documentation, Tier and Data Quality agents
  and NL-to-SQL. Curbside rebuilds equivalents on the open-source MCP server plus Claude.
  [comparison](https://www.getcollate.io/comparison)
- **Dagster connector:** the 2.0.2 connector resolves `[schema, table]` asset keys to
  tables and stamps lineage with the pipeline. I verified this in the connector source;
  older docs describe asset lineage as missing.
- **Licensing:** the `openmetadata-ingestion` package is under the Collate Community
  License. That's fine for a personal project, but it matters for anyone redistributing a
  connector built on it.

## MCP
- **Spec:** the latest revision is 2026-07-28 (stateless core, multi-round-trip
  requests, Tasks moved to an extension).
  [changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- **Python SDK:** the official Python SDK is `mcp` v2.x, where `FastMCP` was renamed
  `MCPServer`. [PyPI](https://pypi.org/project/mcp/)
- **Transaction-level read-only is not enough on its own.** The deprecated reference
  Postgres MCP server accepted `COMMIT; DROP SCHEMA …`. Hence Curbside's layered guard
  (parse, role, timeout).
  [Datadog write-up](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)
- **Gaps:** in September 2026 there is no open-source "pipeline-ops" MCP server that
  combines orchestrator state, dbt artifacts, catalog lineage and data-quality results
  for incident triage. curbside-mcp fills that niche.

## Agents
- **SDK:** the Claude Agent SDK (Python) is `claude-agent-sdk` 0.2.160 and bundles the
  Claude Code CLI.
  - `tools=[]` removes the built-in tools.
  - `setting_sources=[]` stops `~/.claude` settings from leaking into an agent.
  - `output_format` gives structured results.
  - [docs](https://code.claude.com/docs/en/agent-sdk/python)
- **Semantic layer vs. text-to-SQL:** in dbt Labs' April 2026 benchmark on modeled data,
  semantic-layer answers beat text-to-SQL, 98.2% vs 90.0% with Sonnet 4.6. That's why the
  analyst uses `query_metric` first.
  [dbt blog](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)

## Local stack on a 16 GB Mac
- **Container runtime:** OrbStack is free for personal use and returns idle VM memory to
  macOS. Apple's `container` tool has no Compose support.
  [licensing](https://docs.orbstack.dev/licensing)
- **dbt:** dbt v2 (the Rust engine) went GA 2026-09-14 but does not support Postgres yet.
  dbt Core 1.12 is the right choice here.
  [upgrade guide](https://docs.getdbt.com/docs/dbt-versions/dbt-upgrade/upgrading-to-v2)
- **Ingestion tools:** Airbyte's local install needs at least 8 GB even in low-resource
  mode, so dlt was the fit.
- **Measured OpenMetadata footprint** (server + Elasticsearch + Postgres, no Airflow):
  about **3.0 GB**.

## NYC Open Data specifics
- **The 311 `:updated_at` system field is noisy:** a daily refresh re-touches around 550k
  rows across all agencies, but only about 1k changed in business terms.
  - For the **DSNY slice** I measured 13,409 rows re-touched in two days vs 1,265 real
    changes (resolution or closure).
  - A 45-day rolling window would pull 43,243 rows and still need catch-up logic for older
    rows.
  - So Curbside keeps `:updated_at` as the cursor (it's complete, and ~10× overhead is
    cheap at this size) and merges on `unique_key`.
- **Future dates:** 311 publishes future-dated `closed_date` values (as late as 2033),
  hence the `not_in_future` tests.
- **Non-residential district codes:** 311 `community_board` has 72+ values against 59
  residential districts. `0 Unspecified` and joint interest areas (parks, airports) are
  mapped explicitly.
- **Reuse terms:** NYC Open Data places no restrictions on reuse.
  [FAQ](https://www.nyc.gov/opendata/get-started/FAQs)
