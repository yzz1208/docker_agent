# Upgrade Phase 10 — Product UX / Performance / Intelligence Polish

Phase 9 completed the LangGraph orchestration architecture and product cutover. Real local usage
then exposed a different class of problems: the system works, but important product details still
make it feel slow, rigid, and unfinished.

Phase 10 treats those findings as first-class engineering work rather than cosmetic cleanup.

## Goals

- make completed answers appear immediately;
- never keep the composer locked after a completed request;
- separate primary response latency from background history synchronization;
- make intelligent orchestration the default new-chat experience;
- avoid heavyweight RAG/runtime work for greetings and product-help requests;
- reduce unnecessary clarification and improve follow-up routing;
- finish Chinese localization across the user-facing product;
- make onboarding, usage guidance, and example prompts discoverable;
- improve observability/settings information architecture and visual polish;
- measure latency and interaction regressions before closeout.

## Roadmap

~~~text
Step 1  Core interaction recovery + Chinese localization + fast chat path   ✅ implemented
Step 2  Latency profiling + RAG warmup + SSE progress + token streaming      ✅ implemented
Step 3  Chat reading/interaction polish + sources + execution detail         ✅ implemented
Step 4  Operations / Settings UX refinement                                  ✅ implemented
Step 5  Intelligence / routing / follow-up quality evaluation                ✅ implemented
Step 6  Product regression gate + Phase 9/10 closeout                        🚧 final gate
~~~

## Step 1 — Core interaction recovery

### 1. Immediate completed-answer rendering

Previously the frontend waited for:

~~~text
POST /chat or /chat/auto
        ↓
GET /conversations/{id}
        ↓
GET /conversations
        ↓
unlock composer
~~~

That meant the model could already have completed while the UI still looked busy. On a slow or
temporarily stale persistence read, the reply could also appear to require a manual refresh.

The new flow is:

~~~text
POST response arrives
        ↓
render user + assistant result immediately
        ↓
unlock composer
        ↓
background conversation/history synchronization
~~~

The optimistic message is replaced by persisted messages once the background sync succeeds.

If synchronization fails, the already-completed answer remains visible and usable. The UI reports
that history synchronization failed without pretending the Agent request itself failed.

### 2. Composer recovery

A completed request no longer waits for the history refresh before sending state is released.

Users can immediately type and submit a follow-up while conversation metadata/history refreshes in
the background.

Approval remains the one intentional lock: when a durable Human Approval interrupt is pending, the
composer stays disabled until the user approves or denies it.

### 3. Intelligent orchestration is the new-chat default

A fresh chat now starts in 智能编排 rather than 手动专家.

Manual expert mode remains available for users who deliberately want a fixed specialist.

### 4. Lightweight conversational fast path

Real usage showed greetings and self-introduction requests entering the Docker docs pipeline. This
can trigger BGE-M3/reranker model loading even though no Docker evidence is required.

Docker Support now has a chat route and a deterministic fast path for:

- greetings;
- expert self-introduction;
- platform introduction;
- capability explanation;
- basic usage/help.

These recognized fast inputs execute:

~~~text
0 router-model calls
0 embedding calls
0 reranker calls
0 Docker tool calls
0 document retrieval calls
~~~

Conceptual Docker questions still use Docker Docs RAG. Runtime questions still use validated
read-only tools.

### 5. Smarter orchestration clarification policy

The platform decision prompt now clarifies only when missing information materially changes:

- specialist choice;
- capability choice; or
- a safe next step.

Broad but answerable requests should make useful progress instead of asking unnecessary questions.
Follow-ups such as “继续”, “what next”, and “still failing” are instructed to use existing
orchestration context and keep the current specialist unless new evidence clearly requires a
handoff.

### 6. Chinese product language

Step 1 removes remaining obvious English product copy from:

- Operations;
- Settings;
- 404 page.

