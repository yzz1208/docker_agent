# Upgrade Phase 3B — Persistence and Configuration Foundations

## Goal

Phase 3B turns the agent backend into a product backend that can support:

- persistent conversations;
- persistent messages;
- agent execution history;
- user/agent configuration;
- a future Web UI;
- additional agent types beyond Docker Support.

The first step deliberately does **not** replace the existing in-memory clarification
session manager. Persistence is introduced as a separate product data layer first.

## Step 1 — Conversation Persistence Schema

New persistence package:

~~~text
src/docker_agent/persistence/
├─ models.py
├─ store.py
└─ __init__.py
~~~

Initial tables:

~~~text
conversations
messages
agent_executions
~~~

### conversations

Stores product-level conversation metadata:

~~~text
id
agent_type
title
created_at
updated_at
~~~

The agent_type field is explicit so storage remains reusable when more agents are added.

### messages

Stores durable chat messages:

~~~text
id
conversation_id
role
content
route
use_docs
clarification
created_at
~~~

Route and clarification metadata are attached only when relevant. The message model does
not store raw Docker tool stdout or complete RAG contexts.

### agent_executions

Stores safe orchestration metadata associated with an assistant message:

~~~text
message_id
planned_workers
completed_workers
worker_trace
created_at
~~~

worker_trace uses the compact Phase 3A execution contract. Raw runtime output and full
evidence remain outside chat history by default.

## Repository Boundary

The persistence layer exposes immutable records:

~~~text
ConversationRecord
MessageRecord
ExecutionRecord
ConversationSnapshot
~~~

and repository operations:

~~~text
create_conversation
append_message
save_execution
get_conversation
list_conversations
load_conversation
~~~

The repository takes an explicit SQLAlchemy Engine so it can use PostgreSQL in the
application while targeted tests use in-memory SQLite.

## Integration Order

After the standalone repository passes Ruff/pytest:

1. add a persistence adapter from LangGraphAgentTurnResult;
2. persist user and assistant turns from the Chat service;
3. separate persistent conversation id from temporary clarification state;
4. add conversation history API endpoints;
5. add agent configuration persistence;
6. build the frontend shell against those APIs.

This staged order avoids coupling the current clarification session semantics directly to
the long-lived product conversation model.


## Step 2 — LangGraph Turn Persistence Adapter

The persistence layer now has a dedicated product adapter:

~~~text
persist_langgraph_turn(...)
~~~

Input:

~~~text
conversation_id
user message text
LangGraphAgentTurnResult
~~~

Output:

~~~text
PersistedAgentTurn
├─ user_message
├─ assistant_message
└─ execution
~~~

Normal answer turns persist the generated answer as the assistant message.

Clarification turns persist the clarification prompt as the assistant message while keeping
the execution plan and worker trace empty.

The adapter serializes only the compact execution metadata introduced in Phase 3A:

~~~text
planned_workers
completed_workers
worker_trace
~~~

It does not persist GraphState, raw Docker stdout, or complete evidence contexts.

The adapter is still independent from the HTTP chat endpoint. Step 3 will connect durable
conversation identity to chat handling without reusing the temporary clarification
session id as the long-lived conversation id.


## Step 3 — Durable Conversation Identity

The product chat layer now has a dedicated coordinator:

~~~text
PersistentChatCoordinator
~~~

It separates two identities that previously looked similar but have different lifetimes:

~~~text
conversation_id
= durable product conversation
= survives completed turns
= owns persisted messages and executions

session_id
= temporary clarification state
= exists only while AgentConversation has a pending question
= in-memory only
~~~

A first turn without a conversation id creates a durable conversation. If the agent asks
for clarification, the temporary session is bound to that conversation.

A clarification follow-up must provide both ids:

~~~text
conversation_id
session_id
~~~

and the coordinator rejects attempts to use an active session with another conversation.

After clarification completes, the session is discarded while the conversation remains.
The same durable conversation can later receive another independent turn with no session id.

The coordinator also validates `agent_type` so a Docker Support request cannot
accidentally append messages to a conversation owned by a future agent type.

