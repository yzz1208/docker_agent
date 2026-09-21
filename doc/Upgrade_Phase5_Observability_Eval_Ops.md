# Upgrade Phase 5 — Observability and Evaluation Ops

## Goal

Phase 5 turns the Docker Support Agent from a product demo into an inspectable AI
application with operational telemetry, reproducible evaluation runs, and regression
visibility.

The focus is not additional agent intelligence. The focus is answering:

~~~text
What ran?
Why did it take that path?
How long did it take?
Did it succeed or fail?
Which stage failed?
Did quality regress after a change?
~~~


## Why This Phase

The project already has:

- LangGraph orchestration;
- deterministic worker roles;
- persistent conversations/messages;
- compact execution metadata;
- configuration APIs;
- a usable web shell;
- offline retrieval/agent evaluation scripts.

What is still missing is a unified operational layer connecting runtime behavior and
evaluation results.

Phase 5 adds that layer.

## Target Architecture

~~~text
Chat / API request
       ↓
Agent Run lifecycle
       ├─ run_id
       ├─ conversation_id
       ├─ route / workers
       ├─ status
       ├─ duration
       ├─ error category
       └─ timestamps
       ↓
LangGraph Agent
       ↓
structured trace / metrics
       ↓
Operations API
       ↓
Web Operations Dashboard

Offline Eval Suites
       ↓
Evaluation Run
       ├─ dataset
       ├─ configuration snapshot
       ├─ aggregate metrics
       └─ per-case results
       ↓
Regression comparison
       ↓
Operations Dashboard
~~~


## Step 1 — Agent Run Telemetry Foundation

Introduce a durable run model independent from chat messages.

A run exists for every attempted agent turn, including failures.

Initial fields:

~~~text
id
conversation_id
agent_type
status
route
use_docs
planned_workers
completed_workers
duration_ms
error_type
error_message
started_at
completed_at
~~~


Status:

~~~text
running
succeeded
failed
~~~


The first version deliberately does not persist:

- raw model prompts;
- raw model responses;
- full Docker stdout;
- full retrieved document contexts;
- secrets.

This keeps the operational table compact and safe.

### Run lifecycle

~~~text
create run(status=running)
        ↓
invoke agent
        ↓
success ──→ finalize succeeded + route/workers/duration
        ↓
failure ──→ finalize failed + safe error category/duration
~~~


Run persistence must not hide or replace the original exception.

If telemetry persistence itself fails, the product request should still preserve the
original agent/database failure semantics whenever possible.


### Step 1 implementation status

**IMPLEMENTED pending local Ruff/pytest gate**

Current implementation adds:

~~~text
agent_runs
~~~

with durable lifecycle fields for:

~~~text
conversation_id
agent_type
status
route
use_docs
planned_workers
completed_workers
duration_ms
error_type
error_message
started_at
completed_at
~~~

`PersistentChatCoordinator` now creates a run before agent execution and finalizes it
after the persisted chat turn succeeds.

Failure behavior is deliberate:

~~~text
agent/persistence exception
        ↓
best-effort failed-run finalization
        ↓
original exception is re-raised unchanged
~~~

A successful product chat is also not converted into a failure if telemetry finalization
itself fails after messages were already persisted.

Error messages stored in telemetry are compacted and redact common API-key/token/password
patterns. Full prompts, retrieved contexts, Docker stdout, and model responses are not
stored in the run table.

Conversation deletion removes associated run telemetry.

Step 1 tests cover:

- running -> succeeded lifecycle;
- running -> failed lifecycle;
- duplicate finalization rejection;
- secret-like error redaction;
- bounded error messages;
- run listing/filtering;
- conversation-delete cleanup;
- successful clarification/runtime turns producing successful runs;
- failed Agent calls producing failed runs while preserving the original exception.

Local focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_agent_run_telemetry.py tests/test_persistent_chat.py tests/test_persistence_store.py tests/test_chat_api.py
~~~

## Step 2 — Operations Read API

Add product-facing read endpoints:

~~~text
GET /operations/runs
GET /operations/runs/{run_id}
GET /operations/summary
~~~


Summary should support an explicit recent window and report metrics such as:

~~~text
total runs
success rate
failure rate
p50 / p95 duration
route distribution
worker distribution
error-category distribution
~~~


No raw secret/runtime payloads should be exposed.


### Step 2 implementation status

**IMPLEMENTED pending local Ruff/pytest gate**

Operations read APIs are now available:

~~~text
GET /operations/runs
GET /operations/runs/{run_id}
GET /operations/summary
~~~

Run listing supports:

~~~text
conversation_id
agent_type
status
limit
offset
~~~

