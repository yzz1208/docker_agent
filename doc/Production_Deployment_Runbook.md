# Production Deployment Runbook

## 1. Prepare production configuration

Create the private environment file:

~~~powershell
Copy-Item .env.production.example .env.production
~~~

Replace all placeholders, especially:

~~~text
POSTGRES_PASSWORD
DATABASE_URL
MODEL_NAME
MODEL_BASE_URL
MODEL_API_KEY  # when required
~~~

Keep the default production tool boundary unless a separate privileged deployment is reviewed:

~~~text
TOOL_MODE=mock
ALLOW_LOCAL_DOCKER_TOOLS=false
~~~

The real .env.production is ignored by Git.

## 2. Run the secret-safe preflight

~~~powershell
uv run python scripts/production_preflight.py
~~~

The command validates the production Settings contract and prints only safe metadata.
It never prints database passwords, API-key values, or the complete database URL.

## 3. Validate and build

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml build
~~~

Use IMAGE_TAG for a meaningful release or commit identifier.

## 4. Backup before schema/application upgrades

Create a host backup directory:

~~~powershell
New-Item -ItemType Directory -Force backups
~~~

Start PostgreSQL if needed:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml up -d postgres
~~~

Create a logical SQL backup inside the container:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl -f /tmp/docker_agent_backup.sql'
~~~

Copy it to the host:

~~~powershell
$postgres = docker compose --env-file .env.production -f compose.prod.yaml ps -q postgres
docker cp "$($postgres):/tmp/docker_agent_backup.sql" ".\backups\docker_agent_backup.sql"
~~~

Verify the file exists and is non-empty before continuing.

## 5. Start or upgrade

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
~~~

Expected lifecycle:

~~~text
postgres      healthy
migrate       exited 0
rag-schema    exited 0
backend       healthy
web           healthy
~~~

The backend refuses readiness when the database is not at Alembic head.

## 6. Production smoke

Read-only API smoke through Nginx:

~~~powershell
cd web
$env:BACKEND_URL="http://127.0.0.1:8080"
npm run smoke
Remove-Item Env:BACKEND_URL
~~~

SPA + ingress smoke:

~~~powershell
$env:APP_URL="http://127.0.0.1:8080"
npm run smoke:production
Remove-Item Env:APP_URL
cd ..
~~~

The production smoke checks /, /operations, /settings, /health/ready, and /metrics.

## 7. Knowledge provisioning

Service startup creates the pgvector/document_chunks schema but does not embed documents.
Provision knowledge explicitly:

~~~powershell
uv run python scripts/download_docs.py
uv run python scripts/select_docs.py
uv run python scripts/build_docs.py
uv run python scripts/audit_chunks.py
uv run python scripts/index_chunks.py --reset --batch-size 4
~~~

Treat --reset as a deliberate replacement of indexed chunks, never as normal startup.

## 8. Prometheus

A scrape example is provided at:

~~~text
deploy/prometheus.yml
~~~

Inside the production Docker network it scrapes:

~~~text
backend:8000/metrics
~~~

Metrics are process-local. Durable Agent-run and evaluation history remains in PostgreSQL.

## 9. Application rollback

Prefer rolling back application code/images without downgrading the database when the older
application is compatible with the current schema.

Recommended sequence:

1. stop or drain application traffic;
2. deploy/rebuild the known-good application revision;
3. keep the database at its current revision when compatible;
4. verify /health/ready;
5. run production smoke.

Do not blindly run alembic downgrade -1.

## 10. Database migration rollback

Before any downgrade:

1. verify a backup exists;
2. inspect the target migration downgrade() implementation;
3. stop application writes;
4. verify the old application expects the target schema.

Run only an explicitly reviewed target:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml run --rm migrate alembic downgrade <target_revision>
~~~

If downgrade safety is unclear, restore from backup instead.

## 11. Restore from logical backup

Stop application services:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml stop web backend
~~~

Copy a reviewed backup into PostgreSQL:

~~~powershell
$postgres = docker compose --env-file .env.production -f compose.prod.yaml ps -q postgres
docker cp ".\backups\docker_agent_backup.sql" "$($postgres):/tmp/docker_agent_restore.sql"
~~~

After preparing/cleaning the intended target database according to your PostgreSQL policy:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/docker_agent_restore.sql'
~~~

After restore, inspect alembic_version, deploy the compatible app revision, and rerun readiness/smoke.

## 12. Release evaluation gate

Normal CI is deterministic and does not call a model.
For release-quality evaluation, manually run GitHub Actions -> Evaluation Regression Gate.

Required GitHub configuration:

~~~text
Variable:
EVALUATION_MODEL_NAME

Secrets:
EVALUATION_DATABASE_URL
EVALUATION_MODEL_BASE_URL
EVALUATION_MODEL_API_KEY
~~~

The Evaluation DB must be reachable from the runner and already at Alembic head.

## 13. Incident diagnostics

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml ps
docker compose --env-file .env.production -f compose.prod.yaml logs --tail 200 migrate
docker compose --env-file .env.production -f compose.prod.yaml logs --tail 200 rag-schema
docker compose --env-file .env.production -f compose.prod.yaml logs --tail 200 backend
docker compose --env-file .env.production -f compose.prod.yaml logs --tail 200 web
docker compose --env-file .env.production -f compose.prod.yaml logs --tail 200 postgres
~~~

For Backend startup problems, check migration -> RAG schema -> database readiness in that order.

## 14. Safe shutdown

Preserve data:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml down
~~~

Destructive reset only when data is intentionally disposable/backed up:

~~~powershell
docker compose --env-file .env.production -f compose.prod.yaml down -v
~~~

Never use down -v against important unbacked data.
