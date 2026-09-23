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

The UI should show:

- selected/delegated Agent;
- handoff trace;
- capability/reason;
- current owner;
- direct-specialist mode remains available.

## Step 7 — Orchestration Evaluation and Closeout

Add evaluation datasets for:

- correct specialist selection;
- clarification vs delegation;
- loop/hop-limit protection;
- cross-Agent result quality;
- regression comparison.

Phase 8 is complete only when orchestration behavior is observable, bounded, evaluable, and
does not regress direct Agent workflows.
