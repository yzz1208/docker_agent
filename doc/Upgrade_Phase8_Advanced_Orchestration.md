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

## Step 5 — Orchestrated Synthesis

Allow one bounded orchestration flow to combine specialist results where a single specialist
is insufficient.

The synthesis layer must distinguish observed facts, specialist claims, and unresolved
uncertainty.

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
