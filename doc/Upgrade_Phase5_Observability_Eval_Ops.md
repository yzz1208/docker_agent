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


### Step 3 implementation status

**IMPLEMENTED pending local Ruff/pytest/smoke gate**

The application now has three complementary observability layers:

~~~text
durable Operations data
    = PostgreSQL agent_runs history

structured JSON logs
    = request/run debugging and correlation

Prometheus-compatible metrics
    = process/runtime monitoring
~~~

### Correlation identifiers

Every HTTP request receives:

~~~text
X-Request-ID
~~~

A valid incoming `X-Request-ID` is preserved. Unsafe or missing values are replaced by a
new generated identifier.

Every successful chat response also exposes:

~~~text
X-Run-ID
X-Conversation-ID
~~~

Inside one Agent execution, ContextVar-based correlation provides:

~~~text
request_id
run_id
conversation_id
~~~

to nested application logs without passing those identifiers through every function
signature.

The correlation context is scoped and restored after each request/run so identifiers do
not leak into another execution.

### Structured JSON logging

The `docker_agent` logger now emits compact JSON records to stderr/stdout-compatible
logging handlers.

Operational fields are deliberately bounded:

~~~text
request_id
run_id
conversation_id
http_method
http_route
http_status
duration_ms
agent_type
agent_status
agent_route
error_type
worker_count
~~~

Application log level is configurable through:

~~~text
APP_LOG_LEVEL=INFO
~~~

Secret-like patterns in both log messages and formatted exception traces are redacted for
common API-key/token/password/Bearer/sk-* forms.

Raw prompts, model responses, retrieved contexts, and Docker stdout are not added to
structured log metadata by this layer.

### HTTP request telemetry

The FastAPI middleware records:

~~~text
method
route template
status
duration for structured logs
~~~

Prometheus labels use the route template rather than raw path parameters, preventing
run/conversation IDs from becoming high-cardinality labels.

Unmatched routes use a single:

~~~text
unmatched
~~~

label.

### Prometheus-compatible endpoint

Metrics are exposed at:

~~~text
GET /metrics
~~~

without adding a third-party metrics dependency.

Current metrics:

~~~text
docker_agent_http_requests_total{method,route,status}

docker_agent_runs_total{status}

docker_agent_run_failures_total{error_type}

docker_agent_run_routes_total{route}

docker_agent_worker_executions_total{worker}

docker_agent_run_duration_seconds
    _bucket
    _sum
    _count
~~~

Run-duration histogram buckets:

~~~text
0.1
0.25
0.5
1
2.5
5
10
30
60
+Inf
seconds
~~~

The `/metrics` scrape itself is intentionally excluded from the HTTP request counter.

### Cardinality policy

The following values are **never Prometheus labels**:

~~~text
request_id
run_id
conversation_id
raw user text
raw error message
container id/name
~~~

They belong in correlated logs or durable Operations records instead.

This prevents unbounded metric-series growth.

### Persistence vs metrics semantics

~~~text
Operations API / agent_runs
    durable
    survives process restart
    queryable historical record

/metrics
    in-process
    resets when the process restarts
    intended for Prometheus scraping/aggregation
~~~

The two layers intentionally overlap on some counters but serve different operational
purposes.

### Step 3 coverage

Tests now cover:

- nested ContextVar correlation and restoration;
- safe incoming request-id preservation;
- unsafe request-id replacement;
- structured JSON correlation fields;
- log secret redaction;
- Prometheus counter/histogram exposition;
- HTTP request metrics and `X-Request-ID`;
- metrics scrape self-exclusion;
- Chat `X-Run-ID` / `X-Conversation-ID`;
- successful and failed run metric emission;
- deep Agent `handle()` inheritance of request/run/conversation context.

The read-only integration smoke now also checks:

~~~text
GET /metrics
~~~

Focused local gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_observability.py tests/test_observability_api.py tests/test_agent_run_telemetry.py tests/test_operations_api.py tests/test_persistent_chat.py tests/test_chat_api.py
~~~

With FastAPI + PostgreSQL running:

~~~powershell
cd web
npm run smoke
~~~

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


### Step 4 implementation status

**IMPLEMENTED pending local Ruff/pytest gate**

Phase 5 now persists evaluation history independently from chat/run telemetry.

### Durable evaluation schema