Technical configuration keys, IDs, model names, and canonical route/capability identifiers remain
unchanged where translating them would make debugging or configuration ambiguous.

### 7. Discoverable onboarding

The existing /guide page remains the full usage guide and is linked from the main navigation and
new-chat empty state.

The intelligent-chat empty state now also provides clickable examples:

~~~text
了解平台              介绍一下这个平台
Docker 问题           Docker daemon 连不上
跨专家排障            容器正常但服务持续 503
~~~

Selecting an example fills the composer so users can inspect/edit it before sending.

## Step 1 acceptance gate

Backend:

~~~powershell
uv run ruff check .

uv run pytest -v `
  tests/test_agent_router.py `
  tests/test_agent_service.py `
  tests/test_orchestration_decision.py
~~~

Frontend:

~~~powershell
cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

Important UX checks:

1. a completed answer becomes visible as soon as the POST response returns;
2. the composer becomes available without waiting for history synchronization;
3. a temporary history GET failure does not erase a completed answer;
4. 你好 and 简单介绍自己 do not invoke RAG or Docker tools;
5. a new conversation defaults to 智能编排;
6. Operations, Settings and 404 no longer contain obvious English UI copy;
7. the usage guide and example prompts are easy to discover.

After Step 1 is locally accepted, Step 2 will focus on measured latency rather than perceived
latency: cold RAG model loading, warmup strategy, model-call budgets, and per-stage progress timing.


## Step 2 — Latency profiling, warmup and progress feedback

### 2A. Per-stage latency profiling

The backend now records bounded Prometheus histograms for the expensive internal stages instead of
only exposing whole-request latency.

Current stage labels include:

~~~text
orchestration_decision
decision
rag_database
embedding
dense_retrieval
keyword_retrieval
fusion
rerank
runtime
answer
synthesis
context_build
~~~

The metrics are emitted as `docker_agent_stage_duration_seconds` histograms and structured
`Agent stage completed` logs. This makes it possible to identify whether slow requests are caused
by orchestration, local BGE models, retrieval/database work, Docker runtime inspection, or LLM
generation before changing model budgets or architecture.

### 2B. Explicit RAG model warmup

BGE-M3 and the reranker remain lazy by default, but they now expose explicit warmup state and
warmup methods. Docker Support can preload the document database, embedding model and reranker
before the first documentation request.

A new setting controls startup behavior:

~~~dotenv
RAG_WARMUP_ON_STARTUP=false
~~~

Development and test examples keep warmup disabled so lightweight commands and tests do not
unnecessarily load PyTorch/model weights. The production example enables a background startup
warmup. Application readiness is not blocked by model loading; if a documentation request arrives
before warmup finishes, the existing retrieval lock makes it wait for the same model load instead
of starting a competing load.

Warmup duration is also included in the stage metrics using
`embedding_model_warmup` and `reranker_model_warmup`.

### 2C. Backend-driven progress, token streaming and TTFT

The default intelligent-orchestration path now uses:

~~~text
POST /chat/auto/stream
~~~

The stream emits real backend execution events rather than frontend timers. Supported product
states include orchestration decision, Agent decision, knowledge retrieval, reranking, runtime
diagnostics, answer generation and cross-Agent synthesis.

Only public answer text is allowed into the token stream. Internal decision JSON, tool payloads,
evidence bundles and hidden orchestration state remain outside the public delta channel.

The OpenAI-compatible model client uses `stream=true` when a public stream is active. The backend
records request-to-first-public-token latency as:

~~~text
docker_agent_time_to_first_token_seconds
~~~

The frontend renders deltas immediately and replaces them with the final persisted answer after the
turn completes. The original non-streaming `POST /chat/auto` contract remains available for
compatibility.

### 2D. Product-visible performance telemetry

Operations now reads a bounded in-process performance snapshot from:

~~~text
GET /operations/performance
~~~

The overview shows:

- average TTFT;
- TTFT P95 histogram upper bound;
- slowest execution stages;
- stage sample count;
- average, P50 and P95-upper-bound stage latency.

This complements the persistent Agent-run P50/P95 metrics and raw Prometheus endpoint. The snapshot
is intentionally process-local and resets when the backend process restarts.

## Step 3 — Chat reading, sources and execution detail

Step 3 makes the chat usable as an inspectable technical-support product rather than a plain text
box.

Implemented:

- assistant answer token streaming;
- Markdown/code-friendly answer rendering;
- cited Docker documentation sources alongside completed answers;
- cited runtime-tool sources alongside completed answers;
- source metadata persisted into execution traces so reopening history keeps traceability;
- source metadata carried through specialist result envelopes in intelligent orchestration;
- expandable Worker execution detail instead of exposing all engineering metadata by default;
- optimistic completed answers are replaced by the persisted conversation without flicker;
- approval-pending turns remain visually distinct from completed turns.

The default view keeps the answer primary. Detailed execution metadata remains progressively
disclosed for debugging and technical inspection.

## Step 4 — Operations and Settings refinement

Operations is now organized around three product tasks:

~~~text
Overview
Runs
Evaluations
~~~

The overview includes success/failure state, run latency, TTFT, live stage performance and recent
activity. Run detail exposes route, workers, duration and bounded error information. Evaluation
history supports persisted baseline/candidate comparison.

Settings now:

- separates editable Agent configuration from environment-managed infrastructure values;
- shows whether each effective value came from a persisted override, environment value or default;
- hides secure values while still indicating whether they are configured;
- describes Agent capabilities, toolsets and worker roles;
- keeps unsafe infrastructure and secret fields read-only;
- validates editable ranges before persistence.

## Step 5 — Intelligence and follow-up quality

The orchestration evaluation dataset now explicitly covers product behaviors discovered during real
usage:

- greetings use the deterministic chat fast path;
- platform introduction/help does not enter RAG;
- broad but answerable Docker questions should select a useful specialist instead of clarifying;
- Docker runtime follow-ups keep the current Docker specialist;
- infrastructure incident follow-ups keep the infrastructure specialist;
- cross-Agent delegation still requires the capability/policy checks;
- synthesis preserves uncertainty and specialist provenance.

The GitHub Evaluation Regression Gate now supports the `orchestration` suite in addition to the
existing router/workflow suites.

A live model gate still requires the repository's evaluation model/database secrets and a persisted
baseline run. Code-level coverage is part of normal CI; live-model quality should be run before the
Phase 10 branch is merged into the release line.

## Step 6 — Final regression gate and closeout

Normal CI is the required code gate:

~~~powershell
uv run ruff check .
uv run pytest -v

cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

Production configuration remains part of GitHub CI through Compose validation.

For a real local product gate, run the backend/Web stack and verify:

1. a greeting answers without loading RAG;
2. a documentation question shows real progress and begins rendering text before completion;
3. cited documentation sources are visible and survive history reopen;
4. a runtime question shows runtime evidence without exposing raw unsafe internals;
5. a same-specialist follow-up continues naturally;
6. a cross-specialist handoff pauses for approval and resumes from the durable checkpoint;
7. the composer unlocks after completed turns;
8. Operations shows TTFT/stage data after streamed turns;
9. Settings clearly distinguishes overrides from inherited/environment values;
10. conversation rename/delete/history continue to work after streamed turns.

Live orchestration quality gate:

~~~powershell
uv run python scripts/eval_orchestration.py --repeats 3 --persist
~~~

Then compare that persisted candidate to the accepted baseline through Operations or
`scripts/compare_evaluations.py`.

Phase 10 is considered code-complete after normal CI is green. The final local product gate remains
the place to discover environment-specific latency, model-provider behavior, proxy buffering,
Docker Desktop behavior and other issues that cannot be proven by repository unit tests alone.
