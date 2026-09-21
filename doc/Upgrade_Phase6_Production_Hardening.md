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

### Step 3 implementation status

**IMPLEMENTED pending local Docker build/smoke gate**

Production-oriented container files are now available:

~~~text
docker/Dockerfile.backend
docker/Dockerfile.web
docker/nginx/default.conf
compose.prod.yaml
.dockerignore
~~~

### Backend image

The backend image uses:

~~~text
python:3.12-slim
uv project sync
non-root app user
/app/.venv
/app/.cache/huggingface
~~~

The image contains application code plus Alembic migrations and runs:

~~~text
uvicorn docker_agent.main:app --host 0.0.0.0 --port 8000 --no-access-log
~~~

Uvicorn access logging is disabled because Phase 5 already emits structured request logs.

### Web image

The Web image is multi-stage:

~~~text
node:22-alpine
    ↓
npm install
npm run build
    ↓
nginx:1.27-alpine
~~~

Nginx serves the built Vue SPA and proxies same-origin API traffic to the backend.

Important routing rule:

~~~text
/operations
    = Vue SPA page

/operations/summary
/operations/runs...
/operations/evaluations...
    = FastAPI APIs
~~~

This preserves the Phase 5 fix that prevents the `/operations` page from being swallowed
by the API proxy.

### Production Compose topology

~~~text
postgres
   ↓ health
migrate
   ↓ completed successfully
rag-schema
   ↓ completed successfully
backend
   ↓ /health/ready
web/nginx
   ↓ public :8080
user/browser
~~~

Services:

~~~text
postgres
    pgvector/pgvector:pg16
    persistent named volume

migrate
    same backend image
    alembic upgrade head
    one-shot job

rag-schema
    idempotently creates pgvector/document_chunks schema
    never clears or re-indexes chunks

backend
    waits for RAG schema bootstrap
    no host port by default
    readiness healthcheck

web
    only public service port
    waits for healthy backend
~~~

The default public URL is:

~~~text
http://127.0.0.1:8080
~~~

Override with:

~~~text
WEB_PORT
~~~

### Docker host security

The production template intentionally does **not** mount:

~~~text
/var/run/docker.sock
~~~

and therefore defaults to:

~~~text
TOOL_MODE=mock
~~~

Real host-Docker control is a privileged deployment choice and will not be enabled
implicitly by the production template.

### Model cache

A persistent named volume is mounted at:

~~~text
/app/.cache/huggingface
~~~

and both embedding/reranker cache paths are overridden to this Linux-safe location.

This avoids accidentally propagating development Windows paths into the container.

### RAG schema vs knowledge indexing

The production startup chain guarantees that the pgvector extension and
`document_chunks` table exist before FastAPI starts.

It does **not** automatically run:

~~~text
index_chunks.py --reset
~~~

or download/re-embed the Docker documentation corpus.

This separation is intentional:

~~~text
service startup
    = schema readiness

knowledge provisioning
    = explicit indexing workflow
~~~

Existing indexed chunks are preserved. A fresh production database starts with an empty
knowledge table until the indexing workflow is run deliberately.

### Container topology tests

Static tests verify:

- migration service waits for healthy PostgreSQL;
- backend waits for migration completion;
- web waits for backend readiness;
- only the Web service publishes a host port;
- Docker socket is not mounted;
- Nginx preserves the `/operations` SPA route;
- Operations APIs are proxied;
- backend runs as non-root;
- web image is multi-stage;
- Docker build context excludes secrets/generated directories.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_production_containers.py tests/test_database_runtime.py tests/test_migrations.py
~~~

### Production-stack build and smoke

Build:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml build
~~~

Start:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

The migration service should exit successfully after applying Alembic head. Backend and Web
should become healthy.

Run the existing read-only smoke **through Nginx**:

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
npm run smoke
Remove-Item Env:BACKEND_URL
~~~

This verifies the complete path:

~~~text
browser-like client
    ↓
Nginx
    ↓
FastAPI
    ↓
PostgreSQL
~~~

The Vue SPA is available at:

~~~text
http://127.0.0.1:8080/
http://127.0.0.1:8080/operations
http://127.0.0.1:8080/settings
~~~

Stop the stack without deleting data:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml down
~~~

Delete the production Compose database/cache volumes only when intentionally resetting:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml down -v
~~~

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

### Step 4 implementation status

**IMPLEMENTED pending local gate**

Configuration is now explicitly separated into:

~~~text
development
    APP_ENV=development
    dotenv=.env

test
    APP_ENV=test
    dotenv=.env.test

production
    APP_ENV=production
    dotenv=.env.production
~~~

`get_settings()` selects the dotenv file from `APP_ENV`. Direct `Settings(...)`
construction remains deterministic for tests and utility code and does not implicitly load
the development dotenv file.

