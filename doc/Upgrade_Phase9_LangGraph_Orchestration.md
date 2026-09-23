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
Step 3  Cross-Agent Envelope + Synthesis Nodes          ✅ implemented
Step 4  Durable Checkpoint / Resume                      ✅ implemented
Step 5  Human Approval / Interrupt Boundary              ✅ implemented
Step 6  Auto Chat Shadow Comparison + Product Cutover    ✅ (6A parity + 6B cutover)
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
## Step 3 — Cross-Agent Envelope + Synthesis Nodes

### Scope

Step 3 extends the shadow workflow through final public completion while preserving the
Phase 8 latency and provenance rules.

New topology:

~~~text
START
  ↓
decision
  ├──────── clarify ─────────────────────────────→ END
  │
  ├──────── direct ────→ specialist ─→ complete ─→ END
  │
  └──────── delegate ─→ specialist
                            │
                            ├─ clarification ─→ complete ─→ END
                            │
                            ├─ no prior result ─→ complete ─→ END
                            │
                            └─ prior + current public results
                                      ↓
                                  synthesis ─────────────→ END
~~~

The Step 1 decision graph and Step 2 execution graph remain available unchanged. Step 3 adds
a third explicit shadow entry point:

~~~python
run_orchestration_synthesis_graph(...)
~~~

### Synthesis graph state

`OrchestrationSynthesisGraphState` carries:

~~~text
question
context
source_agent_type
explicit_user_clarification
user_observations
prior_specialist_result
decision
execution
synthesis
final_answer
final_clarification
terminal_action
trace
~~~

`user_observations` are still caller-supplied provenance. The graph does not manufacture
observations from specialist text.

The public result contract is `OrchestrationSynthesisGraphResult`:

~~~text
decision
execution
synthesis
context
terminal_action
answer
clarification
trace
synthesized
~~~

The result enforces that answer and clarification cannot coexist, graph execution must match
the validated decision/context, and synthesis traces cannot be confused with direct completion.

### Direct fast path

A direct decision never calls the synthesis model:

~~~text
decision
  ↓
specialist
  ↓
complete
~~~

The final public answer is taken from the specialist turn answer, falling back to the public
`SpecialistResultEnvelope.summary` only when needed.

This preserves the Phase 8 performance rule: one short routing decision plus one specialist
execution, with zero synthesis calls.

### Delegate + synthesis path

Delegation still runs through `DelegationExecutionService`, so Step 3 continues to reuse the
Phase 8 `DelegationPolicy` and `CrossAgentContextEnvelope` rather than duplicating them.

Synthesis is entered only when all of the following are true:

~~~text
decision.action == delegate
current specialist completed without clarification
prior public SpecialistResultEnvelope exists
~~~

The synthesis node passes exactly two attributed public results:

~~~text
prior specialist public result
current target specialist public result
~~~

plus explicit caller-supplied user observations and the original query from
`DelegationContext.original_query`.

The synthesis layer remains the existing `OrchestratedSynthesisService`, so its strict JSON
schema, untrusted-data prompt boundary, provenance rules, disagreement handling, output
bounds, and clarification precedence remain active.

### Clarification precedence

Step 3 has two clarification boundaries:

1. orchestration decision clarification — no specialist executes;
2. specialist clarification — no synthesis model executes.

If an older public specialist result itself still requires clarification, the synthesis service
also short-circuits deterministically and returns that clarification without a model call.

Therefore the graph never generates a synthesized answer while a required clarification is
still unresolved.

### Delegate without a prior result

A validated delegate decision can technically be executed without a prior public result.
In that case the target specialist still executes and the graph returns its public result
directly, but synthesis is skipped because there are not two attributed specialist results.

This avoids inventing multi-Agent context merely to force a synthesis step.

### Trace contracts

Decision clarification:

~~~text
("decision", "clarify")
~~~

Direct or non-synthesized specialist completion:

~~~text
("decision", action, "specialist", "complete")
~~~

Cross-Agent synthesis:

~~~text
("decision", "delegate", "specialist", "synthesis")
~~~

These traces are bounded and contain workflow-stage names only. They do not contain prompts,
raw tools, hidden reasoning, credentials, or worker internals.