~~~text
evaluation_runs
├─ id
├─ suite
├─ dataset_name
├─ dataset_version
├─ git_revision
├─ status
├─ config_snapshot
├─ aggregate_metrics
├─ case_count
├─ passed_count
├─ failed_count
├─ error_type
├─ error_message
├─ started_at
└─ completed_at

evaluation_case_results
├─ id
├─ evaluation_run_id
├─ case_key
├─ case_id
├─ phase
├─ repeat
├─ status
├─ metrics
├─ details
└─ created_at
~~~

`case_key` is unique within one run and is the stable comparison key for Step 5.

For Router evaluations it uses:

~~~text
case_id:phase:repeat
~~~

so initial/follow-up and repeated routing samples do not collide.

### Dataset and revision identity

Dataset versions use the SHA-256 digest of the evaluation file:

~~~text
sha256:<64-hex-digest>
~~~

Git revision is read directly from local `.git` metadata when available. The persistence
layer does not invoke a shell or subprocess.

### Safe configuration snapshots

Evaluation configuration snapshots are recursively sanitized before persistence.

Secret/infrastructure keys such as:

~~~text
api_key
token
password
secret
credential
private_key
base_url
database_url
~~~

are replaced with metadata like:

~~~json
{"configured": true, "redacted": true}
~~~

rather than storing the original value.

Failed evaluation-run error messages reuse the same compact secret-redaction logic as Agent
run telemetry.

### Evaluation repository

The persistence API now supports:

~~~text
create_evaluation_run
add_evaluation_case
finalize_evaluation_run_success
finalize_evaluation_run_failure
get_evaluation_run
list_evaluation_runs
list_evaluation_cases
dataset_version
resolve_git_revision
sanitize_evaluation_payload
~~~

Run finalization derives:

~~~text
case_count
passed_count
failed_count
~~~

from persisted case rows rather than trusting caller-supplied totals.

### Existing evaluator integration

Two representative suites now support:

~~~text
--persist
~~~

without changing their default behavior:

~~~powershell
uv run python scripts/eval_agent_router.py --persist
uv run python scripts/eval_agent_workflow.py --persist
~~~

Without `--persist`, both scripts keep their previous file/stdout-only workflow.

Router persistence stores:

- stable case/phase/repeat identity;
- exact-plan metrics;
- safe expected/actual details;
- aggregate router summary.

Workflow persistence stores:

- per-case workflow metrics;
- safe expected/actual/error/judge diagnostics;
- aggregate workflow/judge summary.

Questions and full generated answers are deliberately excluded from persisted per-case
details in these first adapters.

The remaining retrieval/answer/parity suites can now adopt the same repository contract
without introducing new tables.

### Evaluation Operations API

Read APIs are available at:

~~~text
GET /operations/evaluations
GET /operations/evaluations/{evaluation_run_id}
~~~

List supports:

~~~text
suite
limit
offset
~~~

Detail returns the run plus ordered per-case results.

This API is intentionally read-only in Phase 5. Evaluation execution remains an explicit
CLI/CI action.

### Step 4 coverage

Tests cover:

- dataset SHA-256 versioning;
- recursive snapshot secret redaction;
- successful evaluation lifecycle;
- failed evaluation lifecycle;
- safe error messages;
- unique case keys;
- duplicate finalization rejection;
- suite filtering;
- persisted case retrieval;
- Evaluation History HTTP list/detail;
- pagination validation;
- secret-safe API responses.

The normal integration smoke now also checks:

~~~text
GET /operations/evaluations?limit=1&offset=0
~~~

Focused local gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_evaluation_persistence.py tests/test_evaluation_api.py tests/test_observability.py tests/test_observability_api.py tests/test_operations_api.py
~~~

Optional live evaluator persistence checks:

~~~powershell
uv run python scripts/eval_agent_router.py --limit 2 --persist
uv run python scripts/eval_agent_workflow.py --limit 2 --persist
~~~

These optional commands can consume model resources and are not part of every unit-test run.

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


### Step 5 implementation status

**IMPLEMENTED pending local Ruff/pytest gate**

Phase 5 can now compare two persisted evaluation runs and turn the result into a release
quality gate.

### Comparability rules

A comparison is accepted only when:

~~~text
baseline != candidate
baseline.status == succeeded
candidate.status == succeeded
baseline.suite == candidate.suite
baseline.dataset_version == candidate.dataset_version
~~~

This prevents accidental comparisons across different suites or dataset revisions.

The two runs may have different:

~~~text
git_revision
config_snapshot
model configuration
implementation revision
~~~

