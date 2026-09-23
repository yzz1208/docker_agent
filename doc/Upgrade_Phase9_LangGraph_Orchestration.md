# Upgrade Phase 9 — LangGraph Platform Orchestration

## Goal

Phase 9 migrates the platform-level Auto Orchestration runtime onto an explicit LangGraph
workflow without changing the already-stable Phase 8 product behavior all at once.

Phase 8 established:

~~~text
decision
  ↓
bounded delegation
  ↓
specialist execution
  ↓
cross-Agent envelope
  ↓
optional synthesis
  ↓
Auto Web mode
~~~

Phase 9 turns that orchestration chain into a graph with explicit state, conditional edges,
checkpoint/resume boundaries, and later human-in-the-loop extension points.

The migration remains conservative:

- manual specialist Chat remains unchanged;
- `/chat/auto` remains on the Phase 8 service until parity is proven;
- every graph migration step first runs as a shadow/test path;
- existing orchestration contracts remain the source of truth.

## Planned steps

~~~text
Step 1  Decision Graph Foundation / Shadow Parity       ✅ implemented
Step 2  Specialist Execution Node                       ⏳
Step 3  Cross-Agent Envelope + Synthesis Nodes          ⏳
Step 4  Durable Checkpoint / Resume                      ⏳
Step 5  Human Approval / Interrupt Boundary              ⏳
Step 6  Auto Chat Shadow Comparison + Product Cutover    ⏳
Step 7  Evaluation + Phase Closeout                      ⏳
~~~

## Step 1 — Decision Graph Foundation

### Scope

Step 1 migrates only the orchestration **decision topology** into LangGraph.

Added:

~~~text
src/docker_agent/orchestration/graph.py
tests/test_orchestration_graph.py
~~~

Graph topology:

~~~text
START
  ↓
decision
  ├──────── clarify ───────→ END
  ├──────── direct ────────→ END
  └──────── delegate ──────→ END
~~~

The `decision` node calls the existing `OrchestrationDecisionModel`. Therefore all Phase 8
validation remains active:

- Registry-backed Agent identity;
- capability validation;
- clarify contract;
- direct-owner continuity;
- delegation policy;
- loop protection;
- hop-limit protection;
- no invented Agent/capability.

Step 1 does **not** execute a specialist. The three terminal nodes only record which validated
branch would run next.

### Graph state

The shadow graph carries a bounded `OrchestrationDecisionGraphState`:

~~~text
question
context
source_agent_type
decision
terminal_action
trace
~~~

The public `OrchestrationDecisionGraphResult` exposes:

~~~text
decision
context
terminal_action
trace
~~~

and enforces the invariant:

~~~text
terminal_action == decision.action
trace == ("decision", terminal_action)
~~~

This gives later Phase 9 steps a stable graph transport contract without copying hidden Agent
state or weakening Phase 8 policy checks.

### Shadow-only boundary

Step 1 deliberately does not change:

~~~text
POST /chat
POST /chat/auto
AutoOrchestrationService
DelegationExecutionService
OrchestratedSynthesisService
Web UI
conversation persistence
~~~

The graph is currently invoked only by tests or explicit code using:

~~~python
run_orchestration_decision_graph(...)
~~~

This is intentional. We first prove parity before moving any product traffic.

### Step 1 coverage

Dedicated tests verify:

- direct routing reaches the `direct` terminal;
- clarification reaches the `clarify` terminal;
- validated handoff intent reaches the `delegate` terminal;
- graph decision output matches the existing direct decision contract;
- the graph still performs exactly one decision-model call;
- invalid platform-level delegation is rejected by the existing policy;
- empty input is rejected before any model call;
- inconsistent graph result state cannot be constructed.

## Local Step 1 gate

After pulling the Phase 9 branch:

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull
~~~

Run the focused Step 1 gate first:

~~~powershell
uv run ruff check .

uv run pytest -v `
  tests/test_orchestration_graph.py `
  tests/test_orchestration_decision.py `
  tests/test_agent_delegation.py
~~~

Then run the Phase 8 orchestration regression set:

~~~powershell
uv run pytest -v `
  tests/test_orchestration_execution.py `
  tests/test_orchestration_envelope.py `
  tests/test_orchestration_synthesis.py `
  tests/test_auto_orchestration.py `
  tests/test_auto_chat_api.py `
  tests/test_orchestration_evaluation.py
~~~

If those are green, run the complete backend gate:

~~~powershell
uv run pytest -v
~~~

Frontend is not changed by Step 1, but the full local project gate remains:

~~~powershell
cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

## Step 1 acceptance boundary

Step 1 is accepted when:

- Ruff passes;
- focused decision-graph tests pass;
- Phase 8 orchestration regression tests pass;
- the full backend suite passes;
- existing Web gates remain green;
- `/chat/auto` behavior remains unchanged.

Only after that local gate will Step 2 connect a validated `direct/delegate` graph branch to
`DelegationExecutionService`.