### Product boundary

Step 3 remains shadow-only. It still does **not** change:

~~~text
POST /chat
POST /chat/auto
AutoOrchestrationService
Web UI
conversation persistence
~~~

The existing Chinese Auto-Orchestration product path continues to use the Phase 8 service.
Phase 9 will not receive production traffic until checkpoint/resume and shadow parity are
implemented and verified.

### Step 3 coverage

Dedicated tests verify:

- direct fast path executes one specialist and zero synthesis calls;
- decision clarification executes zero specialists and zero synthesis calls;
- delegate with prior/current public results performs exactly one synthesis call;
- synthesis receives both canonical contributing Agents;
- caller-supplied user observations retain explicit provenance;
- original query, not the follow-up message, anchors synthesis;
- delegated target still receives the Phase 8 safe cross-Agent envelope;
- specialist clarification skips synthesis;
- delegate without prior result skips synthesis;
- prior unresolved clarification wins without a synthesis-model call.

### Step 3 CI result

At implementation head:

~~~text
Ruff                           passed
Migration / DB contract        passed
Backend                        506 passed
Frontend Typecheck             passed
Frontend                       30 passed
Production build               passed
Production configuration       passed
~~~

## Local Step 3 gate

After pulling the latest Phase 9 branch:

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull
~~~

Run the focused Step 3 gate:

~~~powershell
uv run ruff check .

uv run pytest -v `
  tests/test_orchestration_synthesis_graph.py `
  tests/test_orchestration_execution_graph.py `
  tests/test_orchestration_graph.py `
  tests/test_orchestration_synthesis.py `
  tests/test_orchestration_execution.py `
  tests/test_orchestration_envelope.py
~~~

Then verify the Phase 8 production path remains unchanged:

~~~powershell
uv run pytest -v `
  tests/test_auto_orchestration.py `
  tests/test_auto_chat_api.py `
  tests/test_orchestration_evaluation.py
~~~

Finally run the complete project gate:

~~~powershell
uv run pytest -v

cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

### Step 3 acceptance boundary

Step 3 is accepted when:

- direct remains synthesis-free;
- clarification remains higher priority than specialist/synthesis work;
- delegation still uses the Phase 8 allowlisted envelope;
- synthesis receives only attributed public specialist results;
- the original query and explicit user observations retain provenance;
- the full backend suite passes;
- existing `/chat/auto` behavior remains unchanged;
- frontend regression gates remain green.

Only after this local gate should Step 4 introduce LangGraph durable checkpoint/resume.
## Step 4 — Durable Checkpoint / Resume

### Scope

Step 4 gives the Phase 9 shadow workflow a real LangGraph checkpointer boundary. A workflow
can now persist after a completed node, stop before later work, and resume from the same
`thread_id` without re-running the already completed decision or specialist nodes.

Added:

~~~text
src/docker_agent/orchestration/checkpoint.py
src/docker_agent/orchestration/checkpoint_graph.py
tests/test_orchestration_checkpoint.py
scripts/setup_orchestration_checkpoints.py
~~~

The project also adds:

~~~text
langgraph-checkpoint-postgres>=3.1.2,<4.0.0
~~~

for production PostgreSQL-backed persistence.

### Checkpointed graph topology

The Step 4 graph preserves the Step 3 routing rules:

~~~text
START
  ↓
decision
  ├──────── clarify ─────────────────────────────→ END
  │
  ├──────── direct ────→ specialist ─→ complete ─→ END
  │
  └──────── delegate ─→ specialist
                            │
                            ├─ clarification/no prior ─→ complete ─→ END
                            │
                            └─ prior + current public results
                                      ↓
                                  synthesis ─────────────→ END
~~~

but it is compiled with a LangGraph `BaseCheckpointSaver`.

For a delegated flow, an operator/test can interrupt before synthesis:

~~~text
decision
  ↓
specialist
  ↓
[checkpoint persisted]
  ↓
PAUSED before synthesis
~~~

and later resume the same thread:

~~~text
same thread_id
  ↓
restore checkpoint
  ↓
synthesis
  ↓
END
~~~

The resume path does not call the decision model again and does not execute the specialist
again.

### Public-only durable state

Step 4 intentionally uses a separate `OrchestrationCheckpointGraphState` instead of
checkpointing the Step 2/3 raw execution object.

Persisted orchestration state contains:

~~~text
question
DelegationContext
source_agent_type
explicit_user_clarification
explicit user_observations
prior SpecialistResultEnvelope
validated OrchestrationDecision
current SpecialistResultEnvelope
public OrchestratedSynthesisResult
final answer / clarification
bounded workflow trace
~~~

It deliberately does **not** contain:

~~~text
OrchestrationExecutionResult.turn
raw specialist turn objects
raw tool output
worker state
system prompts
credentials
hidden Agent state
~~~

This means the durable checkpoint boundary is narrower than the in-process execution boundary.

### Thread contract

Every checkpointed orchestration run requires a non-empty LangGraph `thread_id`.

A new run refuses to start on a thread that already contains orchestration state. Completed
threads also refuse `resume`, while paused threads expose their pending node names.

The top-level graph uses LangGraph's empty `checkpoint_ns`. Step 4 originally tested a custom
business namespace, but LangGraph 1.2 interprets a non-empty checkpoint namespace as a
subgraph namespace when reading state. Isolation therefore remains keyed by `thread_id`,
which is the intended top-level checkpoint contract.

### PostgreSQL production adapter

`open_postgres_orchestration_checkpointer(...)` converts the existing SQLAlchemy-style
`postgresql+psycopg://...` DATABASE_URL into a psycopg PostgreSQL URI and opens the connection
with:

