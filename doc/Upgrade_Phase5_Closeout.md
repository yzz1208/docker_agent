# Upgrade Phase 5 Closeout

## Status

**Phase 5 — Observability & Evaluation Ops: COMPLETE**

Phase 5 adds the operational and quality-control layer around the Docker Support Agent.

## Runtime Observability

Every attempted Agent turn can now produce a durable run record with:

~~~text
run id
conversation id
status
route
workers
duration
safe error metadata
timestamps
~~~

FastAPI requests and Agent execution also share:

~~~text
request_id
run_id
conversation_id
~~~

through structured logging correlation.

Prometheus-compatible runtime metrics are available from:

~~~text
GET /metrics
~~~

without using high-cardinality request/run/conversation identifiers as labels.

## Operations APIs

Runtime operations:

~~~text
GET /operations/runs
GET /operations/runs/{run_id}
GET /operations/summary
~~~

Evaluation operations:

~~~text
GET /operations/evaluations
GET /operations/evaluations/{evaluation_run_id}
GET /operations/evaluations/compare
~~~

## Evaluation Persistence

Evaluation Runs capture:

~~~text
suite
dataset SHA-256
git revision
safe configuration snapshot
aggregate metrics
per-case results
status/timestamps
~~~

Router and Workflow evaluation scripts support optional:

~~~text
--persist
~~~

while retaining their original non-persistent workflows.

## Regression Gate

Persisted baseline and candidate runs can be compared by stable case key.

The gate detects:

~~~text
new failures
new passes
metric regressions
incomplete case sets
route/tool behavior changes
configuration changes
~~~

CLI:

~~~powershell
uv run python scripts/compare_evaluations.py --baseline <BASELINE> --candidate <CANDIDATE>
~~~

Exit semantics:

~~~text
0 pass
1 regression/incomplete
2 invalid comparison
~~~

## Web Operations Surface

The Vue shell now has:

~~~text
/operations
~~~

with:

~~~text
Overview
├─ success/failure
├─ P50/P95
├─ routes
├─ workers
└─ errors

Runs
├─ recent runs
└─ run detail

Evaluations
├─ evaluation history
├─ evaluation cases
└─ baseline vs candidate comparison
~~~

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
~~~

Integration:

~~~powershell
npm run smoke
~~~

## Deliberately Deferred

Phase 5 does not attempt to finish:

- final UI visual polish;
- hosted monitoring deployment;
- alerting/paging;
- distributed OpenTelemetry tracing;
- cost accounting;
- multi-user analytics;
- automatic live-model evaluation on every commit.

Those can be layered on after the production/deployment phase establishes CI and release
infrastructure.

## Next Phase

Phase 6 should focus on Production / Deployment Hardening:

- database migrations;
- production Docker images;
- environment separation;
- CI/CD;
- regression gate integration;
- deployment topology;
- lifecycle and graceful shutdown;
- production health/monitoring wiring.
