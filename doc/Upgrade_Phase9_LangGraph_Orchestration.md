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
Step 2  Specialist Execution Node                       ✅ implemented
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
## Step 2 — Specialist Execution Node

### Scope

Step 2 keeps the Phase 9 graph in **shadow mode**, but `direct` and `delegate` branches now
execute exactly one validated specialist through the existing `DelegationExecutionService`.

The Step 1 decision-only graph remains available unchanged for routing-only parity tests.

New execution topology:

~~~text
START
  ↓
decision
  ├──────── clarify ─────────────────────→ END
  │
  ├──────── direct ────┐
  │                    ↓
  └──────── delegate → specialist ───────→ END
~~~

The specialist node does not reimplement registry lookup, delegation policy, or envelope
construction. It calls the existing Phase 8 execution service so the same safety contracts are
reused by both the service path and the LangGraph shadow path.

### Execution graph state

`OrchestrationExecutionGraphState` carries only bounded platform-level values:

~~~text
question
context
source_agent_type
explicit_user_clarification
prior_specialist_result
decision
execution
terminal_action
trace
~~~

The result contract is `OrchestrationExecutionGraphResult`:

~~~text
decision
execution
context
terminal_action
trace
~~~

For `clarify`:

~~~text
execution = None
trace = ("decision", "clarify")
~~~

For `direct` or `delegate`:

~~~text
execution.executed = True
trace = ("decision", action, "specialist")
context = execution.context
~~~

This enforces the Step 6 latency principle from Phase 8: **one user orchestration step executes
at most one specialist**.

### Direct path

For a `direct` decision, the graph:

1. validates the decision through `OrchestrationDecisionModel`;
2. enters the specialist node;
3. calls `DelegationExecutionService.execute(...)`;
4. executes only the selected Agent;
5. returns the public `SpecialistResultEnvelope`.

A prior specialist result is deliberately not forwarded on the direct path.

### Delegate path

For a `delegate` decision, the specialist node forwards only the explicit allowlisted inputs
already accepted by the Phase 8 execution service:

~~~text
current question
DelegationContext
explicit user clarification
public prior SpecialistResultEnvelope
~~~

`DelegationExecutionService` then revalidates the handoff, appends the handoff to context,
builds `CrossAgentContextEnvelope`, renders the safe target input, executes exactly one target
Agent, and projects the target result back to `SpecialistResultEnvelope`.

Therefore LangGraph does not gain access to raw prompt state, raw tool output, credentials,
worker state, or hidden specialist internals.

### Specialist clarification and failure

If the selected specialist itself needs clarification, Step 2 preserves that public result
unchanged. The graph does not recursively choose another Agent.

If the specialist fails, the existing `OrchestrationSpecialistExecutionError` propagates out of
the graph. LangGraph does not retry or execute a second Agent in this step.

### Product boundary

Step 2 still does **not** change:

~~~text
POST /chat
POST /chat/auto
AutoOrchestrationService
Web UI
conversation persistence
OrchestratedSynthesisService
~~~

There is still no production traffic through the Phase 9 graph.

Step 2 is currently invoked explicitly through:

~~~python
run_orchestration_execution_graph(...)
~~~

Step 3 will add synthesis/cross-Agent completion nodes before any product cutover work begins.

### Step 2 coverage

New dedicated coverage verifies:

- `direct` executes exactly one selected specialist;
- `clarify` executes zero specialists;
- `delegate` executes exactly one target specialist;
- delegate context gains exactly one handoff;
- prior public specialist result reaches only the delegated target through the safe envelope;
- explicit user clarification is preserved in the delegated envelope;
- direct flow does not forward a prior specialist result;
- specialist-generated clarification remains a clarification result;
- specialist failure propagates without retrying another Agent;
- empty input is rejected before the decision model or specialist is called.

### Step 2 CI result

At implementation head:

~~~text
Ruff                           passed
Migration / DB contract        passed
Backend                        499 passed
Frontend Typecheck             passed
Frontend                       30 passed
Production build               passed
Production configuration       passed
~~~

## Local Step 2 gate

After pulling the latest Phase 9 branch:

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull
~~~

Run the focused graph/execution gate:

~~~powershell
uv run ruff check .

uv run pytest -v `
  tests/test_orchestration_execution_graph.py `
  tests/test_orchestration_graph.py `
  tests/test_orchestration_execution.py `
  tests/test_orchestration_envelope.py
~~~

Then verify the Phase 8 product path remains unchanged:

~~~powershell
uv run pytest -v `
  tests/test_auto_orchestration.py `
  tests/test_auto_chat_api.py `
  tests/test_orchestration_synthesis.py `
  tests/test_orchestration_evaluation.py
~~~

Finally:

~~~powershell
uv run pytest -v

cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

### Step 2 acceptance boundary

Step 2 is accepted when:

- the focused execution graph gate passes;
- direct/clarify/delegate each preserve their expected call budget;
- delegation still uses the Phase 8 cross-Agent envelope;
- specialist failure does not trigger a second Agent;
- the full backend suite passes;
- the existing Auto Web mode remains unchanged;
- frontend regressions remain green.

Only after this local gate should Step 3 add synthesis and cross-Agent completion nodes to the
LangGraph shadow workflow.