Templates:

~~~text
.env.example
.env.test.example
.env.production.example
~~~

Private runtime files:

~~~text
.env
.env.test
.env.production
~~~

are ignored by Git.

### Production database contract

Production settings reject:

- non-PostgreSQL `DATABASE_URL`;
- the old `postgres:postgres` default;
- empty/known weak database passwords;
- unreplaced database URL placeholders.

This validation is global because migration, RAG schema bootstrap, and the API all require
a safe production database configuration.

### Serving-runtime contract

Model configuration is validated separately when FastAPI enters its lifespan.

Production serving requires:

~~~text
MODEL_NAME
MODEL_BASE_URL
~~~

and rejects unreplaced placeholders in:

~~~text
MODEL_NAME
MODEL_BASE_URL
MODEL_API_KEY
~~~

The split is intentional:

~~~text
migrate / rag-schema
    need safe database config
    do not need an active model

backend serving
    needs safe database config
    + valid model runtime config
~~~

This allows schema migration to run independently during deployment while still making a
misconfigured API fail before accepting traffic.

### Tool-mode contract

`TOOL_MODE` is now implemented rather than being a documentation-only setting.

~~~text
TOOL_MODE=mock
    deterministic in-process Docker diagnostic results
    no subprocess
    no Docker daemon access

TOOL_MODE=local
    existing allowlisted read-only Docker CLI
~~~

Production `TOOL_MODE=local` additionally requires:

~~~text
ALLOW_LOCAL_DOCKER_TOOLS=true
~~~

The default production Compose file is stricter and forcibly sets:

~~~text
TOOL_MODE=mock
ALLOW_LOCAL_DOCKER_TOOLS=false
~~~

It still does not mount the Docker socket. A future privileged Docker-diagnostics deployment
must use a separate explicit profile instead of weakening the safe default stack.

### Production dotenv workflow

Create the private file once:

~~~powershell
Copy-Item .env.production.example .env.production
~~~

Before starting containers, replace at minimum:

~~~text
POSTGRES_PASSWORD
DATABASE_URL
MODEL_NAME
MODEL_BASE_URL
MODEL_API_KEY   # when the selected provider requires one
~~~

`POSTGRES_PASSWORD` is required by Compose. `DATABASE_URL` is read directly by backend
services from `.env.production` instead of being assembled by Compose, so URL-encoded
database credentials remain valid.

Validate interpolation/configuration:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml config
~~~

Then use the same env-file flag for build/up/ps/down commands.

### Step 4 coverage

Tests cover:

- explicit environment-to-dotenv mapping;
- actual `.env.test` selection by `get_settings()`;
- invalid environment rejection;
- log-level normalization;
- safe production configuration acceptance;
- default/weak production database rejection;
- SQLite production rejection;
- production runtime model requirements;
- runtime placeholder rejection;
- explicit local-Docker production opt-in;
- real `mock` vs `local` tool-mode behavior;
- production Compose use of `.env.production`;
- required production database password;
- fixed safe production Compose tool mode;
- environment secret files excluded from Git.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_environment_config.py tests/test_docker_tools.py tests/test_database_runtime.py tests/test_production_containers.py
~~~

Production configuration gate:

~~~powershell
Copy-Item .env.production.example .env.production
# edit .env.production
docker compose --env-file .env.production -f compose.prod.yaml config
~~~

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

### Step 5 implementation status

**IMPLEMENTED pending GitHub Actions gate**

Added:

~~~text
.github/workflows/ci.yml
tests/test_ci_workflows.py
~~~

### CI trigger and permissions

The deterministic CI workflow runs on:

~~~text
push
pull_request
~~~

It deliberately does **not** use:

~~~text
pull_request_target
~~~

and grants only:

~~~yaml
permissions:
  contents: read
~~~

Concurrent runs on the same ref cancel older in-progress runs.

### Backend quality job

Ubuntu + Python 3.12:

~~~text
uv sync --all-groups
uv run ruff check .
~~~

Database/migration contract is visible as its own step:

~~~text
tests/test_migrations.py
tests/test_database_runtime.py
~~~

The remaining backend suite then runs with those two files excluded to avoid duplicate
execution.

The job sets:

~~~text
APP_ENV=test
~~~

so CI never accidentally loads a developer `.env`.

### PyTorch platform policy

Torch sources now match the actual deployment environments:

~~~text
Windows
    pytorch-cu130

Linux / GitHub Actions / production container
    pytorch-cpu
~~~

This prevents CI and the default CPU production image from pulling the CUDA 13 runtime
unnecessarily.

The project also constrains uv to:

~~~text
>=0.8,<1.0
~~~

