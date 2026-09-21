# Upgrade Phase 6 Closeout

## Status

**Phase 6 — Production / Deployment Hardening: COMPLETE pending final production validation**

## Delivered

Phase 6 turns the project into a deployable, migration-aware, CI-gated service.

### Database and lifecycle

- Alembic versioned migrations;
- migration round-trip and ORM drift tests;
- no FastAPI-side deployment `create_all()`;
- bounded SQLAlchemy pool configuration;
- FastAPI lifespan ownership;
- startup rejection when schema is not at Alembic head;
- graceful engine disposal;
- liveness, database health, and readiness separation.

### Containers

- production backend image;
- production Vue/Nginx image;
- production Compose stack;
- PostgreSQL health ordering;
- one-shot migration job;
- idempotent RAG schema bootstrap;
- non-root backend runtime;
- persistent model cache;
- no Docker socket in the safe default deployment.

### Environment contracts

~~~text
development -> .env
test        -> .env.test
production  -> .env.production
~~~

Production validates:

- PostgreSQL-only serving database;
- non-default database password;
- no unresolved placeholders;
- model runtime identity;
- explicit opt-in before local Docker tools.

### CI

Normal push/PR CI validates:

- Ruff;
- migration/runtime contract;
- backend tests;
- frontend typecheck/tests/build;
- production Compose;
- monitoring Compose profile.

The live evaluation regression workflow remains manual and protected from ordinary PR usage.

### Evaluation release gate

The explicit GitHub Actions workflow can:

- run/persist a live candidate evaluation;
- compare against a persisted baseline;
- propagate the Phase 5 regression-gate exit code;
- expose machine-readable comparison JSON.

### Monitoring

Optional Compose profile:

~~~text
monitoring
~~~

adds Prometheus.

Scrape path:

~~~text
backend:8000/metrics
~~~

inside the private Compose network.

Public Nginx returns 404 for `/metrics` by default.

### Production runbook

~~~text
doc/Production_Runbook.md
~~~

documents:

- preflight;
- build;
- first deployment;
- health/readiness;
- final smoke;
- monitoring;
- backup;
- restore;
- upgrade;
- rollback;
- knowledge indexing boundaries;
- incident checks;
- shutdown/data retention.

## Final Gate

Backend:

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

Compose:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring config
~~~

Production build:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml build
~~~

Production startup:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

Public read-only smoke:

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
$env:SMOKE_CHECK_METRICS="false"
npm run smoke
Remove-Item Env:SMOKE_CHECK_METRICS
Remove-Item Env:BACKEND_URL
cd ..
~~~

Internal metrics check:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').status)"
~~~

Expected:

~~~text
200
~~~

## Deliberately Deferred

Phase 6 does not attempt to finish:

- Kubernetes;
- managed cloud deployment;
- public TLS/domain provisioning;
- centralized log shipping;
- alert routing/on-call paging;
- OpenTelemetry distributed tracing;
- automatic database backup scheduling;
- image registry publishing/release automation;
- privileged host-Docker production mode.

Those are deployment-platform concerns rather than requirements for the current production
hardening milestone.

## Recommended Next Phase

Phase 7 should move back to product architecture:

**Generic Multi-Agent Platform**

Primary goals:

- Agent registry/factory;
- multiple real Agent types;
- per-Agent toolsets;
- per-Agent knowledge sources;
- graph factory / Supervisor reuse;
- Agent selector in Web;
- generic configuration schema;
- platform-level Operations support across Agent types.
