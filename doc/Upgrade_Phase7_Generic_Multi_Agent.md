# Upgrade Phase 7 — Generic Multi-Agent Platform

## Goal

Phase 7 turns the current Docker Support product into a reusable Agent platform without
discarding the working Docker Support Agent.

The migration strategy is incremental:

~~~text
working Docker Support Agent
        ↓
Agent Registry / Descriptor
        ↓
runtime Agent factory
        ↓
Agent-aware Chat sessions
        ↓
generic configuration schema
        ↓
second real Agent implementation
        ↓
Web Agent selector
        ↓
cross-Agent Operations
~~~

Existing Docker Support behavior remains the compatibility baseline.

## Step 1 — Agent Registry and Descriptor

Create one authoritative runtime catalog for supported Agent types.

Each descriptor exposes:

~~~text
agent_type
display_name
description
capabilities
knowledge_sources
toolsets
worker_roles
configuration_groups
default_enabled
~~~

The first registered Agent remains:

~~~text
docker_support
~~~

No second Agent is introduced in Step 1.

The registry must provide:

- normalized lookup by `agent_type`;
- deterministic listing;
- duplicate-registration rejection;
- unknown-Agent errors;
- immutable descriptor metadata.

Public read-only API:

~~~text
GET /agents
GET /agents/{agent_type}
~~~

The Registry becomes the authority for runtime-supported Agent types. Persistence may still
contain configuration records that are not runtime-registered, so stored configuration and
runtime capability remain separate concepts.

### Step 1 implementation status

**IMPLEMENTED pending local gate**

Added runtime registry primitives:

~~~text
AgentDescriptor
AgentRegistry
AgentAlreadyRegistered
AgentNotRegistered
AgentRegistryError
DOCKER_SUPPORT_DESCRIPTOR
build_agent_registry()
~~~

The Docker Support descriptor currently declares:

~~~text
agent_type
    docker_support

capabilities
    chat
    documentation_qa
    runtime_diagnostics
    multi_agent_supervision

knowledge_sources
    docker_docs

toolsets
    docker_read_only

worker_roles
    knowledge
    runtime
    diagnosis

configuration_groups
    model_settings
    retrieval_settings
    runtime_settings
~~~

The registry normalizes external lookup values such as:

~~~text
Docker-Support
docker_support
  docker-support
~~~

to the canonical:

~~~text
docker_support
~~~

while descriptor registration itself requires an already canonical Agent type.

### Runtime catalog API

Read-only Agent catalog endpoints:

~~~text
GET /agents
GET /agents/{agent_type}
~~~

Unknown runtime Agent types return HTTP 404 from the catalog.

The existing effective-configuration endpoint now asks the Registry whether an Agent type is
runtime-supported before resolving it.

Persisted configuration remains a separate concept: the persistence layer may contain a
future/unregistered Agent configuration without implying that the current process can run
that Agent.

### Shared identity

The Docker Support default display name is now sourced from:

~~~text
DOCKER_SUPPORT_DESCRIPTOR
~~~

rather than duplicated inside the configuration resolver.

The existing Chat flow still defaults to Docker Support in Step 1. Dynamic Agent selection
is intentionally deferred to Step 2/3.

### Web contract preparation

The Web API layer now contains:

~~~text
AgentDescriptor
listAgents()
getAgentDescriptor()
~~~

Development Vite and production Nginx both proxy:

~~~text
/agents
/agents/{agent_type}
~~~

No Agent Selector UI is added in Step 1.

### Step 1 coverage

Tests cover:

- default Docker Support descriptor metadata;
- normalized registry lookup;
- deterministic registry listing;
- duplicate registration rejection;
- unknown Agent lookup;
- descriptor canonical-type validation;
- duplicate descriptor metadata rejection;
- `GET /agents`;
- normalized `GET /agents/{agent_type}`;
- unknown Agent HTTP 404;
- Web Agent API serialization;
- production Nginx Agent API proxy contract.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_agent_registry.py tests/test_agents_api.py tests/test_agent_effective_configuration_api.py tests/test_agent_configuration_api.py tests/test_production_containers.py
~~~

Frontend:

~~~powershell
cd web
npm run typecheck
npm test
cd ..
~~~

## Step 2 — Agent Factory and Runtime Sessions

Replace the single cached `get_agent()` path with an Agent Factory keyed by `agent_type`.

Targets:

- generic Agent protocol;
- factory registration;
- per-Agent cache/lifecycle;
- ChatSessionManager bound to one Agent type;
- PersistentChatCoordinator created per Agent type.

### Step 2 implementation status

**IMPLEMENTED pending local gate**

