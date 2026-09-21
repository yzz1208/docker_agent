# Upgrade Phase 3 — Role Separation / Multi-Agent Architecture

## Goal

Turn the stable LangGraph support workflow into a role-oriented architecture without
changing the proven RAG, Docker runtime, Evidence, or answer-grounding behavior.

Phase 3 introduces four responsibilities:

- **Supervisor**: decides which worker roles are required and in what order;
- **Knowledge**: retrieves Docker documentation evidence;
- **Runtime**: collects local Docker runtime evidence through the node-level runtime graph;
- **Diagnosis**: interprets accumulated evidence and produces the grounded final answer.

Diagnosis is also the final synthesis role for docs-only questions.

## Migration Principle

Do not start with another LLM supervisor.

The existing Router already makes a validated decision:

~~~text
docs_only
runtime_tools + use_docs=false
runtime_tools + use_docs=true
clarify
~~~

Phase 3A deterministically maps that validated decision into a worker plan. This gives us
real role boundaries without adding model latency or another source of routing variance.

## Phase 3A Worker Plans

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
→ no worker execution
→ return clarification
~~~

## Phase 3B

Introduce explicit worker service objects:

~~~text
KnowledgeWorker
RuntimeWorker
DiagnosisWorker
~~~

Each worker consumes/updates the existing canonical AgentState/Evidence contracts.

## Phase 3C

Wire the SupervisorPlan into LangGraph so graph edges are driven by worker roles rather
than hard-coded route branches.

## Phase 3D

Only after deterministic role separation is stable, evaluate whether an LLM Supervisor
adds value for genuinely multi-step requests. If not, keep the deterministic supervisor.

## Validation Policy

Phase 3 will not repeat the Phase 2 full matrix after every small edit.

- routine commits: Ruff + targeted unit tests;
- completed worker integration: one representative integration eval;
- Phase 3 closeout: full normal/failure/timeout/permission + Judge.


## Phase 3A Step 2 — Worker Service Boundaries

The first concrete worker services are now defined:

~~~text
KnowledgeWorker
RuntimeWorker
DiagnosisWorker
~~~

Their boundaries are intentionally narrow.

### KnowledgeWorker

Input:

~~~text
AgentState
~~~

Action:

~~~text
docs_retriever(question)
→ RagContext
→ normalized Knowledge Evidence
→ AgentState
~~~

It does not call the answer model and does not touch Docker runtime tools.

### RuntimeWorker

Input:

~~~text
AgentState + AgentRouteDecision
~~~

Action:

~~~text
run_runtime_loop_graph(...)
→ ToolResult
→ Runtime Evidence
→ AgentStep trace
→ AgentState
~~~

It does not retrieve documentation and does not generate the final answer.

### DiagnosisWorker

Input:

~~~text
AgentState + decision + available docs/runtime contexts
~~~

Action:

~~~text
generate_agent_answer_from_evidence(...)
→ citation validation
→ AgentAnswer
→ AgentState.answer
~~~

It does not execute Docker tools or retrieval.

### Why this is useful

The existing support graph currently contains these responsibilities inside node closures.
Phase 3A extracts them as reusable services first. The next step is to make LangGraph nodes
delegate to these workers, then let SupervisorPlan drive worker sequencing.


## Phase 3A Step 3 — LangGraph Nodes Delegate to Workers

The stable unified support graph now delegates its three execution responsibilities:

~~~text
docs node      -> KnowledgeWorker
runtime node   -> RuntimeWorker
answer node    -> DiagnosisWorker
~~~

The route node is intentionally unchanged.

This is a structural refactor only. Worker order is still controlled by the existing graph
edges, so current runtime behavior, retrieval behavior, citation guards, and answer output
contracts remain unchanged.

The next step is to add SupervisorPlan to graph state and let the supervisor plan, rather
than route-specific hard-coded edges, determine the worker sequence.


## Phase 3A Step 4 — SupervisorPlan Drives the Graph

The unified support graph no longer hard-codes route-specific worker transitions.

The route node now performs:

~~~text
route_question(...)
→ AgentRouteDecision
→ plan_workers(...)
→ SupervisorPlan
~~~

Graph transport state now includes:

~~~text
supervisor_plan
worker_index
completed_workers
~~~

The same conditional transition function is used after route and after every worker:

~~~text
SupervisorPlan.workers[worker_index]
→ runtime | knowledge | diagnosis | END
~~~

Examples:

~~~text
("knowledge", "diagnosis")
("runtime", "diagnosis")
("runtime", "knowledge", "diagnosis")
()
~~~

Each worker validates that it is the worker expected at the current plan position, then
advances the index and records itself in completed_workers.

This removes route-specific worker sequencing from LangGraph edges while keeping the
existing validated Router as the source of the deterministic supervisor plan.