Step 3 still leaves the current HTTP `/chat` endpoint unchanged. Step 4 will expose the
durable conversation id in the API and switch the endpoint to this coordinator.


## Step 4 — Persistent Chat API Cutover

The public `POST /chat` endpoint now uses `PersistentChatCoordinator`.

Request shape:

~~~json
{
  "message": "web",
  "conversation_id": "<durable-id-or-null>",
  "session_id": "<clarification-session-or-null>"
}
~~~

Response shape now includes both identities:

~~~json
{
  "conversation_id": "<durable-conversation-id>",
  "session_id": "<temporary-session-id>",
  "session_active": false
}
~~~

Rules:

~~~text
new conversation:
conversation_id = null
session_id      = null

independent next turn in existing conversation:
conversation_id = existing durable id
session_id      = null

clarification follow-up:
conversation_id = existing durable id
session_id      = active clarification id
~~~

The default HTTP product path now creates `LangGraphDockerSupportAgent`, so every
persisted turn has the Supervisor/Worker execution contract required by the persistence
adapter.

Product persistence is initialized lazily on the first chat request. The current
development implementation uses SQLAlchemy `create_all` for these product tables; a
migration tool can replace this bootstrap before production deployment.

Deleting `/chat/{session_id}` only clears temporary clarification state. It deliberately
does not delete the durable conversation or historical messages.

HTTP-level targeted tests use a shared in-memory SQLite engine and verify:

- durable conversation id survives a clarification flow;
- user/assistant messages and executions are persisted;
- a clarification follow-up without conversation id is rejected;
- an expired clarification session returns 404;
- resetting a session leaves conversation history intact.

## Next

Step 5 will expose read-only conversation history APIs:

~~~text
GET /conversations
GET /conversations/{conversation_id}
~~~

Those endpoints will return product DTOs from the persistence repository and will not
expose ORM objects or raw internal GraphState.


## Step 5 — Conversation History API

The backend now exposes read-only product history endpoints:

~~~text
GET /conversations
GET /conversations/{conversation_id}
~~~

### Conversation list

The list endpoint returns lightweight summaries ordered by most recent activity:

~~~text
id
agent_type
title
created_at
updated_at
~~~

It supports:

~~~text
limit
offset
~~~

so a future sidebar can paginate conversation history without loading message bodies.

### Conversation detail

The detail endpoint returns:

~~~text
conversation metadata
messages[]
~~~

Each assistant message can include its own compact execution metadata:

~~~text
execution
├─ planned_workers
├─ completed_workers
└─ worker_trace
~~~

Execution rows are joined to messages in the API serializer, so frontend code does not
need to correlate a separate execution list by message id.

The history API exposes product DTOs only. It does not expose SQLAlchemy ORM objects,
GraphState, raw Docker stdout, or full evidence contexts.

### Targeted API coverage

Step 5 tests cover:

- conversation summary listing;
- most-recently-updated ordering;
- limit/offset pagination;
- detail message ordering;
- execution metadata attached to assistant messages;
- unknown conversation 404;
- invalid pagination 400.

## Next

Step 6 will add mutation operations needed by a real conversation sidebar:

~~~text
PATCH /conversations/{conversation_id}
DELETE /conversations/{conversation_id}
~~~

The first mutation scope will be intentionally small: rename a conversation and delete
its persisted history. Agent configuration persistence remains the following step.


## Step 6 — Conversation Mutation API

The conversation sidebar backend now supports the two basic mutations needed by a product UI:

~~~text
PATCH  /conversations/{conversation_id}
DELETE /conversations/{conversation_id}
~~~

### Rename

The PATCH endpoint accepts:

~~~json
{
  "title": "New conversation title"
}
~~~

Titles are trimmed, must not be empty, and are limited to 240 characters. Renaming also
updates the conversation activity timestamp.

### Delete

Deleting a conversation removes:

~~~text
agent_executions
messages
conversation
~~~

in explicit repository order. This avoids depending on SQLite foreign-key cascade settings
during tests while remaining compatible with PostgreSQL.

Before durable history is deleted, the coordinator clears any active clarification sessions
bound to that conversation. This prevents an in-memory session from surviving after its
durable conversation has been removed.