~~~text
autocommit = true
row_factory = dict_row
~~~

The adapter uses `PostgresSaver`, matching LangGraph's production checkpoint backend.

Checkpoint schema setup is explicit rather than hidden in API startup:

~~~powershell
uv run python scripts/setup_orchestration_checkpoints.py
~~~

This calls `PostgresSaver.setup()` and should be run as a deployment/setup operation when the
checkpoint tables are first introduced or when the checkpointer package requires migrations.

### Checkpoint deserialization safety

The PostgreSQL adapter does not rely on permissive default deserialization.

`JsonPlusSerializer` is configured with:

~~~text
pickle_fallback = false
explicit allowed_msgpack_modules/types only
~~~

The allowlist is restricted to the small public orchestration contracts required by durable
state:

~~~text
AgentHandoff
DelegationContext
OrchestrationDecision
SpecialistResultEnvelope
OrchestratedSynthesisResult
~~~

This reduces the checkpoint deserialization surface if the checkpoint database is ever
compromised.

### Resume semantics

The checkpoint runner exposes:

~~~python
start_checkpointed_orchestration(...)
read_checkpointed_orchestration(...)
resume_checkpointed_orchestration(...)
~~~

Runs use `durability="sync"` so checkpoint writes are persisted before the graph proceeds to
the next step.

A paused result includes:

~~~text
completed = false
next_nodes = ("synthesis",)
public current SpecialistResultEnvelope
trace = ("decision", "delegate", "specialist")
~~~

After resume:

~~~text
completed = true
next_nodes = ()
final synthesis result
trace = ("decision", "delegate", "specialist", "synthesis")
~~~

Checkpoint list/tuple serialization differences are normalized at the read boundary so public
result contracts remain immutable tuples.

### Step 4 coverage

Dedicated coverage verifies:

- pause before synthesis persists a pending synthesis node;
- resume uses the same thread and completes synthesis;
- decision-model call count does not increase after resume;
- specialist execution count does not increase after resume;
- synthesis executes exactly once after resume;
- a newly compiled graph can read/resume state from the same saver;
- checkpoint state contains the public SpecialistResultEnvelope and not raw execution/turn state;
- completed threads cannot be resumed;
- an existing thread cannot be silently restarted;
- PostgreSQL URL normalization;
- required thread configuration and top-level namespace behavior;
- strict serializer round-trip for allowlisted public state;
- PostgreSQL adapter uses autocommit, dict-row access, explicit setup, and closes connections.

### Product boundary

Step 4 remains **shadow-only**. It does not change:

~~~text
POST /chat
POST /chat/auto
AutoOrchestrationService
Web UI
normal conversation persistence
~~~

