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
