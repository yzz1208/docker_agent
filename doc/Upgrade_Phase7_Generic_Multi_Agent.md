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

## Step 3 — Agent-Aware Chat Contract

Extend Chat so a new conversation can choose an Agent type.

Requirements:

- new chat accepts an Agent type;
- follow-up conversation Agent type is immutable;
- session and conversation mismatch checks remain enforced;
- existing clients default safely to Docker Support during migration.

## Step 4 — Generic Configuration Schema

Move frontend/backend setting-field definitions out of Docker-specific hardcoding.

Descriptor/configuration metadata should drive:

- editable groups;
- field labels/types/ranges;
- effective configuration rendering;
- validation dispatch.

Secure environment-owned values remain non-editable.

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