LangGraph checkpoint tables are separate workflow-state infrastructure. They do not replace
the existing application Conversation / Message / AgentExecution persistence model.

### Step 4 CI result

At implementation head:

~~~text
Ruff                           passed
Migration / DB contract        passed
Backend                        513 passed
Frontend Typecheck             passed
Frontend                       30 passed
Production build               passed
Production configuration       passed
~~~

## Local Step 4 gate

After pulling the latest Phase 9 branch, dependency sync matters because Step 4 adds the
PostgreSQL checkpoint package:

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull

uv sync --all-groups
~~~

Run the deterministic checkpoint/resume gate first:

~~~powershell
uv run ruff check .

uv run pytest -v `
  tests/test_orchestration_checkpoint.py `
  tests/test_orchestration_synthesis_graph.py `
  tests/test_orchestration_execution_graph.py `
  tests/test_orchestration_graph.py
~~~

Then run the Phase 8/9 regression set:

~~~powershell
uv run pytest -v `
  tests/test_orchestration_execution.py `
  tests/test_orchestration_envelope.py `
  tests/test_orchestration_synthesis.py `
  tests/test_auto_orchestration.py `
  tests/test_auto_chat_api.py `
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

If your normal local PostgreSQL database is running and already at the application migration
head, also run the production-backend setup smoke check:

~~~powershell
uv run python scripts/setup_orchestration_checkpoints.py
~~~

Expected output:

~~~text
LangGraph orchestration checkpoint tables are ready.
~~~

The setup command is optional for the deterministic unit gate but required before a future
production cutover to PostgreSQL-backed checkpointing.

### Step 4 acceptance boundary

Step 4 is accepted when:

- deterministic pause/resume tests pass;
- resume does not re-run decision or specialist work;
- only public orchestration state crosses the durable boundary;
- PostgreSQL adapter/security contracts pass;
- the complete backend suite passes;
- existing `/chat/auto` remains unchanged;
- frontend regression gates remain green;
- optional local PostgreSQL setup succeeds when the database is available.

Only after this local gate should Step 5 add a user-visible/human-approval interrupt boundary.
## Step 5 — Human Approval / Interrupt Boundary

### Scope

Step 5 adds a real LangGraph `interrupt(...)` Human-in-the-loop boundary on top of the
Step 4 durable checkpoint graph.

The approval flow remains shadow-only and does not replace `/chat/auto` yet.

Added:

~~~text
src/docker_agent/orchestration/approval.py
src/docker_agent/orchestration/approval_graph.py
tests/test_orchestration_approval.py
~~~

### Approval policy

Approval is policy-driven rather than forced on every request.

Default policy:

~~~text
clarify         → never requires approval
direct          → no approval by default
delegate        → approval required by default
~~~

The policy can also require approval for specific capabilities:

~~~python
HumanApprovalPolicy(
    required_actions=frozenset(),
    required_capabilities=frozenset({"runtime_diagnostics"}),
)
~~~

This gives the platform a reusable boundary for future write-capabilities or higher-risk
tools without changing the graph topology.

### Human-in-the-loop topology

The Step 5 graph is:

~~~text
START
  ↓
decision
  ├──────── clarify ─────────────────────────────────────────→ END
  │
  └──────── direct/delegate
                ↓
           approval_gate
                │
                ├─ not required ───────────────→ specialist
                │
                └─ required
                      ↓
                  approval
                      ↓
                 interrupt(...)
                      ↓
                 durable pause
                    /     \
                   /       \
              approved     denied
                 ↓           ↓
            specialist   approval_denied
                 ↓           ↓
          complete/synthesis END
~~~

The interrupt is emitted **before** any specialist execution.

### Interrupt request

The value surfaced to the caller is a bounded public object:

~~~text
kind = orchestration_approval
action
source_agent_type
target_agent_type
capability
reason
question
~~~

`reason` is capped at 500 characters and `question` at 1000 characters.

For compatibility with the full supported LangGraph range, including 1.2.11, the application
owns the response schema instead of passing a `response_schema=` keyword to `interrupt()`.

The interrupt value therefore includes:

~~~text
response_schema:
  type: object
  required: [approved]
  properties:
    approved: boolean
    comment: string