### Sidebar capability after Step 6

The backend now supports:

~~~text
list conversations
open conversation
rename conversation
delete conversation
continue conversation
show per-message execution metadata
~~~

This completes the first backend CRUD foundation for a future conversation sidebar.

## Next

Step 7 begins Agent Configuration persistence. The first configuration model will remain
small and reusable across future agent types:

~~~text
agent_type
display_name
model settings
retrieval/runtime preferences
enabled flag
updated_at
~~~

Secrets such as API keys will not be stored in the general JSON configuration payload.


## Step 7 — Agent Configuration Persistence

The product persistence layer now includes:

~~~text
agent_configurations
~~~

The first configuration contract is intentionally one base configuration per `agent_type`.

Stored fields:

~~~text
agent_type
display_name
enabled
model_settings
retrieval_settings
runtime_settings
created_at
updated_at
~~~

The three settings groups are separated so future UI sections can map cleanly to product
controls instead of exposing one unstructured settings blob.

### Secret boundary

General agent configuration is not a secret store.

Nested configuration payloads are recursively checked and reject fields such as:

~~~text
api_key
token
access_token
refresh_token
password
client_secret
private_key
credentials
~~~

Normal model controls such as `max_tokens` and `token_budget` remain valid because the
guard matches secret field names rather than arbitrary substrings.

Provider credentials continue to come from environment variables or a future dedicated
secret provider.

### Repository operations

~~~text
create_agent_configuration
get_agent_configuration
list_agent_configurations
update_agent_configuration
~~~

Configuration records are immutable product DTOs and JSON settings are deep-copied at the
repository boundary so caller-side mutation cannot silently change stored values.

### Targeted coverage

Step 7 tests cover:

- create/get round trip;
- multiple agent types;
- display-name ordering;
- partial update semantics;
- enabled flag;
- nested secret rejection;
- normal token-related model settings;
- input settings copy isolation;
- duplicate configuration rejection;
- unknown configuration handling.

## Next

Step 8 will expose configuration APIs suitable for a settings page:

~~~text
GET   /agent-configurations
GET   /agent-configurations/{agent_type}
POST  /agent-configurations
PATCH /agent-configurations/{agent_type}
~~~

The initial API will manage persisted product preferences only. It will not return or
accept provider API keys.


## Step 8 — Agent Configuration API

The backend now exposes product-facing configuration endpoints suitable for a settings page:

~~~text
GET   /agent-configurations
GET   /agent-configurations/{agent_type}
POST  /agent-configurations
PATCH /agent-configurations/{agent_type}
~~~

### Create

Example request:

~~~json
{
  "agent_type": "docker_support",
  "display_name": "Docker Support",
  "enabled": true,
  "model_settings": {
    "model_name": "example-model",
    "temperature": 0.2,
    "max_tokens": 4096
  },
  "retrieval_settings": {
    "top_k": 8,
    "rerank_top_k": 4
  },
  "runtime_settings": {
    "max_steps": 5
  }
}
~~~

Duplicate agent types return HTTP 409.

### Read and list

The list endpoint returns configurations ordered by display name. The detail endpoint
returns one agent type or HTTP 404 when no configuration exists.

### Partial update

PATCH updates only supplied fields. Unspecified model/retrieval/runtime groups keep their
stored values, while an explicitly supplied empty object clears that group.

### Security behavior

All requests still pass through the repository secret guard. Nested fields such as
`api_key`, `token`, `password`, or `private_key` return HTTP 400 and are never
persisted.

The response schema does not contain any provider credential field.

### Targeted API coverage

Step 8 tests cover:

- create + detail round trip;
- configuration listing;
- partial PATCH semantics;
- nested secret rejection;
- duplicate create conflict;
- unknown configuration 404;
- valid `max_tokens` and `token_budget` settings.

## Next

Step 9 will connect persisted configuration to agent construction through a typed
configuration resolver.

The first resolver will merge:

~~~text
secure environment settings
        +
persisted non-secret product preferences
        =
effective Docker Support configuration
~~~

Provider credentials will always come from the secure environment side. Persisted
configuration will only override explicitly supported non-secret fields.