Phase 7 now has a generic runtime construction layer.

### Runtime protocol

Added:

~~~text
AgentTurnProtocol
AgentProtocol
~~~

The session layer only requires:

~~~text
AgentProtocol.handle(question)
    ↓
AgentTurnProtocol
├─ decision
├─ answer
└─ needs_clarification
~~~

This removes the direct `DockerSupportAgent` type dependency from:

~~~text
AgentConversation
ChatSessionManager
~~~

The durable persistence coordinator still requires `LangGraphAgentTurnResult` because the
current persistence adapter stores supervisor/worker execution metadata. That specialization
is intentionally retained until a second real Agent proves a broader persistence contract is
needed.

### AgentFactory

Added:

~~~text
AgentFactory
AgentBuilder
AgentBuilderAlreadyRegistered
AgentBuilderNotRegistered
validate_factory_registration()
~~~

The Factory:

- resolves external Agent types through the Registry;
- caches one runtime instance per canonical Agent type;
- rejects duplicate builders;
- reports missing builders;
- supports targeted invalidation;
- supports full cache clear on application shutdown;
- uses one build lock per Agent type.

Per-Agent build locks prevent duplicate concurrent construction of one expensive Agent while
allowing different Agent types to initialize independently.

### Docker Support builder

Docker Support is now registered as a runtime builder:

~~~text
DOCKER_SUPPORT_DESCRIPTOR
        ↓
_build_docker_support_agent()
        ↓
AgentFactory
        ↓
LangGraphDockerSupportAgent
~~~

The builder still applies:

- secure base Settings;
- persisted product preferences;
- enabled/disabled validation;
- existing LangGraph Docker Support construction.

The behavior of the current Docker Agent is unchanged.

### Runtime session isolation

Runtime helpers are now Agent-aware:

~~~text
get_agent(agent_type)
get_chat_sessions(agent_type)
get_chat_coordinator(agent_type)
~~~

The default remains:

~~~text
docker_support
~~~

so the existing `POST /chat` contract is unchanged in Step 2.

Each `ChatSessionManager` is bound to one `agent_type`.

`PersistentChatCoordinator` verifies:

~~~text
sessions.agent_type == coordinator.agent_type
~~~

and rejects a mismatched runtime binding immediately.

This provides the isolation required before Step 3 lets clients select an Agent type.

### Configuration invalidation

When the Docker Support configuration changes:

~~~text
AgentFactory.invalidate("docker_support")
get_agent.cache_clear()
~~~

is applied.

New turns then receive a runtime Agent built from the new effective configuration.

An already-active clarification session keeps the Agent instance it started with so one
conversation turn cannot switch model/runtime configuration halfway through its clarification
flow.

### Lifecycle

FastAPI shutdown now clears:

~~~text
chat coordinator cache
chat session-manager cache
get_agent compatibility cache
AgentFactory runtime instances
database engine
~~~

### Step 2 coverage

Tests cover:

- canonical Agent instance caching;
- targeted invalidation and rebuild;
- independent cached instances across Agent types;
- duplicate builder rejection;
- missing builder rejection;
- Registry/Factory completeness validation;
- full AgentFactory cache clear;
- session-manager/coordinator Agent-type mismatch rejection;
- existing durable chat behavior remains compatible.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_agent_factory.py tests/test_agent_registry.py tests/test_persistent_chat.py tests/test_chat_api.py tests/test_database_runtime.py
~~~

Frontend is unchanged functionally in Step 2. A quick type/test gate is still recommended:

~~~powershell
cd web
npm run typecheck
npm test
cd ..
~~~

## Step 3 — Agent-Aware Chat Contract

Extend Chat so a new conversation can choose an Agent type.

Requirements:

- new chat accepts an Agent type;
- follow-up conversation Agent type is immutable;
- session and conversation mismatch checks remain enforced;
- existing clients default safely to Docker Support during migration.

### Step 3 implementation status

**IMPLEMENTED pending local gate**

The Chat API is now Agent-aware while preserving the existing Docker Support default.

### Request contract

`POST /chat` now accepts:

~~~json
{
  "message": "...",
  "agent_type": "docker_support",
  "conversation_id": null,
  "session_id": null
}
~~~

`agent_type` is optional.

For a new conversation:

~~~text
agent_type omitted
    ↓
docker_support

agent_type provided
    ↓
Registry normalization
    ↓
matching Agent coordinator
~~~

Unknown/unregistered Agent types are rejected before a conversation is created.

### Persisted conversation authority

For an existing conversation, the persisted:

~~~text
conversation.agent_type
~~~

is authoritative.

If the client omits `agent_type`, the backend loads the conversation and automatically
routes the turn through that Agent type.

