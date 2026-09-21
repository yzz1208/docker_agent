# Upgrade Phase 6 — Production and Deployment Hardening

## Goal

Phase 6 turns the Docker Support Agent from a locally complete product into a repeatable,
versioned, deployable service.

The focus is operational correctness:

~~~text
schema changes are versioned
builds are reproducible
environments are explicit
services start and stop predictably
CI validates backend/frontend/evaluation gates
deployment has health and monitoring contracts
~~~

Phase 6 deliberately does not expand Agent intelligence.

## Target Delivery Architecture

~~~text
GitHub
  ↓
CI
  ├─ Ruff
  ├─ pytest
  ├─ frontend typecheck/test/build
  ├─ migration validation
  └─ evaluation regression gate
  ↓
container images
  ├─ backend
  └─ frontend
  ↓
production compose / deployment target
  ├─ FastAPI
  ├─ PostgreSQL + pgvector
  ├─ web
  └─ Prometheus-ready metrics
~~~

## Step 1 — Versioned Database Migrations

Introduce Alembic for product-facing persistence tables.

Production/deployment schema management becomes:

~~~text
alembic upgrade head
~~~

rather than application-side:

~~~text
metadata.create_all()
~~~

The ORM metadata remains the model source of truth, while migration revisions are the
deployment history.

### Scope

The initial migration covers the current product persistence schema:

~~~text
agent_configurations
conversations
messages
agent_executions
agent_runs
evaluation_runs
evaluation_case_results
~~~

The existing document/vector indexing schema remains managed by its dedicated indexing
workflow in this step and is not silently folded into the product migration history.

### Existing local databases

Phase 5 databases may already contain the exact current tables because earlier application
startup called `create_all()`.

For a **new empty database**:

~~~powershell
uv run alembic upgrade head
~~~

For an **existing Phase 5 development database whose schema already matches the initial
revision**, adopt the migration history once:

~~~powershell
uv run alembic stamp head
~~~

Stamping changes only Alembic version metadata. It does not create or alter product tables.

Do not stamp an unknown or partially upgraded database.

### Runtime policy

After Step 1, FastAPI no longer creates product tables lazily.

The deployment/startup sequence is:

~~~text
database reachable
        ↓
alembic upgrade head
        ↓
start FastAPI
~~~

Unit tests may continue to use `PersistenceBase.metadata.create_all()` through the existing
test helper because isolated ephemeral schemas are not deployment environments.

### Step 1 implementation status

**IMPLEMENTED pending local migration gate**

Added:

~~~text
alembic.ini
migrations/env.py
migrations/script.py.mako
migrations/versions/20260921_0001_product_persistence.py
tests/test_migrations.py
~~~

The initial revision creates the seven current product tables, indexes, foreign keys, and
the evaluation case unique constraint.

FastAPI `get_persistence_engine()` no longer calls `metadata.create_all()`.

Migration test coverage performs:

~~~text
empty SQLite database
    ↓
alembic upgrade head
    ↓
inspect expected product tables
    ↓
Alembic autogenerate compare against ORM metadata
    ↓
expect zero schema drift
    ↓
alembic downgrade base
    ↓
verify product tables removed
    ↓
alembic upgrade head again
~~~

Focused gate:

~~~powershell
uv sync --all-groups
uv run ruff check .
uv run pytest -v tests/test_migrations.py tests/test_persistence_store.py tests/test_agent_configuration_persistence.py tests/test_agent_run_telemetry.py tests/test_evaluation_persistence.py
~~~

With local PostgreSQL running, a clean-database smoke is:

~~~powershell
uv run alembic current
uv run alembic upgrade head
uv run alembic current
~~~

For a pre-Phase-6 local database that already contains the complete current product schema,
use the one-time adoption path:

~~~powershell
uv run alembic stamp head
uv run alembic current
~~~

After adoption, all future schema changes must use normal Alembic revisions and
`upgrade`/`downgrade`.

## Step 2 — Application Lifecycle and Database Engine Hardening

Move process resources into explicit FastAPI lifespan ownership.

Targets:

- one application database engine lifecycle;
- connection-pool configuration;
- startup database/schema readiness checks;
- graceful engine disposal;
- explicit startup failure when migrations are missing;
- deterministic shutdown behavior.

### Step 2 implementation status

**IMPLEMENTED pending local gate**

Database runtime ownership is now explicit.

### Engine configuration

The application database engine now uses:

~~~text
pool_pre_ping = true
pool_size = DATABASE_POOL_SIZE
max_overflow = DATABASE_MAX_OVERFLOW
pool_timeout = DATABASE_POOL_TIMEOUT_SECONDS
pool_recycle = DATABASE_POOL_RECYCLE_SECONDS
~~~

for non-SQLite databases.

SQLite keeps its native pool behavior so isolated unit tests remain lightweight.

Defaults:

~~~text
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT_SECONDS=30
DATABASE_POOL_RECYCLE_SECONDS=1800
DATABASE_MIGRATION_CONFIG=alembic.ini
~~~

Pool configuration is validated by Pydantic.

### FastAPI lifespan ownership

API startup now:

~~~text
create/get application engine
        ↓
SELECT 1
        ↓
read current Alembic revisions
        ↓
compare with migration heads
        ↓
refuse startup if schema is outdated
        ↓
serve traffic
~~~

Shutdown:

~~~text
clear coordinator/agent caches
        ↓
dispose SQLAlchemy engine
        ↓
clear engine cache
~~~

The API no longer waits for the first product request to discover a missing migration.

### Health contract

~~~text
GET /health
~~~

remains pure liveness and has no database dependency.

~~~text
GET /health/db
~~~

checks connectivity using the application engine and does not expose raw SQLAlchemy/database
exception details.

~~~text
GET /health/ready
~~~

checks both connectivity and migration state.

Ready response:

~~~json
{
  "status": "ok",
  "database": "reachable",
  "schema": "current",
  "current_revisions": ["20260921_0001"],
  "head_revisions": ["20260921_0001"]
}
~~~

An outdated schema returns HTTP 503.

The Web smoke test now verifies this readiness endpoint.

### Step 2 coverage

Tests cover:

- PostgreSQL pool option wiring;
- SQLite pool-option compatibility;
- Alembic current-head readiness;
- outdated-schema rejection;
- readiness API current/outdated responses;
- lifespan engine disposal;
- API startup rejection when schema is outdated;
- database-health error redaction.

Focused Step 1 + Step 2 gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_migrations.py tests/test_database_runtime.py tests/test_persistence_store.py tests/test_agent_configuration_persistence.py tests/test_agent_run_telemetry.py tests/test_evaluation_persistence.py
~~~

Live local check after the existing database was stamped to head:

~~~powershell
uv run alembic current
uv run uvicorn docker_agent.main:app --reload
~~~

Then:

~~~text
GET /health
GET /health/db
GET /health/ready
~~~

should all return HTTP 200.

## Step 3 — Production Containers

Add reproducible backend and frontend images:

~~~text
Dockerfile.backend
Dockerfile.web
~~~

and production-oriented Compose wiring.

Requirements:

- non-development commands;
- health checks;
- dependency ordering;
- persistent PostgreSQL volume;
- migration job/entrypoint;
- no source-code bind mount requirement;
- frontend SPA fallback;
- API proxying.

## Step 4 — Environment Separation

Define explicit configuration profiles/contracts for:

~~~text
development
test
production
~~~

Production must reject obviously unsafe defaults where appropriate, including default
database credentials when policy requires it.

Document required secrets and environment variables without checking secrets into Git.

## Step 5 — CI

Add GitHub Actions gates for:

~~~text
backend lint
backend tests
migration checks
frontend typecheck
frontend tests
frontend production build
~~~

Cache Python/uv and Node dependencies where useful.

## Step 6 — Evaluation Regression Gate in CI

Connect the Phase 5 comparison contract to release validation.

The CI/release workflow should support:

~~~text
persist candidate evaluation
        ↓
compare to selected baseline
        ↓
exit 0 / 1 / 2
        ↓
release gate
~~~

Live-model evaluation remains an explicit protected/release workflow rather than running on
every small pull request.

## Step 7 — Deployment and Monitoring Closeout

Finish:

- production Compose/deployment documentation;
- migration/runbook procedures;
- rollback guidance;
- health/readiness semantics;
- Prometheus scrape example;
- backup/restore considerations;
- final production smoke procedure.

## Phase 6 Completion Criteria

Phase 6 is complete when:

- a clean database can migrate from zero to head;
- migration downgrade/upgrade is testable;
- FastAPI no longer silently creates deployment tables;
- backend/web production images build;
- CI runs deterministic quality gates;
- deployment startup applies migrations before serving traffic;
- monitoring/health endpoints remain reachable;
- production runbook documents upgrade and rollback behavior.