to prevent an unexpected future major-version change from silently altering CI behavior.

### Frontend quality job

Node 22 is used consistently across:

~~~text
web/package.json engines
GitHub Actions
docker/Dockerfile.web
~~~

The job runs:

~~~text
npm install
npm run typecheck
npm test
npm run build
~~~

### Production configuration job

CI creates a temporary non-secret validation file from:

~~~text
.env.production.example
~~~

and runs:

~~~text
docker compose --env-file .env.production -f compose.prod.yaml config
~~~

This validates Compose interpolation/topology without starting services or requiring model
credentials.

### Live-model boundary

Ordinary push/PR CI intentionally does not:

- call a paid/external model;
- persist a live candidate evaluation;
- require production model secrets;
- require access to a long-lived evaluation database.

Those actions belong to Step 6 as an explicit protected/manual release-quality workflow.

### Dependency lockfiles

The repository currently does not commit:

~~~text
uv.lock
web/package-lock.json
~~~

so deterministic CI currently relies on bounded dependency ranges plus fixed runtime majors.

Committing both lockfiles remains recommended before the final Phase 6 closeout. They should
be generated by a normal networked development environment rather than fabricated.

### Step 5 coverage

Static workflow tests verify:

- safe events and read-only permissions;
- Backend Ruff/migration/pytest commands;
- Frontend typecheck/test/build commands;
- production Compose validation;
- Linux CPU vs Windows CUDA PyTorch source policy;
- uv and Node runtime version contracts.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_environment_config.py tests/test_docker_tools.py tests/test_production_containers.py tests/test_ci_workflows.py tests/test_database_runtime.py
~~~

Frontend gate:

~~~powershell
cd web
npm run typecheck
npm test
npm run build
~~~

After pushing the branch, the GitHub `CI` workflow should show three jobs:

~~~text
Backend quality
Frontend quality
Production configuration
~~~

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

### Step 6 implementation status

**IMPLEMENTED pending manual workflow gate**

Added:

~~~text
.github/workflows/evaluation-gate.yml
~~~

and extended:

~~~text
scripts/eval_agent_router.py
scripts/eval_agent_workflow.py
scripts/compare_evaluations.py
~~~

### Manual release-quality workflow

The workflow is intentionally:

~~~text
workflow_dispatch only
~~~

It never runs automatically on a normal push or pull request.

Inputs:

~~~text
suite
    agent_router | agent_workflow

baseline_run_id
    required persisted baseline

max_regression
    default 0.02

limit
    optional positive case limit

repeats
    router repeat count, default 1

judge
    optional LLM judge for agent_workflow
~~~

### Required GitHub configuration

Repository/environment secret:

~~~text
EVALUATION_DATABASE_URL
~~~

must point to the long-lived evaluation PostgreSQL database.

Model configuration:

~~~text
EVALUATION_MODEL_NAME       # repository variable
EVALUATION_MODEL_BASE_URL   # secret
EVALUATION_MODEL_API_KEY    # secret when provider requires it
~~~

The evaluation database must:

- be reachable from the selected GitHub runner;
- already be migrated to Alembic head;
- contain the requested baseline run.

If the database is private-network only, use a self-hosted runner or another runner with
network access instead of exposing PostgreSQL publicly.

### Candidate workflow

The release gate performs:

~~~text
manual dispatch
    ↓
validate limit / repeats / threshold / baseline id
    ↓
run selected live evaluation suite
    ↓
--persist
    ↓
write reports/evaluation-summary.json
    ↓
read candidate evaluation_run_id
    ↓
compare baseline vs candidate
    ↓
write reports/evaluation-comparison.json
    ↓
copy comparison JSON into GitHub Step Summary
    ↓
preserve comparison exit code
~~~

Router evaluations include:

~~~text
--repeats <input>
~~~

so the candidate case shape can match a repeated baseline.

If limit/repeat/dataset shape does not match the baseline, the existing Phase 5 comparison
logic rejects or marks the comparison incomplete rather than allowing a misleading pass.

### Persisted evaluator database policy

Persisted evaluation CLIs no longer call:

~~~text
metadata.create_all()
init_persistence_store()
~~~

They now require:

~~~text
require_database_ready(engine)
~~~

before writing an Evaluation Run.

This keeps long-lived release evaluation databases under the same Alembic-only schema policy
as the serving application.

### Machine-readable outputs

Router and Workflow evaluation scripts now accept:

~~~text
--summary-output <path>
~~~

When `--persist` is enabled, the summary contains:

~~~text
evaluation_run_id
~~~

The regression CLI now accepts:

~~~text
--output <path>
~~~

and writes the same JSON that it prints to stdout.

Its exit semantics remain:

~~~text
0 = pass
1 = regression / incomplete
2 = invalid comparison / missing run
~~~

