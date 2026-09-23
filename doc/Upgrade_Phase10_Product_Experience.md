# Upgrade Phase 10 — Product Experience & Responsiveness

## Goal

Phase 9 completed the LangGraph orchestration platform and product cutover. Phase 10 focuses on day-to-day usability: latency, interaction feedback, localization, conversational quality, help content, and product polish.

## Step 1 — UX, Localization, and Warm-Path Performance

Status: implemented, pending final local product gate.

### RAG warm-path performance

Previously each Docker documentation turn recreated the SQLAlchemy engine, BGE-M3 embedder, and BGE reranker, and then cleared CUDA cache. Repeated documentation questions therefore behaved like repeated cold starts.

The Docker Support Agent now lazily creates and reuses the PostgreSQL engine, BGE-M3 embedder, and BGE reranker for the lifetime of the cached Agent instance. The first documentation request may still incur local model-load cost; later requests avoid reloading these heavy resources.

### Lightweight conversational fast path

A new `general_chat` route handles narrow product/conversational messages such as greetings, assistant self-introduction, product capability questions, usage guidance, and thanks.

The fast path is deliberately narrow. Messages containing technical markers such as containers, Compose, logs, CPU, memory, restart, OOM, or 503 stay on the normal technical routing path.

For the most common greetings and product-help questions, platform routing, Docker routing, answer-model calls, RAG, and runtime tools are all skipped. The application returns deterministic product guidance immediately.

Technical answers remain evidence-gated; this does not relax Docker Docs or runtime citation requirements.

`general_chat` is supported consistently by DockerSupportAgent, DynamicDockerSupportAgent, SupervisorPlan, DiagnosisWorker, the unified support graph, and the platform orchestration decision model.

### Responsive chat interaction

The workspace now shows the submitted user message immediately, displays a visible thinking state, retains the completed answer while persisted history refreshes, and automatically scrolls to the latest activity.

If the secondary history refresh fails after the backend already completed the Agent turn, the answer stays visible and the composer is unlocked. A refresh failure no longer makes a successful request appear failed.

Regression coverage verifies that another message can be sent immediately after a completed turn.

### Rich message rendering

Assistant messages now use a safe structured renderer for headings, paragraphs, lists, fenced code blocks, inline code, and bold text. It uses Vue interpolation rather than raw HTML insertion.

### Chinese localization

The Operations dashboard and Settings page are now primarily Chinese, including filters, KPI labels, run/evaluation details, configuration sources, common field labels, capability labels, and empty/error states. Stable internal identifiers remain unchanged.

### In-product guide

A new `/help` route and top-navigation item `使用帮助` provide product introduction, mode explanation, Human Approval safety boundary, example questions, workflow overview, page descriptions, and practical usage tips.

### Current latency boundary

This step improves repeated RAG latency and perceived responsiveness, but it does not yet implement token streaming. API calls still return one completed turn at a time.

## Focused local gate

```powershell
git fetch
git switch feat/upgrade-phase-10-product-experience
git pull

uv sync --all-groups
uv run ruff check .

uv run pytest -v `
  tests/test_agent_router.py `
  tests/test_agent_service.py `
  tests/test_dynamic_service.py `
  tests/test_multi_agent_supervisor.py `
  tests/test_multi_agent_workers.py `
  tests/test_graph_workflow.py `
  tests/test_orchestration_decision.py

cd web
npm run typecheck
npm test
npm run build
cd ..

uv run pytest -v
```

## Manual product gate

1. In manual Docker Support mode, send `你好，介绍一下自己`. It should answer naturally instead of asking for a Docker question.
2. Immediately send a second message; the composer should remain usable without reloading.
3. Ask the same documentation question twice. The second request should avoid reloading BGE-M3 and the reranker.
4. Confirm the chat automatically follows the latest activity and displays an in-progress state.
5. Confirm structured answers render headings, lists, and code cleanly.
6. Open `运行观测` and `设置` and check the Chinese interface.
7. Open `使用帮助` from the top navigation.
8. Confirm Smart Orchestration approval still works after the Phase 9 cutover.

## Next Phase 10 work

After this local gate, continue with measured improvements: request-stage latency metrics, optional provider connection reuse, true SSE/token streaming if useful, richer orchestration observability, conversation search/filtering, responsive/accessibility polish, and product-level conversational evaluation.