If the client explicitly sends a different registered Agent type:

~~~text
persisted future_agent
request docker_support
        ↓
HTTP 409 Conflict
~~~

A conversation therefore cannot switch Agent identity after creation.

### Response contract

`ChatResponse` now includes:

~~~text
agent_type
~~~

and the HTTP response adds:

~~~text
X-Agent-Type
~~~

Both contain the canonical Agent type used for the turn.

This lets future clients track Agent identity without inferring it from route/tool behavior.

### Clarification session reset

Clarification session state is already partitioned by Agent type from Step 2.

The reset API now supports:

~~~text
DELETE /chat/{session_id}?agent_type={agent_type}
~~~

The query parameter is optional and defaults to `docker_support` for backward compatibility.

Non-default Agent sessions must identify their Agent type when reset so one Agent's in-memory
session namespace is never searched through another Agent coordinator.

### Web API preparation

The Web client now supports:

~~~text
sendChat({
  message,
  agentType,
  conversationId,
  sessionId
})

resetChatSession(
  sessionId,
  agentType
)
~~~

No visual Agent selector is introduced in Step 3. Existing Web chat still omits `agentType`,
which preserves Docker Support for new conversations and lets existing conversations route
from their persisted Agent identity.

### Step 3 compatibility

Existing clients that send only:

~~~json
{
  "message": "..."
}
~~~

continue to create Docker Support conversations.

Existing follow-up clients that send:

~~~json
{
  "message": "...",
  "conversation_id": "...",
  "session_id": "..."
}
~~~

continue to work because the Agent type is resolved from persistence.

### Step 3 coverage

Tests cover:

- legacy new-chat default to Docker Support;
- canonical Agent identity in response and headers;
- explicit Agent selection for a new conversation;
- normalized Agent type selection;
- existing-conversation Agent inference from persistence;
- cross-Agent conversation switch rejection with HTTP 409;
- unregistered Agent rejection before conversation creation;
- Agent-aware clarification-session reset;
- Web chat request serialization;
- Web clarification reset serialization;
- optional integration smoke assertion of canonical `agent_type`.

Focused gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_chat_api.py tests/test_persistent_chat.py tests/test_agent_factory.py tests/test_agent_registry.py tests/test_conversation_api.py
~~~

Frontend:

~~~powershell
cd web
npm run typecheck
npm test
cd ..
~~~

Optional integration smoke:

~~~powershell
cd web
npm run smoke
cd ..
~~~

## Step 4 — Generic Configuration Schema

Move frontend/backend setting-field definitions out of Docker-specific hardcoding.

Descriptor/configuration metadata should drive:

- editable groups;
- field labels/types/ranges;
- effective configuration rendering;
- validation dispatch.

Secure environment-owned values remain non-editable.

### Step 4 implementation status

**IMPLEMENTED pending local gate**

Agent configuration metadata now has one authoritative source: the runtime Agent descriptor.

### Generic configuration schema primitives

Added:

~~~text
ConfigurationFieldDescriptor
ConfigurationGroupDescriptor
ConfigurationRuleDescriptor
ConfigurationSchemaError
validate_configuration_schema()
resolve_settings_from_schema()
~~~

A field descriptor declares:

~~~text
key
settings_name
label
description
kind
minimum
maximum
~~~

The internal `settings_name` mapping is used by the backend but is not exposed to Web
clients.

Supported editable value kinds currently are:

~~~text
string
integer
number
~~~

Supported cross-field rules currently are:

~~~text
less_equal
not_all_zero
~~~

These are sufficient for the existing Docker Support configuration while remaining reusable
for the next Agent.

### Docker Support descriptor as the schema source

`DOCKER_SUPPORT_DESCRIPTOR` now owns the complete editable configuration schema for:

~~~text
Model
Retrieval
Runtime
~~~

including field labels, descriptions, ranges, Settings mappings, and cross-field rules.

The former duplicate field maps in `agent.configuration` are removed.

Docker Support still exposes the same persisted preference keys, so existing database records
and API payloads remain compatible.

### Schema integrity validation

Agent registration now rejects invalid configuration metadata before runtime use.

Validation includes:

- duplicate configuration groups;
- duplicate field keys;
- unsupported group names;
- empty field keys/labels/descriptions/settings mappings;
- unsupported value kinds;
- minimum greater than maximum;
- multiple UI fields mapped to one Settings field;
- rules referencing unknown groups or fields;
- invalid rule arity.

This prevents a newly registered Agent from publishing a malformed Settings UI/API contract.

### Generic effective configuration resolver

Added:

~~~text
resolve_agent_configuration(
    descriptor,
    base_settings,
    persisted_record,
)
~~~

The resolver:

1. starts from secure application/environment Settings;
2. applies only fields declared by the Agent descriptor;
3. validates primitive ranges;
4. validates descriptor cross-field rules;
5. preserves secure environment-owned values;
6. returns effective/persisted metadata.

`resolve_docker_support_configuration()` remains as a compatibility wrapper.

A registered descriptor can therefore resolve effective configuration even before a runtime
Agent builder exists. Configuration metadata and runtime implementation remain separate
platform concerns.

### Registered vs persisted-only Agent configuration

For a **registered Agent**:

~~~text
configuration request
    ↓
Registry canonical agent_type
    ↓
descriptor schema validation
    ↓
persistence
~~~

For an **unregistered persisted-only Agent**:

~~~text
configuration request
    ↓
secret-field rejection
    ↓
persistence
~~~

This preserves the earlier platform rule that stored configuration does not imply runtime
support.

Registered Agent identities are canonicalized, so:

~~~text
Docker-Support
docker_support
~~~

refer to the same `docker_support` configuration record.

Runtime invalidation after a saved configuration is also generic: any Agent with a registered
Factory builder is invalidated by its canonical Agent type.

### Agent catalog API metadata

`GET /agents` and `GET /agents/{agent_type}` now include:

~~~text
configuration_schema
configuration_rules
~~~

The public schema exposes UI-safe metadata but does not expose internal `settings_name`
mappings.

### Descriptor-driven Web Settings

`useAgentSettings(agentType)` now loads in parallel:

~~~text
GET /agents/{agent_type}
GET /agent-configurations/{agent_type}/effective
~~~

The composable builds editable fields directly from descriptor metadata.

The Web layer no longer contains a Docker-specific field table for:

~~~text
model_name
temperature
top_k
rerank_top_k
dense_weight
keyword_weight
max_steps
...
~~~

Labels, descriptions, input kinds, minimum/maximum values, group labels, and cross-field
validation now come from the Agent descriptor.

`SettingsView.vue` also renders group names and the Agent display name from descriptor
metadata rather than hardcoded Docker Support labels.

The page still defaults to `docker_support` until the visual Agent selector is added in
Step 6.

### Step 4 coverage

Backend tests cover:

- generic Settings field mapping;
- unsupported field rejection;
- unsupported group rejection;
- numeric range validation;
- generic cross-field rules;
- schema integrity validation;
- Docker Support effective configuration compatibility;
- canonical registered Agent configuration identity;
- a test-only `future_agent` with a different configuration schema;
- effective configuration for a descriptor-only Agent;
- Agent catalog schema/rule serialization.

Frontend tests cover:

- descriptor-provided labels and ranges;
- descriptor-provided group labels;
- requested Agent type loading;
- explicit override serialization;
- descriptor `less_equal` validation;
- descriptor `not_all_zero` validation;
- Agent descriptor API schema serialization.

Focused backend gate:

~~~powershell
uv run ruff check .
uv run pytest -v tests/test_agent_configuration_schema.py tests/test_agent_registry.py tests/test_agents_api.py tests/test_agent_effective_configuration.py tests/test_agent_effective_configuration_api.py tests/test_agent_configuration_api.py
~~~

Frontend:

~~~powershell
cd web
npm run typecheck
npm test
cd ..
~~~

After the focused gate passes, run the full backend suite:

~~~powershell
uv run pytest -v
~~~

## Step 5 — Second Real Agent

Add a genuinely different Agent implementation to prove the abstraction.

The second Agent must differ in at least:

- capabilities;
- toolset and/or knowledge source;
- graph/factory path.

It must not be a renamed Docker Support Agent.

## Step 6 — Web Agent Selector

Expose registered Agents in the Web product.

Targets:

- Agent selector for new conversations;
- Agent identity in conversation list/detail;
- Agent-aware Settings;
- capability summary.

## Step 7 — Cross-Agent Operations and Evaluation

Ensure telemetry, Operations, configuration, and evaluation remain useful when multiple
Agent types are active.

Targets:

- Agent filters;
- per-Agent run distributions;
- per-Agent evaluation suites where applicable;
- platform closeout tests/documentation.

## Phase 7 Completion Criteria

Phase 7 is complete when:

- runtime-supported Agents come from a Registry rather than scattered constants;
- Chat can create conversations for more than one real Agent type;
- sessions cannot cross Agent boundaries;
- settings are selected/rendered by Agent metadata;
- the Web can choose an Agent for a new conversation;
- Operations can distinguish Agent types;
- existing Docker Support behavior and tests remain compatible.
