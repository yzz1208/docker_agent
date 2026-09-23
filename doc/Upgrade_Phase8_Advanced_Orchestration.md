# Upgrade Phase 8 — Advanced Multi-Agent Orchestration

## Goal

Phase 8 adds controlled cross-Agent orchestration on top of the Generic Multi-Agent Platform.

Phase 7 proved that multiple real Agents can coexist behind one Registry, Factory, Chat,
Configuration, Operations, and Evaluation surface.

Phase 8 addresses a different problem:

~~~text
User chooses one Agent manually
        ↓
single specialist handles the whole conversation
~~~

becomes, incrementally:

~~~text
platform orchestration
        ↓
capability discovery
        ↓
bounded delegation / handoff
        ↓
specialist execution
        ↓
cross-Agent trace
        ↓
optional synthesis
~~~

The migration remains conservative. Existing explicit Agent selection stays valid throughout
Phase 8.

## Safety and orchestration principles

Cross-Agent orchestration must remain:

- bounded by a maximum handoff count;
- acyclic by default;
- capability-aware;
- traceable;
- explicit about which Agent owns each step;
- unable to silently broaden tool permissions;
- backward-compatible with direct specialist Chat.

No Phase 8 step may imply that an Agent has tools or live access not declared in its
Descriptor.

## Step 1 — Capability Index and Delegation Contract

Create the platform primitives required before any automatic orchestration is allowed.

### Capability index

Added:

~~~text
AgentCapabilityIndex
~~~

It builds a deterministic index from the runtime Agent Registry.

Current examples:

~~~text
chat
    docker_support
    infrastructure_troubleshooter

runtime_diagnostics
    docker_support

incident_triage
    infrastructure_troubleshooter
~~~

Capability lookups normalize external forms such as:

~~~text
runtime-diagnostics
runtime_diagnostics
~~~

to the same canonical capability key.

The index supports:

~~~text
capabilities()
agents_for(capability)
supports(agent_type, capability)
~~~

This is discovery only. Step 1 does not automatically choose or invoke an Agent.

### Delegation trace

Added immutable orchestration metadata:

~~~text
DelegationContext
AgentHandoff
~~~

A context keeps:

~~~text
original_query
handoffs
hop_count
current_agent_type
visited_agents
~~~

Each handoff records:

~~~text
index
source_agent_type
target_agent_type
capability
reason
~~~

Agent identities are canonicalized through the Registry before being written to the trace.

The first delegation may originate from:

~~~text
source_agent_type = null
~~~

which represents a future platform-level dispatcher rather than a specialist Agent.

### Delegation policy

Added:

~~~text
DelegationPolicy
~~~

The policy validates a proposed handoff before it can be appended to the trace.

Default rules:

- maximum two handoffs;
- no self-delegation;
- no revisit of any source or target already present in the trace;
- target Agent must expose the requested capability;
- later handoffs must originate from the current Agent;
- delegation reason must be non-empty.

The hop limit is configurable when the policy is constructed.

Dedicated errors:

~~~text
DelegationPolicyError
DelegationCapabilityUnavailable
DelegationHopLimitExceeded
DelegationLoopDetected
DelegationSourceMismatch
~~~

### Candidate discovery

The policy can return capability candidates while excluding known Agent types:

~~~text
policy.candidates(
    "chat",
    exclude_agent_types=("docker_support",),
)
    ↓
infrastructure_troubleshooter
~~~

Candidate discovery does not rank or select a winner.

That decision is intentionally deferred to Step 2, where routing behavior can be evaluated
explicitly instead of hidden inside Step 1 infrastructure.

### Step 1 non-goals

Step 1 deliberately does **not**:

- alter POST /chat;
- automatically select an Agent;
- invoke AgentFactory;
- execute a handoff;
- synthesize multiple Agent answers;
- add an Auto Agent mode to Web;
- persist orchestration traces yet.

This keeps the platform behavior unchanged while establishing a safe contract for later
orchestration.

### Step 1 coverage

Tests cover:

- deterministic capability discovery;
- normalized capability lookup;
- capability support checks;
- canonical handoff trace construction;
- platform-originated first delegation;
- unsupported target capability rejection;
- self-delegation rejection;
- source/target loop detection;
- source continuity;
- maximum hop enforcement;
- candidate exclusion;
- empty query/reason rejection.

