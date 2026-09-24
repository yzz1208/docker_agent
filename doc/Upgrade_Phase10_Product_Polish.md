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
Step 2  Latency profiling + RAG warmup/caching + progress feedback          🚧 in progress
Step 3  Chat reading/interaction polish + sources + execution detail         ⏳
Step 4  Operations / Settings UX refinement                                  ⏳
Step 5  Intelligence / routing / follow-up quality evaluation                ⏳
Step 6  Product regression gate + Phase 9/10 closeout                        ⏳
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
unnecessarily load PyTorch/model weights. The production example enables warmup so cold model
loading happens during application startup rather than inside the first real user request.

Warmup duration is also included in the stage metrics using
`embedding_model_warmup` and `reranker_model_warmup`.

### Remaining Step 2 work

The next Step 2 slice should use these measurements to tune the largest real bottleneck, then add
true workflow progress delivery to the chat UI. Progress must be driven by backend execution events
rather than guessed timers. Token streaming/TTFT measurement should be added with that transport so
the UI can distinguish:

~~~text
正在判断问题
正在检索文档
正在重排序
正在运行诊断
正在生成回答
正在综合结果
~~~

Step 2 is not considered complete until the progress transport and measured latency regression gate
are implemented.
