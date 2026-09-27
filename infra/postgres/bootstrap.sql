-- Curbside warehouse bootstrap. Idempotent: safe to run on every `make up`.
-- Runs as the postgres superuser inside the OpenMetadata Postgres container.
--
-- Roles
--   curbside_etl       owns the warehouse; used by dlt and dbt
--   curbside_app       writes operational tables (proposals, incidents, eval runs)
--   curbside_agent_ro  read-only, statement-timeout-bound role behind the agents' SQL tool
--   openmetadata_reader  read-only role for OpenMetadata's Postgres connector / profiler

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'curbside_etl') THEN
    CREATE ROLE curbside_etl LOGIN PASSWORD 'curbside_etl';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'curbside_app') THEN
    CREATE ROLE curbside_app LOGIN PASSWORD 'curbside_app';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'curbside_agent_ro') THEN
    CREATE ROLE curbside_agent_ro LOGIN PASSWORD 'curbside_agent_ro';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'openmetadata_reader') THEN
    CREATE ROLE openmetadata_reader LOGIN PASSWORD 'openmetadata_reader';
  END IF;
END
$$;

-- Defense in depth for the agent role: even if a write slipped past the SQL guardrail,
-- Postgres itself refuses it, and runaway queries are cut off.
ALTER ROLE curbside_agent_ro SET default_transaction_read_only = on;
ALTER ROLE curbside_agent_ro SET statement_timeout = '15s';
ALTER ROLE openmetadata_reader SET default_transaction_read_only = on;

SELECT 'CREATE DATABASE curbside OWNER curbside_etl'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'curbside')\gexec

\connect curbside

GRANT CONNECT ON DATABASE curbside TO curbside_app, curbside_agent_ro, openmetadata_reader;

-- Schemas are created up front (owned by curbside_etl) so default privileges apply to
-- every table dlt or dbt creates later.
CREATE SCHEMA IF NOT EXISTS raw_nyc311   AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS raw_dsny     AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS raw_reference AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS raw_weather  AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS staging      AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS intermediate AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS marts        AUTHORIZATION curbside_etl;
CREATE SCHEMA IF NOT EXISTS ops          AUTHORIZATION curbside_etl;

DO $$
DECLARE
  s text;
BEGIN
  FOREACH s IN ARRAY ARRAY['raw_nyc311','raw_dsny','raw_reference','raw_weather',
                           'staging','intermediate','marts','ops']
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO curbside_agent_ro, openmetadata_reader, curbside_app', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO curbside_agent_ro, openmetadata_reader', s);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE curbside_etl IN SCHEMA %I '
                   'GRANT SELECT ON TABLES TO curbside_agent_ro, openmetadata_reader', s);
  END LOOP;
END
$$;

-- The app role writes only to the ops schema (proposal queue, incidents, eval runs).
GRANT CREATE ON SCHEMA ops TO curbside_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ops TO curbside_app;
ALTER DEFAULT PRIVILEGES FOR ROLE curbside_etl IN SCHEMA ops
  GRANT SELECT, INSERT, UPDATE ON TABLES TO curbside_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ops TO curbside_app;
ALTER DEFAULT PRIVILEGES FOR ROLE curbside_etl IN SCHEMA ops
  GRANT USAGE, SELECT ON SEQUENCES TO curbside_app;