because those differences are often exactly what the comparison is intended to measure.

### Case alignment

Cases are aligned by the persisted:

~~~text
case_key
~~~

The comparison reports:

~~~text
common_case_count
baseline_only_case_keys
candidate_only_case_keys
new_failures
new_passes
unchanged_failures
~~~

Status semantics:

~~~text
baseline passed -> candidate failed/error
    = new failure

baseline failed/error -> candidate passed
    = new pass
~~~

If the case sets are not identical, the comparison verdict is:

~~~text
incomplete
~~~

and the gate fails.

This prevents a candidate evaluated with a different `--limit`, repeat count, or partial
case set from appearing artificially better.

### Aggregate metric comparison

Numeric aggregate metrics are recursively discovered from both runs.

Only quality-like metric paths are compared. Current name hints include:

~~~text
accuracy
coverage
f1
match
precision
rate
recall
score
~~~

Direction defaults to:

~~~text
higher_is_better
~~~

Metrics containing:

~~~text
error_rate
failure_rate
latency
duration
~~~

use:

~~~text
lower_is_better
~~~

Each metric reports:

~~~text
baseline_value
candidate_value
delta
quality_delta
direction
threshold
regression
improvement
~~~

`delta` is always:

~~~text
candidate - baseline
~~~

`quality_delta` normalizes direction so:

~~~text
positive = improvement
negative = degradation
~~~

The default allowed absolute regression is:

~~~text
0.02
~~~

For rate metrics in the 0..1 range, this corresponds to two percentage points.

The threshold can be changed per comparison with:

~~~text
max_regression
~~~

A quality metric becomes a regression when:

~~~text
quality_delta < -max_regression
~~~

### Gate verdict

The final verdict is one of:

~~~text
pass
regression
incomplete
~~~

The gate fails when any of the following is true:

- at least one common case becomes a new failure;
- at least one quality metric exceeds the allowed regression threshold;
- the baseline and candidate case-key sets differ.

New passes can offset neither new failures nor metric regressions. They are reported
separately so improvements remain visible.

### Behavior and configuration diagnostics

For common cases, the comparison reports changes in available actual behavior fields:

~~~text
route
tools / tools_called
container
~~~

These changes are diagnostic only. They do not automatically fail the gate because a route
or tool change can be an intentional implementation improvement.

Sanitized configuration snapshots are also flattened and compared, producing:

~~~text
configuration_changes
~~~

This helps answer:

~~~text
What configuration changed between the baseline and candidate?
~~~

without exposing secrets.

### Comparison API

The Operations API now exposes:

~~~text
GET /operations/evaluations/compare
~~~

Query parameters:

~~~text
baseline_id
candidate_id
max_regression=0.02
~~~

The endpoint returns:

- verdict and gate_passed;
- case transitions;
- aggregate metric deltas;
- route/tool behavior changes;
- safe configuration changes.

### CI / release CLI gate

A CI-friendly CLI is available:

~~~powershell
uv run python scripts/compare_evaluations.py --baseline <BASELINE_RUN_ID> --candidate <CANDIDATE_RUN_ID>
~~~

Optional threshold:

~~~powershell
uv run python scripts/compare_evaluations.py --baseline <BASELINE_RUN_ID> --candidate <CANDIDATE_RUN_ID> --max-regression 0.01
~~~

Exit codes:

~~~text
0 = gate passed
1 = regression or incomplete case set
2 = invalid comparison / missing run / invalid arguments
~~~

The command prints the complete comparison as JSON, making it suitable for CI artifacts
and later GitHub Actions integration.

### Step 5 coverage

Tests cover:

- new failures and new passes;
- higher-is-better regression metrics;
- lower-is-better regression metrics;
- tolerated metric degradation below the configured threshold;
- route/tool behavior changes;
- safe configuration changes;
- incomplete case-set detection;
- incompatible suite rejection;
- missing-run API behavior;
- invalid threshold handling;
- comparison API response contract.

Focused local gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_evaluation_comparison.py tests/test_evaluation_comparison_api.py tests/test_evaluation_persistence.py tests/test_evaluation_api.py
~~~

Example persisted evaluation workflow:

~~~powershell
uv run python scripts/eval_agent_router.py --persist
# change code/config
uv run python scripts/eval_agent_router.py --persist
uv run python scripts/compare_evaluations.py --baseline <OLD_RUN_ID> --candidate <NEW_RUN_ID>
~~~

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
