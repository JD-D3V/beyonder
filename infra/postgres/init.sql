-- Beyonder Postgres init
-- Runs once on first container start.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Alembic will manage app tables. This file only enables extensions
-- and is idempotent enough to re-run safely.
