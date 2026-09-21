# Upgrade Phase 3B Closeout

## Status

**Phase 3B — Persistence and Configuration Foundations: COMPLETE pending local Ruff/pytest gate**

Phase 3B turns the Docker Support Agent backend into a product backend with durable chat
history, reusable agent configuration, and a safe settings contract for a future frontend.

## Product Persistence Architecture

~~~text
POST /chat
    ↓
PersistentChatCoordinator
    ├─ durable conversation_id
    └─ temporary clarification session_id
    ↓
LangGraphDockerSupportAgent
    ↓
persist_langgraph_turn
    ↓
conversations
messages
agent_executions
~~~

The durable conversation id survives completed turns. Clarification session ids remain
temporary in-memory state and are never reused as product conversation identity.

## Conversation Backend Contract

Phase 3B now provides:

~~~text
POST   /chat
GET    /conversations
GET    /conversations/{conversation_id}
PATCH  /conversations/{conversation_id}
DELETE /conversations/{conversation_id}
~~~

The history APIs expose product DTOs only. They do not expose ORM objects, raw GraphState,
full RAG contexts, or raw Docker stdout.

Assistant messages can include compact execution metadata:

~~~text
planned_workers
completed_workers
worker_trace
~~~

## Agent Configuration Contract

Persisted preferences are stored per agent type:

~~~text
agent_type
display_name
enabled
model_settings
retrieval_settings
runtime_settings
~~~

Configuration CRUD:

~~~text
GET   /agent-configurations
GET   /agent-configurations/{agent_type}
POST  /agent-configurations
PATCH /agent-configurations/{agent_type}
~~~

The general JSON persistence layer rejects nested secret fields.

Docker Support then adds a stricter runtime allowlist so unsupported preferences are
rejected rather than silently persisted as no-op values.

## Effective Runtime Configuration

Docker Support Agent construction now resolves:

~~~text
secure environment/default Settings
              +
persisted allowlisted preferences
              ↓
EffectiveDockerSupportConfiguration
              ↓
LangGraphDockerSupportAgent
~~~

Persisted preferences can control supported model, retrieval, and runtime behavior but
cannot override provider credentials or infrastructure-owned secure settings.

After a successful Docker Support configuration write, the cached agent is invalidated.
The next new agent session uses the updated effective configuration.

An active clarification session keeps the agent instance it started with until that
session finishes.

## Effective Configuration API

The settings UI can inspect the final runtime view through:

~~~text
GET /agent-configurations/{agent_type}/effective
~~~

The first supported type is:

~~~text
docker_support
~~~

Each editable field reports:

~~~text
persisted_value
base_value
effective_value
source
editable
secure
configured
~~~

Source is one of:

~~~text
persisted
environment
default
~~~

Environment-owned fields are marked non-editable.

Sensitive fields such as:

~~~text
model_api_key
model_base_url
database_url
~~~

never return their actual values. The API only reports source metadata and whether the
field is configured.

A disabled agent remains readable through the effective endpoint so a settings page can
inspect and re-enable it. New agent construction remains blocked while disabled.

## Security Boundary

Phase 3B deliberately does not implement a secret store.

Secrets remain owned by environment/application configuration.

The product database must not contain:

~~~text
api_key
access_token
refresh_token
password
client_secret
private_key
credentials
~~~

Raw runtime evidence and raw Docker output also remain outside ordinary chat history by
default.

## Phase 3B Completion Criteria

The architecture work is complete because the backend now has:

- durable conversation and message persistence;
- compact persisted agent execution metadata;
- durable conversation identity separated from clarification sessions;
- conversation read/rename/delete APIs;
- agent configuration persistence and CRUD APIs;
- recursive secret rejection;
- Docker Support runtime preference allowlisting;
- effective configuration resolution;
- real runtime application of persisted preferences;
- cached-agent invalidation after configuration changes;
- disabled-agent enforcement;
- secret-safe effective configuration read API.

## Local Validation Gate

Before the branch is treated as merge-ready, run:

~~~powershell
uv run ruff check .
uv run pytest -v
~~~

Useful focused regression gate:

~~~powershell
uv run pytest -v `
  tests/test_agent_configuration_persistence.py `
  tests/test_agent_configuration_api.py `
  tests/test_agent_effective_configuration.py `
  tests/test_agent_effective_configuration_api.py `
  tests/test_persistence_store.py `
  tests/test_persistent_chat.py `
  tests/test_conversation_api.py `
  tests/test_chat_api.py
~~~

For this product-layer phase, the full Phase 2 runtime parity/Judge matrix is not required
unless the normal regression suite reveals an agent-behavior regression.

## Next Stage

**Phase 4 — Web Product Shell**

Recommended first frontend scope:

1. conversation sidebar;
2. chat panel using durable conversation ids;
3. source/tool/execution trace panels;
4. agent settings page using persisted + effective configuration APIs;
5. disabled-agent and backend-error states.

The frontend should consume the product DTOs introduced in Phase 3B rather than importing
or reconstructing internal GraphState semantics.