The GitHub workflow exits with that same code, so regression directly fails the release
quality job.

### Security boundary

The workflow grants only:

~~~yaml
permissions:
  contents: read
~~~

Database/model credentials come from GitHub secrets and are not embedded in the workflow.

The Agent tool mode is forced to:

~~~text
TOOL_MODE=mock
ALLOW_LOCAL_DOCKER_TOOLS=false
~~~

so live quality evaluation cannot invoke Docker on the GitHub runner.

### Step 6 coverage

Workflow contract tests verify:

- manual-only trigger;
- read-only repository permissions;
- required baseline input;
- candidate persistence;
- Router/Workflow suite selection;
- Router repeat propagation;
- stable summary JSON extraction;
- comparison CLI invocation and JSON output;
- use of GitHub secrets/variable rather than literal credentials;
- persisted evaluators require migrated databases and never call create_all.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_ci_workflows.py tests/test_evaluation_comparison.py tests/test_evaluation_persistence.py tests/test_environment_config.py tests/test_docker_tools.py
~~~

After pushing, configure the GitHub variable/secrets above and manually run:

~~~text
Actions
  → Evaluation Regression Gate
  → Run workflow
~~~

Use a known persisted baseline run from the same suite/dataset.

## Step 7 — Deployment and Monitoring Closeout

Finish:

- production Compose/deployment documentation;
- migration/runbook procedures;
- rollback guidance;
- health/readiness semantics;
- Prometheus scrape example;
- backup/restore considerations;
- final production smoke procedure.

### Step 7 implementation status

**IMPLEMENTED pending final production gate**

Phase 6 now includes a complete production runbook:

~~~text
doc/Production_Runbook.md
~~~

covering:

- production environment preparation;
- preflight;
- image build;
- first deployment;
- liveness/readiness;
- final smoke;
- Prometheus monitoring;
- PostgreSQL backup;
- PostgreSQL restore;
- upgrade procedure;
- application/schema rollback;
- knowledge-base operational boundaries;
- incident checklist;
- safe shutdown and data retention.

### Monitoring closeout

An optional Compose profile now provides:

~~~text
prometheus
~~~

using:

~~~text
docker/prometheus/prometheus.yml
~~~

Start it with:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring up -d
~~~

Prometheus scrapes:

~~~text
backend:8000/metrics
~~~

over the private Compose network.

Public Nginx now deliberately returns 404 for:

~~~text
/metrics
~~~

so application metrics are not exposed through the user-facing Web endpoint by default.

The default Prometheus UI port is:

~~~text
9090
~~~

and can be overridden with:

~~~text
PROMETHEUS_PORT
~~~

### Final production smoke contract

Public application smoke through Nginx uses:

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
$env:SMOKE_CHECK_METRICS="false"
npm run smoke
~~~

Metrics are checked separately inside the backend network because Nginx no longer exposes
them publicly.

### Backup and restore policy

The runbook uses PostgreSQL custom-format logical backups:

~~~text
pg_dump -Fc
pg_restore --clean --if-exists --no-owner
~~~

A backup is required before schema-changing production upgrades.

The PostgreSQL backup covers:

- product persistence tables;
- evaluation history;
- pgvector/document_chunks knowledge data.

Model caches are reproducible and are not considered backup data.

### Rollback policy

Rollback decisions distinguish:

~~~text
application-only rollback
    previous app remains compatible with current schema

safe Alembic downgrade
    revision downgrade explicitly preserves required data

backup restore
    destructive/irreversible migration or unsafe downgrade
~~~

The runbook explicitly avoids assuming that every future migration can be safely downgraded.

### Step 7 coverage

Tests verify:

- required production runbook sections;
- backup/restore commands;
- migration upgrade/downgrade procedures;
- optional Prometheus profile;
- persistent Prometheus storage;
- internal backend scrape target;
- public Nginx metrics denial;
- destructive volume-reset warning.

Final Phase 6 gate:

~~~powershell
uv run ruff check .
uv run pytest -v
~~~

Frontend:

~~~powershell
cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

Production configuration:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring config
~~~

Production build/start:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml build
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

Run the final smoke from `doc/Production_Runbook.md` before declaring the release-ready
stack validated.

## Phase 6 Status

**Phase 6 — Production / Deployment Hardening: COMPLETE pending final production gate**

Phase 6 now provides:

- Alembic versioned migrations;
- schema readiness and FastAPI lifespan ownership;
- production backend/Web images;
- production Compose startup ordering;
- explicit environment profiles;
- production configuration safety checks;
- deterministic GitHub Actions quality CI;
- manual live-model evaluation regression gate;
- optional internal Prometheus monitoring;
- production deployment/backup/restore/rollback runbook.

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