~~~

The public read result exposes both this stable application schema and the LangGraph interrupt
id through `HumanApprovalRequest`, so a future API/UI can render a real approval card without
depending on version-specific interrupt metadata.

### Resume contract

Approval resumes through the single-interrupt compatible LangGraph
`Command(resume=response)` form. The pending interrupt id remains exposed for correlation and
future API/UI use, but resume does not depend on newer id-addressed resume syntax.

The helper is:

~~~python
resume_human_approval_orchestration(
    graph,
    thread_id=thread_id,
    approved=True,
    comment="允许继续执行。",
)
~~~

Because the approval node is restarted by LangGraph on resume, it performs no side effects
before calling `interrupt(...)`. Specialist execution only occurs after an approved response
has been returned from the interrupt.

### Approval result states

The durable state uses:

~~~text
not_required
pending
approved
denied
~~~

Pending:

~~~text
completed = false
next_nodes = ("approval",)
approval_status = pending
approval_request = HumanApprovalRequest(...)
specialist calls = 0
~~~

Approved:

~~~text
approval_status = approved
approval_request = None
specialist executes exactly once
workflow continues to complete/synthesis
~~~

Denied:

~~~text
approval_status = denied
specialist calls = 0
synthesis calls = 0
final answer = 操作未获批准，工作流已停止执行。
~~~

### Fast-path preservation

A normal direct read-only request still avoids the approval interrupt:

~~~text
decision
  ↓
approval_skipped
  ↓
specialist
  ↓
complete
~~~

This keeps the Phase 8/9 latency principle intact: Human approval is introduced only where
policy requires it.

### Durable safety boundary

Step 5 continues to checkpoint only the public orchestration state from Step 4.

Approval adds only primitive durable fields:

~~~text
approval_status
approval_comment
~~~

The approval request itself is surfaced through the LangGraph interrupt snapshot and does not
introduce raw specialist/tool state into the checkpoint.

### Step 5 coverage

Dedicated tests verify:

- default delegate pauses before any specialist execution;
- pending interrupt exposes target Agent/capability and the stable application response schema;
- approval resumes the same thread using the single-interrupt `Command(resume=response)` form;
- the interrupt call remains compatible with the LangGraph 1.2.11 one-value signature;
- approved resume does not rerun the decision model;
- approved resume executes the target specialist exactly once;
- delegated approved flow can continue into synthesis exactly once;
- denial executes zero specialists and zero synthesis calls;
- direct read-only requests skip approval by default;
- capability policy can require approval for direct runtime diagnostics;
- clarification bypasses the approval gate;
- completed/non-interrupted threads cannot be approval-resumed;
- invalid approval policy configuration is rejected.

### Product boundary

Step 5 is still **shadow-only**.

It does not change:

~~~text
POST /chat
POST /chat/auto
AutoOrchestrationService
Web UI
conversation persistence
~~~

The approval request/result contracts are intentionally backend-first so Step 6 can add shadow
comparison and then expose the approval state to the Chinese Web UI during product cutover.

### Step 5 CI result

At implementation head:

~~~text
Ruff                           passed
Migration / DB contract        passed
Backend                        522 passed
Frontend Typecheck             passed
Frontend                       30 passed
Production build               passed
Production configuration       passed
~~~

## Local Step 5 gate

After pulling the latest Phase 9 branch:

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull

uv sync --all-groups
~~~

Run the focused Human-in-the-loop gate:

~~~powershell
uv run ruff check .

