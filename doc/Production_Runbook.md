# Production Deployment Runbook

## Purpose

This runbook is the operational contract for deploying, upgrading, monitoring, backing up,
restoring, and rolling back the Docker Support Agent production Compose stack.

The default stack is intentionally conservative:

~~~text
PostgreSQL
  ↓
Alembic migration
  ↓
RAG schema bootstrap
  ↓
FastAPI readiness
  ↓
Nginx + Vue
~~~

Optional monitoring adds Prometheus on the same Compose network.

## 1. Prepare Production Configuration

Create the private environment file:

~~~powershell
Copy-Item .env.production.example .env.production
~~~

Replace all placeholders and use a strong database password.

At minimum configure:

~~~text
POSTGRES_PASSWORD
DATABASE_URL
MODEL_NAME
MODEL_BASE_URL
MODEL_API_KEY   # when required by the provider
~~~

The default production deployment keeps:

~~~text
TOOL_MODE=mock
ALLOW_LOCAL_DOCKER_TOOLS=false
~~~

The standard production stack must not mount the Docker socket.

## 2. Preflight

Validate application configuration:

~~~powershell
$env:APP_ENV="production"
uv run python scripts/production_preflight.py
Remove-Item Env:APP_ENV
~~~

Validate Compose interpolation and topology:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml config
~~~

Validate source quality before deployment:

~~~powershell
uv run ruff check .
uv run pytest -v
cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

## 3. Build

Build the production images:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml build
~~~

Use a meaningful immutable image tag for a release:

~~~powershell
$env:IMAGE_TAG="2026-09-21.1"
docker compose --env-file .env.production -f compose.prod.yaml build
~~~

Record the Git revision and image tag in the release notes.

## 4. First Deployment

Start the stack:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

Expected lifecycle:

~~~text
postgres     healthy
migrate      exited 0
rag-schema   exited 0
backend      healthy
web          healthy
~~~

The public application is:

~~~text
http://127.0.0.1:8080
~~~

or the configured `WEB_PORT`.

## 5. Health and Readiness

Public liveness:

~~~text
GET /health
~~~

Database connectivity:

~~~text
GET /health/db
~~~

Deployment readiness:

~~~text
GET /health/ready
~~~

A deploy is not healthy until readiness reports:

~~~json
{
  "status": "ok",
  "database": "reachable",
  "schema": "current"
}
~~~

An outdated Alembic revision must keep the backend unready.

## 6. Final Production Smoke

Run the read-only application smoke through Nginx:

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
$env:SMOKE_CHECK_METRICS="false"
npm run smoke
Remove-Item Env:SMOKE_CHECK_METRICS
Remove-Item Env:BACKEND_URL
cd ..
~~~

The public Nginx endpoint deliberately does not expose `/metrics`.

Verify internal metrics separately:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').status)"
~~~

Expected status:

~~~text
200
~~~

Optional chat smoke may consume model resources:

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
$env:SMOKE_CHECK_METRICS="false"
$env:SMOKE_CHAT_MESSAGE="What does a Docker volume do?"
npm run smoke
Remove-Item Env:SMOKE_CHAT_MESSAGE
Remove-Item Env:SMOKE_CHECK_METRICS
Remove-Item Env:BACKEND_URL
cd ..
~~~

The smoke script deletes the temporary conversation it creates.

## 7. Prometheus Monitoring

Prometheus is an opt-in Compose profile.

Start it with the application:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring up -d
~~~

Default UI:

~~~text
http://127.0.0.1:9090
~~~

Override with:

~~~text
PROMETHEUS_PORT
~~~

Prometheus scrapes internally:

~~~text
backend:8000/metrics
~~~

The scrape endpoint is therefore available to the monitoring network without being proxied
through public Nginx.

Current application metric families include:

~~~text
docker_agent_http_requests_total
docker_agent_runs_total
docker_agent_run_failures_total
docker_agent_run_routes_total
docker_agent_worker_executions_total
docker_agent_run_duration_seconds
~~~

For an Internet-facing deployment, place authentication/network controls in front of the
Prometheus UI rather than exposing port 9090 publicly.

## 8. Database Backup

Back up before every schema-changing deployment.

Create a directory:

~~~powershell
New-Item -ItemType Directory -Force backups
~~~

Create a custom-format dump inside PostgreSQL and copy it out:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/docker_agent.dump'
docker compose --env-file .env.production -f compose.prod.yaml cp postgres:/tmp/docker_agent.dump ./backups/docker_agent.dump
~~~

Validate that the backup file exists and is non-empty before upgrading.

A PostgreSQL logical backup covers both product tables and persisted `document_chunks`.

Model-cache volumes are reproducible caches and do not require backup.

## 9. Database Restore

Restoration is a destructive operational action. Stop application writers first:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml stop web backend
~~~

Copy the dump into PostgreSQL:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml cp ./backups/docker_agent.dump postgres:/tmp/docker_agent.dump
~~~

Restore:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml exec -T postgres sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/docker_agent.dump'
~~~

Re-apply the migration head expected by the checked-out application revision:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic upgrade head
~~~

Restart and verify readiness:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

Then run the final production smoke again.

## 10. Upgrade Procedure

Before deploying a new release:

1. confirm CI is green;
2. run the Evaluation Regression Gate when required for the release;
3. back up PostgreSQL;
4. record current Git revision and image tag;
5. review new Alembic revisions and their downgrade functions;
6. build the new image tag.

Apply the release:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml build
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

Compose guarantees migration completion before backend readiness.

Run the final smoke before declaring the release complete.

## 11. Rollback Procedure

Application-only rollback is appropriate only when the previous application version remains
compatible with the current database schema.

Switch back to the previous code/image tag and redeploy.

For a schema rollback, first inspect migration state:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic current
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic history
~~~

Only run a downgrade when the target revision's downgrade is explicitly known to be safe:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic downgrade -1
~~~

Do not assume every future migration is lossless.

If a migration is destructive or downgrade cannot safely restore data, use the pre-deploy
PostgreSQL backup instead of forcing an Alembic downgrade.

After rollback, verify:

~~~text
/health
/health/db
/health/ready
production smoke
~~~

## 12. Knowledge-Base Operations

Production startup creates the RAG schema but does not automatically rebuild embeddings.

A fresh database therefore requires an explicit indexing workflow before Docs RAG is fully
populated.

Do not use `--reset` during ordinary service restart or deployment.

Treat corpus replacement/re-indexing as a separate data operation with its own validation
and rollback plan.

## 13. Incident Checklist

If the Web UI is unavailable:

1. check `docker compose ... ps`;
2. inspect Web and backend logs;
3. check `/health`;
4. check `/health/ready`;
5. confirm migration and RAG bootstrap jobs exited 0.

If readiness fails with an outdated schema:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic current
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic upgrade head
~~~

If PostgreSQL is unavailable, fix database availability before restarting backend loops.

If model calls fail while readiness is healthy, inspect structured Agent logs and the
Operations dashboard rather than treating the process as unhealthy.

## 14. Shutdown and Data Retention

Stop services while retaining persistent data:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml down
~~~

With monitoring:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring down
~~~

Do not use `down -v` during normal operations.

This command deletes PostgreSQL, model-cache, and Prometheus volumes:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml --profile monitoring down -v
~~~

Use it only for an intentional full reset.
