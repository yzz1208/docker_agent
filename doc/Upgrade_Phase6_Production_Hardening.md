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

## Step 2 — Application Lifecycle and Database Engine Hardening

Move process resources into explicit FastAPI lifespan ownership.

Targets:

- one application database engine lifecycle;
- connection-pool configuration;
- startup database/schema readiness checks;
- graceful engine disposal;
- explicit startup failure when migrations are missing;
- deterministic shutdown behavior.

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
