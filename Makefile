SHELL := /bin/bash
export PATH := $(HOME)/.orbstack/bin:/opt/homebrew/bin:$(HOME)/.local/bin:$(PATH)
export PYTHONPATH := $(CURDIR)
export DBT_PROFILES_DIR := $(CURDIR)/transform
export DBT_PROJECT_DIR := $(CURDIR)/transform
export DAGSTER_HOME := $(CURDIR)/.dagster_home
export CURBSIDE_ROOT := $(CURDIR)
OM_METADATA := $(CURDIR)/infra/openmetadata/ingestion/.venv/bin/metadata
OM_WORKFLOWS := $(CURDIR)/infra/openmetadata/ingestion/workflows

# Load local secrets/config (ANTHROPIC_API_KEY, OM token, ...) if present.
ifneq (,$(wildcard .env))
include .env
export
endif

COMPOSE := docker compose -p curbside --project-directory infra --env-file infra/compose.env \
	-f infra/openmetadata/docker-compose.yml -f infra/docker-compose.curbside.yml
PG := docker exec -i openmetadata_postgresql psql -v ON_ERROR_STOP=1 -U postgres

.PHONY: help
help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

# ---------------------------------------------------------------- infrastructure
.PHONY: up down pull ps db-bootstrap mem
pull: ## Pull container images
	$(COMPOSE) pull postgresql elasticsearch execute-migrate-all openmetadata-server

up: ## Start Postgres + OpenMetadata (no Airflow) and bootstrap the warehouse
	$(COMPOSE) up -d --wait postgresql
	$(MAKE) db-bootstrap
	$(COMPOSE) up -d --wait openmetadata-server
	@echo "OpenMetadata UI: http://localhost:8585  (admin@open-metadata.org / admin)"

up-db: ## Start only Postgres (enough for the data pipeline)
	$(COMPOSE) up -d --wait postgresql
	$(MAKE) db-bootstrap

down: ## Stop all containers (data is kept)
	$(COMPOSE) down

ps: ## Container status
	$(COMPOSE) ps

db-bootstrap: ## Create the curbside database, schemas, roles and ops tables (idempotent)
	$(PG) -f /curbside/bootstrap.sql
	$(PG) -d curbside -f /curbside/ops.sql

mem: ## Show container memory usage
	docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'

# ---------------------------------------------------------------- python env
.PHONY: install
install: ## Create/refresh the uv virtualenv
	uv sync

# ---------------------------------------------------------------- data pipeline
.PHONY: ingest dbt-build pipeline
ingest: ## Run all dlt ingestion pipelines
	uv run python -m ingestion.run

dbt-build: ## dbt deps + build (models, tests, seeds)
	cd transform && uv run dbt build

pipeline: ingest dbt-build ## Ingest then transform (without Dagster)

# ---------------------------------------------------------------- openmetadata
.PHONY: om-install om-token om-seed om-ingest om-profile om-classify
om-install: ## Create the isolated openmetadata-ingestion virtualenv
	uv sync --project infra/openmetadata/ingestion

om-token: ## Store the ingestion-bot JWT in .env
	uv run python -m governance.bot_token

om-seed: ## Governance as code: team, domain, glossary (run before om-ingest)
	uv run python -m governance.seed_governance pre

om-ingest: ## Full catalog sync: governance, warehouse, dbt, Dagster, data product, source lineage
	uv run python -m governance.catalog_sync

om-profile: ## Profile the marts (column statistics)
	$(OM_METADATA) profile -c $(OM_WORKFLOWS)/profiler.yaml

om-classify: ## OpenMetadata's built-in PII auto-classification (eval baseline)
	$(OM_METADATA) classify -c $(OM_WORKFLOWS)/auto_classification.yaml

# ---------------------------------------------------------------- one-shot setup
.PHONY: setup
setup: install om-install up om-token pipeline om-ingest ## Fresh clone -> running platform (~15 min, mostly the 311 backfill)
	@echo "Done. Next: make dagster (UI :3000), make app (UI :8501), add ANTHROPIC_API_KEY to .env for agents"

# ---------------------------------------------------------------- quality
.PHONY: test lint dq-coverage
test: ## Unit tests + live integration tests (integration tests skip if the stack is down)
	uv run pytest -q

lint: ## Ruff
	uv run ruff check .

dq-coverage: ## Free: inject every chaos fault and confirm a data test catches it
	uv run python -m evals.chaos.detection

# ---------------------------------------------------------------- agents + app
.PHONY: app ask steward incident proposals approve reject
app: ## Streamlit console at http://localhost:8501 (next free port if taken)
	uv run streamlit run app/streamlit_app.py --server.address 127.0.0.1

ask: ## Analyst agent: make ask Q="Which borough diverts the most waste?"
	uv run python -m agents.analyst "$(Q)"

steward: ## Steward agent: queue catalog improvements for approval
	uv run python -m agents.steward $(TABLES)

incident: ## Incident agent: make incident RUN=<dagster run id> (default: latest failed run)
	uv run python -m agents.incident $(RUN)

proposals: ## List metadata proposals waiting for approval
	uv run python -m governance.proposals list

approve: ## make approve ID=<proposal id>
	uv run python -m governance.proposals approve $(ID)

reject: ## make reject ID=<proposal id>
	uv run python -m governance.proposals reject $(ID)

# ---------------------------------------------------------------- chaos + evals
.PHONY: chaos chaos-restore eval-analyst eval-steward eval-chaos
chaos: ## Break something: make chaos FAULT=unit_change_tonnage (the failure sensor calls the incident agent)
	uv run python -m evals.chaos.faults inject $(FAULT)
	uv run python -c "from evals.chaos import dagster_runs; print('run', dagster_runs.launch('transform_only'))"

chaos-restore: ## Undo all injected faults and rebuild the warehouse
	uv run python -m evals.chaos.faults restore-all

eval-analyst: ## Golden-question eval (costs API credits; LIMIT=1 to measure)
	uv run python -m evals.run_evals analyst $(if $(LIMIT),--limit $(LIMIT),)

eval-steward: ## PII tagging eval vs OpenMetadata auto-classification (costs API credits)
	uv run python -m evals.run_evals steward

eval-chaos: ## Incident root-cause eval over injected faults (costs API credits): FAULTS="a b"
	uv run python -m evals.run_evals chaos $(FAULTS)

# ---------------------------------------------------------------- orchestration
.PHONY: dbt-parse dagster materialize
dbt-parse: ## Regenerate the dbt manifest Dagster loads
	cd transform && uv run dbt parse --quiet

dagster: dbt-parse ## Dagster UI + daemon (schedules) at http://127.0.0.1:3000
	uv run dagster dev -m orchestration.definitions -h 127.0.0.1 -p 3000

materialize: dbt-parse ## Headless: materialize every asset once (ingest + dbt build)
	uv run dagster asset materialize -m orchestration.definitions --select '*'