The run response exposes only the compact telemetry contract:

~~~text
id
conversation_id
agent_type
status
route
use_docs
planned_workers
completed_workers
duration_ms
error_type
error_message
started_at
completed_at
~~~

No prompt, raw model response, retrieved context, Docker stdout, or secret field is added to
the read API.

### Summary window and metric semantics

~~~text
GET /operations/summary?hours=24
~~~

uses a bounded recent window:

~~~text
minimum: > 0 hours
maximum: 720 hours (30 days)
default: 24 hours
~~~

Summary fields:

~~~text
total_runs
running_runs
succeeded_runs
failed_runs
success_rate
failure_rate
duration_p50_ms
duration_p95_ms
route_distribution
worker_distribution
error_distribution
~~~

Rate denominator:

~~~text
completed_runs = succeeded_runs + failed_runs

success_rate = succeeded_runs / completed_runs
failure_rate = failed_runs / completed_runs
~~~

Running runs are counted separately and do not dilute success/failure rates.

Latency percentiles use completed runs with a recorded duration. The current implementation
uses linear interpolation between sorted duration samples.

Route distribution counts finalized runs with a known route.

Worker distribution counts completed worker-role occurrences.

Error distribution counts failed runs by stored safe error type.

### Integration wiring

The Vite development proxy now includes:

~~~text
/operations
~~~

and the normal read-only smoke script checks:

~~~text
/operations/summary?hours=24
~~~

in addition to health, effective configuration, and conversation APIs.

### Step 2 coverage

Tests cover:

- safe run listing;
- failure error redaction through the HTTP API;
- status/agent/conversation filtering;
- pagination;
- run detail;
- unknown-run 404;
- running-vs-completed rate semantics;
- P50/P95 latency;
- route/worker/error distributions;
- empty-completed-run behavior;
- invalid pagination/window bounds.

Focused local gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_agent_run_telemetry.py tests/test_operations_api.py tests/test_persistent_chat.py tests/test_chat_api.py
~~~

With local FastAPI + PostgreSQL running:

~~~powershell
cd web
npm run smoke
~~~

## Step 3 — Structured Logs and Metrics

Add request/run correlation:

~~~text
request_id
run_id
conversation_id
~~~


Use structured application logging and add Prometheus-compatible metrics for:

- request count;
- agent run count;
- run duration;
- failures by category;
- route count;
- worker count.

OpenTelemetry integration can be added behind configuration once the internal run model
and metric names are stable.


## Step 4 — Evaluation Run Persistence

Wrap the existing retrieval/agent evaluation workflows in a persistent evaluation-run
contract.

Each evaluation run should record:

~~~text
id
suite
dataset/version
git revision
configuration snapshot
started_at
completed_at
status
aggregate metrics
per-case summary
~~~


The existing evaluation scripts remain usable from CLI.

The persistence layer adds reproducibility and comparison rather than replacing the
current evaluators.


## Step 5 — Regression Comparison

Support comparing two evaluation runs:

~~~text
baseline
    vs
candidate
~~~


Report:

- metric delta;
- newly failing cases;
- newly passing cases;
- changed route/tool behavior where available;
- quality regressions exceeding configured thresholds.

This creates a real release-quality gate instead of relying on ad-hoc report reading.


## Step 6 — Operations Web Surface

Add an Operations route to the Vue shell.

Initial views:

~~~text
Overview
├─ run success/failure
├─ latency
├─ routes
└─ recent errors

Runs
├─ recent run table
└─ run detail

Evaluations
├─ evaluation history
└─ baseline vs candidate comparison
~~~


The dashboard should prioritize inspectability over visual polish.


## Validation Policy

Normal backend development:

~~~powershell
uv run ruff check .
uv run pytest -v
~~~


Normal frontend development:

~~~powershell
cd web
npm run typecheck
npm test
npm run build
~~~


Phase 5 integration gates should use deterministic fake agents where possible.

Live model/tool evaluation remains a stage/release gate rather than a requirement for every
small change.


## Deliberately Deferred

Phase 5 does not initially add:

- distributed tracing infrastructure;
- hosted LangSmith dependency;
- arbitrary prompt logging;
- raw model transcript storage;
- user analytics;
- billing/cost accounting;
- alerting/paging.

Those can be added once the internal telemetry contract is stable.


## Resume / Engineering Value

Phase 5 is intended to demonstrate production AI application engineering beyond Agent
orchestration itself:

- durable AI run lifecycle;
- observability;
- structured telemetry;
- regression evaluation;
- reproducible configuration snapshots;
- operational APIs;
- quality comparison workflows;
- dashboard-backed debugging.