Focused gate:

~~~powershell
git switch feat/upgrade-phase-8-agent-orchestration
git pull

uv run ruff check .
uv run pytest -v tests/test_agent_delegation.py tests/test_agent_registry.py tests/test_agent_factory.py
~~~

Phase 7 regression sanity:

~~~powershell
uv run pytest -v tests/test_persistent_chat.py tests/test_chat_api.py tests/test_infrastructure_agent.py
~~~

## Step 2 — Orchestration Decision Model

Introduce a platform-level decision contract that can choose among:

~~~text
clarify
direct specialist
delegate specialist
~~~

The decision layer uses Agent Descriptor capabilities and produces structured,
validation-safe output.

### Step 2 implementation status

**IMPLEMENTED and CI-verified**

Added:

~~~text
src/docker_agent/orchestration/decision.py
tests/test_orchestration_decision.py
~~~

Core contract:

~~~text
OrchestrationDecisionModel
        ↓
OrchestrationDecision

action
reason
source_agent_type
target_agent_type
capability
clarification
~~~

Supported actions are:

~~~text
clarify
direct
delegate
~~~

`clarify` selects no Agent and requires a user-facing clarification question.

`direct` selects a registered specialist and one capability without creating a handoff. For
an initial platform dispatch, `source_agent_type` is null. If a current specialist already
owns the turn, `direct` may only keep that same Agent; it cannot silently switch ownership.

`delegate` is only valid when a current source Agent exists. The proposed target and
capability are validated through the Step 1 `DelegationPolicy`, including capability support,
source continuity, self-delegation protection, loop prevention, and hop limits.

The model prompt is built from the runtime Registry rather than hard-coded specialist names.
For each registered Agent it exposes only descriptor-backed identity, description,
capabilities, and declared toolsets. The prompt explicitly forbids inventing Agent types,
capabilities, permissions, tools, or live access.

The returned JSON contract is strict. Missing fields, unexpected fields, malformed JSON,
unknown Agent identities, unsupported capabilities, invalid direct switches, platform-level
fake delegation, and unsafe handoffs are rejected before any Agent execution can occur.

### Step 2 non-goals

Step 2 deliberately does **not**:

- change `POST /chat`;
- call `AgentFactory.get(...)`;
- invoke Docker Support or Infrastructure Troubleshooter;
- persist a delegation trace;
- execute the validated handoff;
- synthesize specialist answers;
- add Web Auto mode.

This preserves the Phase 8 boundary:

~~~text
user request
    ↓
orchestration decision
    ↓
validated intent only

NO specialist execution yet
~~~

### Step 2 coverage

Dedicated tests cover:

- initial direct routing to Docker Support for `runtime_diagnostics`;
- initial direct routing to Infrastructure Troubleshooter for `incident_triage`;
- platform clarification;
- keeping the current specialist with `direct`;
- validated Docker → Infrastructure delegation;
- canonical Agent/capability normalization;
- platform-originated fake delegation rejection;
- silent direct Agent-switch rejection;
- unsupported capability rejection;
- unknown Agent rejection;
- delegation trace loop protection;
- context-owner/source mismatch protection;
- strict missing/unexpected JSON field rejection;
- fenced JSON parsing;
- invalid JSON rejection before execution.

The full backend gate after Step 2 reports:

~~~text
431 passed, 1 warning
~~~

and includes Ruff plus the migration/database readiness contract.

## Step 3 — Delegation Execution Service

Connect validated delegation decisions to AgentFactory.

Targets:

- invoke one selected specialist;
- propagate bounded delegation context;
- keep direct specialist Chat compatible;
- preserve Agent identity in execution metadata;
- prevent recursive/unbounded Agent calls.

### Step 3 implementation status

**IMPLEMENTED and CI-verified**

Added:

~~~text
src/docker_agent/orchestration/execution.py
tests/test_orchestration_execution.py
~~~

Core execution path:

~~~text
OrchestrationDecision
        ↓
DelegationExecutionService
        ↓
defensive validation
        ↓
DelegationPolicy          (delegate only)
        ↓
AgentFactory.get(target)
        ↓
target Agent.handle(question)
        ↓
OrchestrationExecutionResult
~~~

The execution result preserves:

~~~text
decision
bounded DelegationContext
executed agent_type
specialist turn
~~~

`clarify` is execution-safe: it returns an execution result with no specialist turn and
does not access AgentFactory.

`direct` invokes exactly one selected specialist. Initial platform dispatch does not create
a handoff. A direct decision cannot silently change an existing source/context owner.

`delegate` revalidates the proposed handoff through `DelegationPolicy` immediately before
execution. Only after capability, source continuity, loop, and hop-limit checks succeed is
the target resolved through AgentFactory and invoked.

The specialist receives only the current user question at this stage. Step 3 does not pass
raw source-Agent state, prompts, tool output, or hidden runtime state across the Agent
boundary. The explicit cross-Agent result/context envelope remains Step 4 work.

### Execution safety boundary

The service intentionally performs at most one `Agent.handle(...)` call per `execute(...)`.
It does not inspect a specialist result and recursively re-run orchestration. Even when the
specialist itself asks for clarification, Step 3 returns that turn to the caller rather than
automatically selecting or invoking another Agent.

The execution layer also defensively rejects manually forged decisions before factory access,
including:

- unsupported orchestration actions;
- empty reasons;
- missing target/capability;
- target capability mismatches;
- direct cross-Agent switches;
- missing or mismatched context source identity;
- delegate loops;
- hop-limit violations;
- unknown Agent identities.

Specialist runtime failures are wrapped as `OrchestrationSpecialistExecutionError` with the
canonical target Agent identity while preserving the original exception as the cause.

### Compatibility

Step 3 does not modify `POST /chat`, `ChatSessionManager`, persistent direct conversations,
or the Web Agent selector. Existing explicit specialist Chat therefore remains the default
product behavior while the orchestration execution service is validated independently.

### Step 3 coverage

Dedicated tests cover:

- clarify-without-execution;
- initial direct specialist execution;
- continuing the current direct specialist;
- Docker Support → Infrastructure delegation;
- handoff trace creation before execution;
- loop rejection before factory access;
- hop-limit rejection before factory access;
- unsupported capability rejection;
- context owner/source enforcement;
- specialist failure wrapping;
- no recursive execution after a specialist clarification turn;
- unknown action rejection.

The full backend gate after Step 3 reports:

~~~text
442 passed, 1 warning
~~~

Ruff, migration/database readiness, frontend type checking, frontend unit tests, production
Web build, and production configuration validation also pass.

## Step 4 — Cross-Agent Context and Result Envelope

Define what information can cross an Agent boundary.

Targets:

- original user question;
- explicit user clarification;
- safe specialist result summary;
- source Agent;
- target Agent;
- capability/reason;
- no hidden prompt/tool state leakage.

### Step 4 implementation status

**IMPLEMENTED and CI-verified**

Added:

~~~text
src/docker_agent/orchestration/envelope.py
tests/test_orchestration_envelope.py
~~~

Step 3 execution now also produces and consumes the explicit envelope types:

~~~text
CrossAgentContextEnvelope
SpecialistResultEnvelope
~~~

### Cross-Agent request allowlist

A delegated specialist may receive only:

~~~text
original_query
current_user_message
explicit_user_clarification
source_agent_type
target_agent_type
capability
handoff_reason
handoff_index
prior_specialist_result
~~~

`prior_specialist_result`, when present, is itself restricted to:

~~~text
agent_type
route
reason
needs_clarification
clarification
bounded public answer summary
~~~

The source result must belong to the declared source Agent. Agent and capability identities
are canonicalized before the envelope is created.

### Public-result projection

`build_specialist_result_envelope(...)` projects an `AgentTurnProtocol` onto the public
cross-Agent contract. It reads only the specialist's public decision metadata, public final
answer, or public clarification.

It deliberately does not copy:

- system/model prompts;
- raw tool output;
- runtime/doc source objects;
- worker state;
- supervisor plans;
- hidden model state;
- credentials or secret configuration.

Public answer text is bounded before reuse across Agent boundaries. The current default
maximum is 4000 characters; longer specialist output is explicitly marked as truncated.

### Delegated target input

For `delegate`, `DelegationExecutionService` now renders the allowlisted envelope and passes
that rendered context to the target Agent. `direct` remains unchanged and still receives the
normal user question without a cross-Agent wrapper.