uv run pytest -v `
  tests/test_orchestration_approval.py `
  tests/test_orchestration_checkpoint.py `
  tests/test_orchestration_synthesis_graph.py `
  tests/test_orchestration_execution_graph.py `
  tests/test_orchestration_graph.py
~~~

Then verify the Phase 8 product path remains unchanged:

~~~powershell
uv run pytest -v `
  tests/test_auto_orchestration.py `
  tests/test_auto_chat_api.py `
  tests/test_orchestration_execution.py `
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

Expected full local results:

~~~text
backend: 522 passed
frontend: 30 passed
production build: passed
~~~

If PostgreSQL checkpoint tables were already initialized during Step 4, no additional schema
setup is required for Step 5.

### Step 5 acceptance boundary

Step 5 is accepted when:

- approval pauses durably before specialist execution;
- approval uses LangGraph interrupt/Command resume semantics;
- approved resume does not duplicate prior work;
- denied approval executes no specialist or synthesis work;
- direct fast paths remain approval-free unless policy explicitly gates the capability;
- checkpoint state remains public-only;
- full backend/frontend gates pass;
- existing `/chat/auto` behavior remains unchanged.

Only after this local gate should Step 6 compare the Phase 8 service path and the Phase 9
LangGraph path in shadow mode before product cutover.

### LangGraph 1.2.11 compatibility correction

Local Step 5 testing exposed an API compatibility issue that CI did not initially reveal:
the project allows `langgraph>=1.2.11`, while the newer `interrupt(..., response_schema=...)`
keyword is not available in every allowed version.

Step 5 therefore intentionally uses the common baseline API:

~~~python
response = interrupt(approval_request_payload(...))
...
graph.invoke(Command(resume=response), config)
~~~

The approval form schema is embedded in the application-owned interrupt payload and parsed into
`HumanApprovalRequest.response_schema`.

This keeps the Human-in-the-loop contract stable across the supported LangGraph range rather
than forcing local environments to upgrade to a newer minor release.
## Step 6A — Auto Chat Shadow Parity

### Scope

Step 6 is split into two release-safe parts:

~~~text
6A  Product-compatible LangGraph adapter + shadow parity   ✅
6B  /chat/auto cutover + approval UI                       ⏳
~~~

Step 6A does **not** change production traffic. The existing Phase 8
`AutoOrchestrationService` remains the `/chat/auto` runtime until 6B.

Added:

~~~text
LangGraphAutoOrchestrationService
src/docker_agent/orchestration/parity.py
tests/test_auto_orchestration_parity.py
~~~

### Product-compatible LangGraph adapter

`LangGraphAutoOrchestrationService` implements the same public `chat(...)` contract as the
Phase 8 service while using the Step 3 LangGraph synthesis graph internally.

It intentionally reuses the existing Auto conversation behavior:

- auto conversation creation and validation;
- bounded recent-history rendering;
- previous specialist owner/result restoration;
- original-query recovery;
- explicit user-observation extraction;
- existing message/execution persistence;
- existing route names and Chinese trace labels.

Therefore the candidate path can be compared without introducing a second product API.

### Observable parity contract

The comparison layer projects each turn into an
`AutoOrchestrationParitySnapshot` containing:

~~~text
route
current_agent_type
needs_clarification
synthesized
answer_present
clarification_present
trace_stages
trace_agents
specialist_agents
~~~

`compare_auto_orchestration_turns(...)` returns the baseline snapshot, candidate snapshot,
and field-level mismatches. `gate_passed` is true only when the structural product contract
matches.

The comparator deliberately does not make model-generated prose equality the core release
gate. Deterministic tests additionally assert exact answer/clarification equality where both
paths use identical fixture responses.

### Shadow safety model

Step 6A does not dual-execute Phase 8 and Phase 9 against real production specialists.

Doing that for every request would:

- double model/tool latency;
- potentially execute runtime tools twice;
- duplicate future write-side effects;
- distort call-budget measurements.

Instead, shadow parity uses isolated deterministic runtimes with the same model decisions and
specialist outputs. This validates orchestration topology and product semantics without
duplicating real side effects.

A future live shadow signal, if added, must be decision-only or otherwise explicitly
side-effect-free.

### Covered parity scenarios

The Step 6A gate verifies:

- direct Docker specialist flow;
- orchestration clarification with zero specialist calls;
- two-turn direct → delegate → cross-Agent synthesis;
- specialist-generated clarification;
- recent conversation context parity;
- target specialist envelope parity;
- decision-model call-count parity;
- synthesis-model call-count parity;
- explicit mismatch detection when baseline/candidate behavior diverges.

The two-turn handoff test compares independent Phase 8 and Phase 9 conversations and confirms
that both recover the same previous specialist state even though their conversation IDs differ.

### Step 6A CI result

At implementation head:

~~~text
Ruff                           passed
Migration / DB contract        passed
Backend                        528 passed
Frontend Typecheck             passed
Frontend                       30 passed
Production build               passed
Production configuration       passed
~~~

### Product boundary after 6A

Production remains:

~~~text
POST /chat/auto
    ↓
AutoOrchestrationService (Phase 8)
~~~

Candidate remains:

~~~text
LangGraphAutoOrchestrationService
    ↓
run_orchestration_synthesis_graph(...)
~~~

Step 6B will switch the backend runtime only after this parity gate also passes locally.

## Local Step 6A gate

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull

uv sync --all-groups
uv run ruff check .

uv run pytest -v `
  tests/test_auto_orchestration_parity.py `
  tests/test_auto_orchestration.py `
  tests/test_auto_chat_api.py `
  tests/test_orchestration_synthesis_graph.py
~~~

Then run the complete project gate:

~~~powershell
uv run pytest -v

cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

Expected current full result:

~~~text
backend: 528 passed
frontend: 30 passed
production build: passed
~~~

### Step 6A acceptance boundary

6A is accepted when:

- all structural parity reports pass for matching scenarios;
- direct/clarify/delegate call budgets match;
- two-turn handoff state restoration matches;
- persistence-visible routes and traces match;
- the existing `/chat/auto` regression suite stays green;
- full backend/frontend gates pass.

Only after this local gate should Step 6B replace the Phase 8 `/chat/auto` runtime, expose
pending Human Approval state through the API, and add the Chinese approval UI.
## Step 6B — Product Cutover + Chinese Approval UI

### Runtime cutover

`POST /chat/auto` now uses:

~~~text
LangGraphProductAutoOrchestrationService
    ↓
HumanApprovalPolicy
    ↓
LangGraph durable approval graph
    ↓
PostgreSQL PostgresSaver
~~~

The Phase 8 `AutoOrchestrationService` and the Step 6A
`LangGraphAutoOrchestrationService` remain in the codebase as the baseline/parity reference,
but they no longer own the product `/chat/auto` endpoint.

### Product turn lifecycle

Direct fast path:

~~~text
user message
  ↓
decision
  ↓
approval policy: not required
  ↓
one specialist
  ↓
assistant answer
~~~

The user-visible trace stays concise and does not show a redundant 'approval skipped' step.

Delegate path:

~~~text
user message
  ↓
decision = delegate
  ↓
durable interrupt
  ↓
persist user message only
  ↓
return approval_status=pending
~~~

After approval:

~~~text
same conversation
same LangGraph thread
  ↓
Command(resume=...)
  ↓
target specialist executes once
  ↓
optional synthesis
  ↓
persist assistant message
~~~

After denial, no specialist or synthesis executes and the assistant records a short stop
message.

### Conversation/checkpoint identity

Approval threads are deterministic per Auto conversation turn:

~~~text
auto:<conversation_id>:turn:<user_turn_index>
~~~

The browser does not need to store the LangGraph thread id.

A pending Auto conversation has one unmatched latest user message. On reload, the backend uses
that durable conversation state to derive the pending turn thread and read the LangGraph
checkpoint.

This allows approval state to survive:

- browser refresh;
- frontend navigation;
- rebuilding the product service;
- backend process restart when PostgreSQL checkpoint storage remains available.

### Persistence semantics

A pending approval is **not** written as a fake assistant message.

Before approval:

~~~text
messages:
user
assistant
user  ← pending turn
~~~

After approval/denial:

~~~text
messages:
user
assistant
user
assistant
~~~

The approval request itself lives in the LangGraph interrupt/checkpoint and API response.

This prevents 'waiting for approval' text from contaminating recent conversation context and
future routing prompts.

### Approval API

Existing product endpoint:

~~~text
POST /chat/auto
~~~

can now return:

~~~text
route = auto_approval_pending
approval_status = pending
needs_approval = true
approval_request = {...}
~~~

Reload/recovery endpoint:

~~~text
GET /chat/auto/{conversation_id}/approval
~~~

returns the pending Auto turn or `null`.

Resume endpoint:

~~~text
POST /chat/auto/{conversation_id}/approval

{
  "approved": true | false,
  "comment": "optional bounded comment"
}
~~~

Checkpoint/PostgreSQL failures are mapped to HTTP 503 instead of leaking an internal 500.

### Chinese Web approval UI

The Auto chat page now renders a dedicated approval card when `needs_approval=true`.

It displays:

~~~text
需要你的批准

当前专家  →  下一位专家
转交原因
目标 capability
当前用户问题

[拒绝]  [允许继续]
~~~

While approval is pending:

- the composer is disabled;
- the send button displays `等待审批`;
- the right-hand orchestration status shows `等待批准`;
- the timeline includes an `人工审批` node;
- approval survives reopening the conversation.

The layout is responsive and becomes a vertical approval flow on narrow screens.

### Frontend state contract

`AutoChatResponse` now includes:

~~~text
approval_status
needs_approval
approval_request
~~~

The frontend never reads LangGraph checkpoint internals directly.

It uses only:

~~~text
getAutoApproval(conversationId)
resolveAutoApproval({ conversationId, approved, comment })
~~~

### Required checkpoint setup after cutover

Before Step 6B, PostgreSQL checkpoint setup was optional for the product path because Phase 9
was shadow-only.

After 6B it is required for Auto mode.

Before starting the cutover backend against a database for the first time, run:

~~~powershell
uv run python scripts/setup_orchestration_checkpoints.py
~~~

Expected:

~~~text
LangGraph orchestration checkpoint tables are ready.
~~~

This remains an explicit deployment/setup operation; API startup does not silently mutate
checkpoint schema.

### Step 6B coverage

Backend product tests verify:

- direct fast path completes with no pending approval;
- delegate persists only the user message before approval;
- target specialist is not called before approval;
- a new product-service instance recovers the same pending interrupt;
- approved resume does not repeat the decision;
- approved resume executes one target specialist and one synthesis;
- denied resume executes zero target specialists/synthesis calls;
- pending approval blocks a new user message;
- resolved conversations no longer report a pending approval.

API tests verify:

- `/chat/auto` pending response shape;
- approval request schema;
- pending-approval recovery endpoint;
- null response when no approval is pending;
- approval resume request/response contract.

Frontend tests verify:

- approval API serialization;
- workspace pending state;
- composer lock while pending;
- approval resolution;
- pending approval recovery when reopening history.

### Step 6B CI result

Implementation gate:

~~~text
Ruff                           passed
Migration / DB contract        passed
Backend                        537 passed
Frontend Typecheck             passed
Frontend                       33 passed
Production build               passed
Production configuration       passed
~~~

## Local Step 6B gate

~~~powershell
git fetch
git switch feat/upgrade-phase-9-langgraph-orchestration
git pull

uv sync --all-groups

# Required now that /chat/auto is on the durable graph
uv run python scripts/setup_orchestration_checkpoints.py

uv run ruff check .

uv run pytest -v `
  tests/test_auto_orchestration_cutover.py `
  tests/test_auto_chat_api.py `
  tests/test_auto_orchestration_parity.py `
  tests/test_orchestration_approval.py `
  tests/test_orchestration_checkpoint.py
~~~

Then:

~~~powershell
uv run pytest -v

cd web
npm run typecheck
npm test
npm run build
cd ..
~~~

Expected:

~~~text
backend: 537 passed
frontend: 33 passed
production build: passed
~~~

### Manual product acceptance

Start the backend and Web app using the project's normal local commands, then:

1. open a new `智能编排` conversation;
2. send a direct Docker/runtime question and confirm it returns normally with no approval card;
3. continue the same conversation with a service-level failure that routes from Docker Support
   to Infrastructure Troubleshooter;
4. confirm the UI shows the Chinese approval card before the target specialist runs;
5. refresh the browser and reopen the conversation; confirm the same approval is restored;
6. click `允许继续`; confirm the workflow resumes and produces the delegated/synthesized result;
7. repeat with another delegated flow and click `拒绝`; confirm no target-specialist result is
   produced and the conversation records the stop message.

### Step 6 acceptance boundary

Step 6 is accepted when both 6A and 6B gates pass locally and the manual approval flow works
through a real PostgreSQL checkpoint backend.

After that, Step 7 should add cutover-focused evaluation/operations coverage and close Phase 9.
