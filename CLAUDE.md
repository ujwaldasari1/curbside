# Curbside: notes for Claude

AI-native, metadata-driven data platform for NYC sanitation data: dlt → Postgres → dbt →
Dagster, cataloged in OpenMetadata, with three Claude agents (analyst, steward, incident)
that reach the platform only through MCP. README.md has the architecture and quickstart;
docs/infra.svg shows what runs where. Current status and open items: docs/HANDOFF.md.

## Commands
- `make test` (pytest; live integration tests skip when the stack is down), `make lint` (ruff)
- `make up` / `make down`: Postgres + OpenMetadata + Elasticsearch in Docker
- `make dagster` (UI 127.0.0.1:3000), `make app` (Streamlit, 127.0.0.1:8501, or the next
  free port if 8501 is taken)
- Paid, calls the Anthropic API: `make ask Q=...`, `make steward`, `make incident`,
  `make eval-*`, and the Chaos lab / Ask pages in the console. Ask before running these.

## Invariants (don't weaken)
- Agents run with `tools=[]`, `setting_sources=[]`, `strict_mcp_config`, an explicit tool
  allow-list, budget and turn caps. OpenMetadata write tools are disallowed and denied again
  by a PreToolUse hook. The only catalog write path is a human approving a proposal
  (governance/proposals.py builds a JSON Patch).
- SQL from agents goes through the sqlglot guard in curbside-mcp, then runs as
  `curbside_agent_ro` (read-only, 15 s timeout, row cap). Queue writes use `curbside_app`.
- The analyst's `sql` field is filled in code from tool results (`evidence_query_ids`),
  never written by the model. `other_sql_run` holds exploratory queries.
- Every service binds to 127.0.0.1 (compose `!override` in infra/docker-compose.curbside.yml,
  `--server.address` in `make app`).
- Secrets live only in `.env` (gitignored). Never print or commit them.

## Cost controls
- Dagster `triage_on_failure` sensor is deliberately STOPPED (the owner wants no automatic
  API spend). Turn it on only when asked; the Chaos-lab demo needs it on to auto-run the
  incident agent.
- `metadata_stewardship_schedule` is off by default. `daily_refresh_schedule` (06:00 ET)
  is free: dlt + dbt only.
- Prefer single-agent work over multi-agent workflows unless the owner asks for one.

## Conventions
- Commit messages: short title, then bullets explaining why; no local paths or secrets.
- Postgres `numeric` comes back as `Decimal` and `date` as `datetime.date`; app/data.py
  converts them for charts. Do the same in any new pandas/chart code.
- Pushing: the repo is private at github.com/ujwaldasari1/curbside. The GitHub CLI token
  needs the `workflow` scope because the push includes .github/workflows.
