-- Operational tables for the agent layer. Idempotent. Created as curbside_etl so the
-- default privileges from bootstrap.sql apply (curbside_app: read/write, agents: read).
SET ROLE curbside_etl;

-- Human-in-the-loop queue: agents propose metadata changes, people approve them, and only
-- then are they applied to OpenMetadata (see governance/proposals.py).
CREATE TABLE IF NOT EXISTS ops.metadata_proposals (
    id              bigserial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    agent           text        NOT NULL,
    entity_type     text        NOT NULL,
    entity_fqn      text        NOT NULL,
    change_type     text        NOT NULL CHECK (change_type IN
                        ('table_description', 'column_description', 'column_tag', 'table_tag')),
    column_name     text,
    proposed_value  text        NOT NULL,
    rationale       text        NOT NULL,
    evidence        jsonb,
    status          text        NOT NULL DEFAULT 'pending' CHECK (status IN
                        ('pending', 'approved', 'rejected', 'applied', 'failed')),
    reviewed_by     text,
    reviewed_at     timestamptz,
    review_note     text,
    apply_error     text
);
CREATE UNIQUE INDEX IF NOT EXISTS metadata_proposals_one_pending
    ON ops.metadata_proposals (entity_fqn, change_type, coalesce(column_name, ''), proposed_value)
    WHERE status = 'pending';

-- Root-cause reports written by the incident agent.
CREATE TABLE IF NOT EXISTS ops.incidents (
    id                bigserial PRIMARY KEY,
    created_at        timestamptz NOT NULL DEFAULT now(),
    agent             text        NOT NULL,
    dagster_run_id    text,
    failed_asset      text        NOT NULL,
    title             text        NOT NULL,
    severity          text        NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    root_cause_asset  text,
    fault_category    text,
    root_cause        text        NOT NULL,
    evidence          jsonb,
    suggested_fix     text,
    status            text        NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved'))
);

-- One row per agent run (evals and production): cost, latency, outcome.
CREATE TABLE IF NOT EXISTS ops.agent_runs (
    id              bigserial PRIMARY KEY,
    started_at      timestamptz NOT NULL DEFAULT now(),
    agent           text        NOT NULL,
    trigger         text        NOT NULL,
    session_id      text,
    model           text,
    num_turns       int,
    duration_ms     int,
    total_cost_usd  numeric(10, 4),
    is_error        boolean,
    result_summary  text
);

RESET ROLE;
