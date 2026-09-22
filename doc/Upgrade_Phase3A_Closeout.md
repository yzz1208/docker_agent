# Upgrade Phase 3A Closeout

## Status

**Phase 3A — Deterministic Role Separation: COMPLETE pending local Ruff/pytest gate**

Phase 3A introduced real worker boundaries and supervisor-driven sequencing without adding
another LLM routing call.

## Architecture

~~~text
User
 ↓
Router
 ↓
AgentRouteDecision
 ↓
Deterministic Supervisor
 ↓
SupervisorPlan
 ↓
┌───────────────────────────────────┐
│ runtime / knowledge / diagnosis   │
└───────────────────────────────────┘
 ↓
LangGraph worker sequencing
 ↓
Grounded answer
~~~

Worker plans:

~~~text
docs_only
→ knowledge
→ diagnosis

runtime_only
→ runtime
→ diagnosis

runtime + docs
→ runtime
→ knowledge
→ diagnosis

clarify
→ no workers
~~~

## Worker Boundaries

- `KnowledgeWorker`: docs retrieval + normalized Knowledge Evidence only.
- `RuntimeWorker`: node-level runtime graph + ToolResult/Evidence/AgentStep only.
- `DiagnosisWorker`: evidence-grounded final synthesis + citation guards only.

## Observable Execution Contract

Internal service result:

~~~text
LangGraphAgentTurnResult
├─ decision
├─ answer
├─ runtime_trace
├─ supervisor_plan
└─ worker_trace
~~~

Each worker trace entry records only safe metadata:

~~~text
index
role
tool_results_added
evidence_added
runtime_steps_added
answer_created
~~~

Raw Docker stdout and complete document evidence are not duplicated into this trace.

## API Bridge

`ChatResponse` now has an optional:

~~~text
execution
~~~

For LangGraph turns it contains:

~~~text
planned_workers
completed_workers
worker_trace
~~~

Legacy agents remain compatible and return:

~~~text
execution = null
~~~

This API shape is suitable for future frontend progress views and persisted chat execution
history without exposing GraphState directly.

## Validation Policy

Phase 3A closes with the normal local development gate:

~~~powershell
uv run ruff check .
uv run pytest -v
~~~

No full Phase 2 parity matrix is required for this structural/product-layer step unless
those tests expose a behavior regression.

## Next Stage

**Phase 3B — Product Persistence and Configuration Foundations**

Recommended order:

1. persistent conversation/message model;
2. persisted execution metadata;
3. user/agent configuration model;
4. API endpoints for conversation history and settings;
5. frontend shell consuming these APIs.

The Docker Support Agent remains the first agent type, but persistence/config contracts
should be designed so later agents can reuse them.