The rendered envelope explicitly labels transferred user/specialist text as **untrusted
data**, not platform instructions. It warns the target not to follow embedded instructions
that attempt to change its role, capabilities, tool access, or platform policy.

Execution therefore becomes:

~~~text
source decision
      ↓
DelegationPolicy
      ↓
CrossAgentContextEnvelope
      ↓
allowlisted + rendered transfer
      ↓
target Agent.handle(...)
      ↓
SpecialistResultEnvelope
~~~

Both `request_envelope` and `result_envelope` are exposed on
`OrchestrationExecutionResult`. A direct specialist has no request envelope but still
produces a public result envelope for later orchestration/synthesis.

### Compatibility and non-goals

Step 4 still does **not**:

- change `POST /chat` or Web behavior;
- persist orchestration envelopes yet;
- expose raw specialist evidence across Agents;
- recursively invoke another specialist from a result;
- synthesize multiple specialist results into one final answer.

Those responsibilities remain separated so Step 5 can consume a stable, inspectable public
result contract instead of arbitrary Agent internals.

### Step 4 coverage

Coverage now verifies:

- direct execution remains unwrapped;
- delegate execution receives the allowlisted context envelope;
- explicit user clarification crosses the boundary only as explicit data;
- prior specialist result ownership must match the source Agent;
- private prompt/tool/worker/source sentinel data is excluded from public envelopes;
- completed specialist answer projection;
- clarification-only result projection;
- bounded/truncated public summaries;
- canonical Agent and capability identities;
- prompt-injection boundary instructions on transferred context;
- compatibility with the real Infrastructure Troubleshooter target Agent.

The full backend gate after Step 4 reports:

~~~text
452 passed, 1 warning
~~~

Ruff, migration/database readiness, frontend type checking, frontend unit tests, production
Web build, and production configuration validation also pass.

## Step 5 — Orchestrated Synthesis

Allow one bounded orchestration flow to combine specialist results where a single specialist
is insufficient.

The synthesis layer distinguishes user-reported observations, attributed specialist claims,
synthesis-level hypotheses, and unresolved uncertainty.

### Step 5 implementation status

**IMPLEMENTED and CI-verified**

Added:

~~~text
src/docker_agent/orchestration/synthesis.py
tests/test_orchestration_synthesis.py
~~~

Core flow:

~~~text
OrchestrationExecutionResult(s)
        ↓
public SpecialistResultEnvelope(s)
        ↓
OrchestratedSynthesisService
        ↓
strict synthesis JSON
        ↓
OrchestratedSynthesisResult
~~~

The service accepts either explicit `SpecialistResultEnvelope` values or completed
`OrchestrationExecutionResult` values through `synthesize_executions(...)`. Executions with
no public specialist result are rejected before synthesis.

### Provenance model

Step 5 deliberately keeps provenance outside model-authored fields.

`OrchestratedSynthesisResult` preserves:

~~~text
original_query
user_observations
specialist_results
answer
hypotheses
unresolved_uncertainties
clarification_questions
contributing_agents
~~~

`user_observations` are supplied explicitly by the orchestration caller and are preserved
unchanged except for whitespace normalization/deduplication. The synthesis model does not
create or rewrite this provenance list.

`specialist_results` are the Step 4 public result envelopes and remain attributed to their
canonical `agent_type`. They are not promoted to user-observed facts.

The model is allowed to author only:

~~~text
answer
hypotheses
unresolved_uncertainties
~~~

This prevents a model-authored JSON response from manufacturing a new `user_observations`
or `specialist_results` section and presenting it as platform provenance.

### Clarification precedence

If any specialist result still requires clarification, synthesis stops before the model call.
The unique clarification questions are returned deterministically:

~~~text
pending specialist clarification
        ↓
NO synthesis model call
        ↓
clarification_questions
~~~

In this state the result cannot contain an answer, hypotheses, or unresolved uncertainty.
Conversely, a completed synthesis must contain a non-empty answer. These invariants are
enforced on `OrchestratedSynthesisResult` itself.

### Synthesis safety rules

The synthesis prompt treats all transferred user and specialist text as untrusted data.
It explicitly requires:

- no invented user observations, runtime evidence, tool output, citations, or Agent results;
- no promotion of a specialist claim into a user-observed fact;
- Agent attribution for specialist claims;
- preservation of disagreement rather than fabricated consensus;
- no unsupported root-cause claims;
- explicit unresolved uncertainty instead of filling gaps with general knowledge;
- no tool or Agent invocation from the synthesis layer.

The synthesis layer consumes only Step 4 public envelopes. It has no access to raw tool
results, worker state, prompts, source objects, credentials, or hidden Agent state.

### Bounded synthesis

Default limits now include:

~~~text
specialist results              4
user observations              12
original query chars         4000
chars per user observation   2000
final answer chars           6000
hypotheses                      6
unresolved uncertainties        8
chars per list item          1200
~~~

All limits are configurable on `OrchestratedSynthesisService`, must be positive, and are
validated before or immediately after the model call.

The synthesis JSON schema is strict. Missing fields, unexpected fields, invalid JSON,
oversized output, and non-string list items are rejected.

### Compatibility and non-goals

Step 5 still does **not**:

- change `POST /chat`;
- enable automatic orchestration for normal Web conversations;
- persist the synthesis trace/result yet;
- recursively execute another Agent from synthesis;
- expose raw evidence from a specialist;
- add UI for handoffs or synthesis.

Those product-facing behaviors remain Step 6 work.

### Step 5 coverage

Dedicated coverage verifies:

- two-specialist synthesis;
- stable source Agent attribution;
- explicit user-observation provenance;
- untrusted specialist prompt-injection text;
- clarification short-circuit without a model call;
- clarification deduplication;
- direct collection from `OrchestrationExecutionResult` values;
- rejection of executions without a public result;
- duplicate Agent-result rejection;
- empty/missing specialist-result rejection;
- user-observation normalization/deduplication;
- code-fenced JSON parsing;
- missing/unexpected schema-field rejection;
- invalid JSON rejection;
- answer/list/query/context size bounds;
- contradictory terminal-state rejection.

The full backend gate after Step 5 reports:

~~~text
470 passed, 1 warning
~~~

Ruff, migration/database readiness, frontend type checking, frontend unit tests, production
Web build, and production configuration validation also pass.

## Step 6 — Web Auto-Orchestration Mode

Add an optional Web mode alongside explicit Agent selection.

The UI shows:

- selected/delegated Agent;
- handoff trace;
- capability/reason;
- current owner;
- direct-specialist mode remains available.

### Step 6 implementation status

**IMPLEMENTED and CI-verified**

Added the product Auto path:

~~~text
POST /chat/auto
        ↓
AutoOrchestrationService
        ↓
OrchestrationDecisionModel
        ↓
at most one specialist execution per user turn
        ↓
optional handoff synthesis
~~~

New backend/API files include:

~~~text
src/docker_agent/orchestration/auto_chat.py
src/docker_agent/api/orchestration.py
tests/test_auto_orchestration.py
tests/test_auto_chat_api.py
~~~

Manual specialist Chat remains on the existing `/chat` endpoint. Auto orchestration uses
`/chat/auto`, so the new product behavior does not hide orchestration behind the existing
manual workflow or change the semantics of direct specialist conversations.

### Low-latency execution policy

Step 6 is intentionally optimized for response speed rather than maximizing Agent count.

For a normal direct request:

~~~text
short orchestration decision
        ↓
one selected specialist
        ↓
return specialist result directly
~~~

There is **no synthesis model call** on this fast path.

For a later turn that requires a specialist change:

~~~text
short orchestration decision
        ↓
one delegated target specialist
        ↓
safe prior/current public results
        ↓
synthesis
~~~

Each user turn therefore executes at most one specialist. The system does not run Docker
Support and Infrastructure Troubleshooter in parallel just to demonstrate multi-Agent
behavior. Decision responses are capped to a small token budget, while synthesis is invoked
only when a real handoff has produced two relevant public specialist results.

Current orchestration model budgets are:

~~~text
decision model max tokens     320
synthesis model max tokens   1200
delegation max hops             2
~~~

### Durable Auto conversations

Auto conversations are stored with:

~~~text
agent_type = auto_orchestration
~~~

They reuse the existing conversation/message/execution persistence tables, so no database
migration is required. Auto conversations can be listed, reopened, renamed, and deleted like
manual conversations.

