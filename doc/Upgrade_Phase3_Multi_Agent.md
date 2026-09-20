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
