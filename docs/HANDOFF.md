# Handoff: state as of 2026-09-30

## Done
- **Analyst provenance.** The `sql` field is filled from the SQL that actually ran. The
  model cites `query_id`s in `evidence_query_ids`, and superseded queries go to
  `other_sql_run`. Verified live: the cited SQL reproduces every number in the answer.
  The prompt also bans statistical-significance language on complete counts.
- **Network hardening.** Postgres, Elasticsearch, OpenMetadata, Dagster and Streamlit bind
  to 127.0.0.1 only. .gitignore now covers `.env.*`, `.envrc`, `.streamlit/secrets.toml`,
  `.claude/settings.local.json` and any `docker-volume/`.
- **Console.** The Overview diversion chart was empty (a Decimal/date dtype bug) and is
  fixed. Overview now also shows dataset figures (609k 311 requests, 436 tonnage months)
  and a weekly 311 chart.
- **Docs.** docs/infra.svg (what runs where, light and dark) and docs/curbside-overview.png
  (logo overview, also used for LinkedIn) are both in the README. The README Mermaid chart
  was corrected: curbside-mcp reaches OpenMetadata over REST, not MCP.
- **GitHub.** Private repo created. The first CI run passed (lint + unit tests, and the
  30-day live pipeline on a throwaway Postgres).
- **Secrets scan** over the full git history, including unreachable objects: no real
  secrets anywhere. The role passwords in bootstrap.sql are local-only defaults.

## Runtime state on the original laptop
- Docker containers run from `make up`. Dagster and Streamlit were started in the
  background with logs in `logs/`.
- Dagster: `triage_on_failure` is STOPPED on purpose (no automatic API spend),
  `daily_refresh_schedule` is running, and the stewardship schedule is off.
- Agent spend so far: about $0.63 (3 analyst runs).

## Open items
- **Evals not run yet** (`make eval-analyst LIMIT=1` first to measure cost, then the full
  suites). evals/reports/ is empty, although the README links to it.
- **CI warnings:** bump `actions/checkout` and `astral-sh/setup-uv` off Node 20.
  `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19.
- **Before making the repo public:** rewrite the commit author email to the GitHub
  no-reply address, and add a LICENSE.
- **OpenMetadata MCP inside Claude Code** returns 401 unless the editor is launched with
  `OPENMETADATA_JWT_TOKEN` in its environment. .mcp.json expands the variable. The agents
  are unaffected.
- **Minor:** evals/ and tests/ hardcode local DSNs instead of honouring the
  `CURBSIDE_*_PASSWORD` overrides.

## Setting up on another machine
1. `gh repo clone ujwaldasari1/curbside` (needs access to the private repo).
2. Install uv and Docker (OrbStack on macOS), then `make setup`, which takes about 15
   minutes, mostly the 311 backfill.
3. `cp .env.example .env`, run `make om-token` for the OpenMetadata bot token, and add
   `ANTHROPIC_API_KEY`. The agents use this key, not your Claude Code login.
4. `make dagster` and `make app`. Stop the `triage_on_failure` sensor again if you want
   no automatic spend.