The safe orchestration trace and resumable public state are persisted inside the existing
`AgentExecution.worker_trace` JSON metadata. Persisted Auto state contains only canonical
current-Agent identity and the Step 4 public `SpecialistResultEnvelope`; it does not persist
raw prompts, raw tool output, or hidden specialist state.

Recent conversation context used for follow-up orchestration is bounded to a small number of
messages and characters and is explicitly marked as untrusted conversational data.

### Chinese product experience

The main Chat experience is now Chinese-first. The top navigation and backend-health labels
are also localized.

New-conversation mode selection is presented as a clear segmented control:

~~~text
手动专家 | 智能编排
~~~

Manual mode retains the explicit specialist selector. Auto mode displays the currently
selected specialist once one has been chosen. Existing conversations lock their mode so a
conversation cannot silently switch between manual and Auto semantics.

The Auto empty state explains three user-facing guarantees:

~~~text
快速判断   — 一次短路由决策
受控转交   — 每回合最多执行一个专家
清晰结果   — 事实、推测与不确定性分开
~~~

While a request is running the UI shows a compact `正在智能编排` state rather than exposing
internal model prompts or worker state.

The right-hand orchestration panel presents a visual timeline:

~~~text
智能判断
   ↓
专家处理
   ↓ optional
专家转交
   ↓ optional
综合结论
~~~

Each visible step shows only safe product metadata such as localized Agent name, capability,
and reason. Internal route names are localized for the Chat UI, and the public specialist
results are displayed separately from the final assistant message.

Agent names/capabilities used in the Chat experience are localized, including:

~~~text
Docker Support                  → Docker 支持
Infrastructure Troubleshooter  → 基础设施排障
runtime_diagnostics             → 运行时诊断
incident_triage                 → 故障分诊
~~~

### Step 6 tests

Coverage now verifies:

- direct Auto routing executes exactly one specialist;
- Auto clarification executes no specialist;
- a follow-up can hand off Docker Support → Infrastructure Troubleshooter;
- handoff synthesis uses only the safe prior specialist result;
- Auto conversations persist in normal conversation history;
- persisted Auto trace/current-owner state can be restored after reopening history;
- manual conversations cannot be passed into `/chat/auto`;
- bounded recent conversation context is marked as untrusted data;
- `/chat/auto` response headers and trace/result payloads;
- missing Auto conversations map to 404;
- the Web calls Auto and manual endpoints separately;
- Web mode switching and persisted Auto-history restoration;
- Chinese health/status labels;
- frontend type checking and production build.

Final Step 6 gate:

~~~text
backend: 477 passed, 1 warning
frontend: 30 passed
frontend production build: passed
~~~

Ruff, migration/database readiness, and production Compose validation also pass.

## Step 7 — Orchestration Evaluation and Closeout

Add evaluation datasets for:

- correct specialist selection;
- clarification vs delegation;
- loop/hop-limit protection;
- cross-Agent result quality;
- regression comparison.

Phase 8 is complete only when orchestration behavior is observable, bounded, evaluable, and
does not regress direct Agent workflows.

### Step 7 implementation status

**IMPLEMENTED and CI-verified**

Added:

~~~text
data/eval/orchestration_v1.jsonl
src/docker_agent/orchestration/evaluation.py
scripts/eval_orchestration.py
tests/test_orchestration_evaluation.py
~~~

The generic evaluation comparison layer was also extended to understand orchestration
behavior and model-call budgets.

### Evaluation dataset

The initial benchmark contains 17 cases covering:

~~~text
selection
clarification
delegation
safety_guard
loop_protection
hop_limit
cross_agent_quality
~~~

Decision cases cover Docker documentation/runtime selection, Infrastructure incident and
hypothesis selection, vague requests that must clarify, keeping an existing specialist, and
both Docker → Infrastructure and Infrastructure → Docker handoffs.

Deterministic guard cases validate rejection of platform-originated fake delegation,
self-delegation, Agent revisit loops, handoffs above max_hops, and capability escalation to
a target that does not expose the requested capability.

Cross-Agent synthesis cases use only public SpecialistResultEnvelope values and cover
two-Agent synthesis, unresolved/conflicting specialist conclusions, and clarification
precedence.

The dataset itself is CI-validated for unique IDs, schema shape, and required Step 7
coverage categories.

### Evaluation metrics

Decision/guard metrics:

~~~text
safe_decision_rate
action_accuracy
specialist_selection_accuracy
capability_accuracy
clarification_accuracy
safety_block_accuracy
exact_match_accuracy
~~~

Synthesis metrics:

~~~text
safe_synthesis_rate
contributing_agents_accuracy
answer_presence_accuracy
clarification_accuracy
uncertainty_accuracy
exact_match_accuracy
~~~

Metrics are also summarized by category so aggregate accuracy cannot hide a handoff, loop,
clarification, or synthesis regression.

### Performance and call-budget observability

The runner records per case:

~~~text
latency_ms
model_call_count
latency_budget_match
~~~

and aggregates average/P95 latency, total model calls, average calls per case, and
latency_budget_pass_rate.

Raw millisecond latency is observable but is not compared directly by the generic absolute
quality-regression threshold. Instead, latency enters the gate through the normalized
latency_budget_pass_rate. Default operator-run budgets are 8000 ms for decisions and
12000 ms for synthesis, and both are configurable.

Model-call counts are lower-is-better regression metrics, so accidental extra model calls
can fail a baseline/candidate comparison.

### Safe evaluation boundary

scripts/eval_orchestration.py intentionally does not execute specialist Agents or Docker
tools. It evaluates the real orchestration decision model, deterministic policy guards, and
the real synthesis model over public specialist envelopes.

This keeps the orchestration benchmark safe while existing specialist evaluation suites and
the full regression suite continue to cover Docker and Infrastructure Agent behavior.

### Running the benchmark

~~~powershell
uv run python scripts/eval_orchestration.py `
  --repeats 3 `
  --persist `
  --summary-output reports/orchestration_eval_summary.json
~~~

A smaller smoke run can use:

~~~powershell
uv run python scripts/eval_orchestration.py --limit 5
~~~

Persisted runs use:

~~~text
suite = orchestration
agent_type = auto_orchestration
dataset = orchestration_v1.jsonl
dataset_version = sha256:<content hash>
~~~

They also persist the git revision, sanitized model/config snapshot, aggregate metrics,
per-case expected/actual behavior, and per-case performance metrics.

### Baseline / candidate regression gate

After persisting a known-good baseline and a candidate:

~~~powershell
uv run python scripts/compare_evaluations.py `
  --baseline <baseline-run-id> `
  --candidate <candidate-run-id> `
  --max-regression 0.02 `
  --output reports/orchestration_comparison.json
~~~

For orchestration runs, behavior comparison now recognizes action, target_agent_type,
capability, current_agent_type, needs_clarification, synthesized, and contributing_agents.

model_call_count and average_model_calls_per_case are compared as lower-is-better metrics.
A new case failure, quality regression beyond threshold, call-budget regression, or case-set
mismatch prevents the comparison gate from passing.

### CI versus live-model evaluation

The provider-backed benchmark is intentionally operator-run rather than part of normal CI,
because an external model call would make CI nondeterministic. CI verifies the deterministic
evaluation contracts, dataset coverage, safety scoring, synthesis provenance scoring,
orchestration behavior comparison, call-budget comparison, full backend regressions,
frontend regressions, and production build.

### Step 7 final gate

~~~text
backend: 485 passed, 1 warning
frontend: 30 passed
frontend production build: passed
Ruff: passed
migration/database readiness: passed
production configuration validation: passed
~~~

Direct specialist Chat remains covered by the full regression suite.

## Phase 8 closeout

Phase 8 is now **COMPLETE**.

The platform now supports:

~~~text
Registry-backed capability discovery
        ↓
strict orchestration decision
        ↓
bounded / acyclic delegation
        ↓
one specialist execution per orchestration step
        ↓
allowlisted cross-Agent context/result envelope
        ↓
optional provenance-safe synthesis
        ↓
Chinese Auto-Orchestration Web mode
        ↓
durable trace/history
        ↓
evaluation dataset + regression gate
~~~

The original manual workflow remains backward-compatible:

~~~text
POST /chat       → explicit specialist
POST /chat/auto  → platform orchestration
~~~

Phase 8 does not turn every request into a multi-Agent workflow. The intended behavior
remains latency-conscious: direct when one specialist is sufficient, clarify when required
information is missing, delegate only when ownership should change, and synthesize only
when multiple public specialist results are materially useful.
