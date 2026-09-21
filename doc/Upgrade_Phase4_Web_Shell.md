# Upgrade Phase 4 — Web Product Shell

## Goal

Phase 4 turns the Phase 3B product backend into an operator-facing web application.

The frontend consumes product DTOs only. It must not reconstruct internal GraphState or
depend on ORM/runtime implementation details.

## Technology

~~~text
Vue 3
TypeScript
Vite
Vue Router
native fetch API
~~~

The first shell deliberately avoids a large UI framework or state-management dependency.
The existing backend contracts are small enough to validate the product flow first.

Development uses the Vite proxy:

~~~text
browser :5173
   ↓
Vite
   ↓
FastAPI :8000
~~~

so CORS does not need to be opened just for local development.

## Step 1 — Runnable Product Shell

New frontend root:

~~~text
web/
├─ package.json
├─ vite.config.ts
├─ index.html
└─ src/
   ├─ main.ts
   ├─ App.vue
   ├─ router.ts
   ├─ styles.css
   ├─ lib/
   │  ├─ api.ts
   │  └─ types.ts
   └─ views/
      ├─ ChatView.vue
      └─ SettingsView.vue
~~~

### Typed API client

The frontend now has TypeScript contracts for:

- chat responses;
- runtime/document sources;
- worker execution metadata;
- conversation summaries/details;
- persisted agent configuration;
- effective configuration metadata.

The API layer centralizes HTTP error handling and exposes product operations such as:

~~~text
listConversations
getConversation
renameConversation
deleteConversation
sendChat
resetChatSession
getAgentConfiguration
getEffectiveAgentConfiguration
updateAgentConfiguration
~~~

### Chat workspace

The first chat workspace supports:

- loading persisted conversations;
- opening conversation history;
- starting a new durable conversation;
- sending an independent turn;
- continuing an active clarification session;
- showing persisted message execution metadata;
- renaming a conversation;
- deleting persisted history;
- inspecting latest-turn route, worker roles, runtime sources, and docs sources.

The latest-turn source panel is intentionally transient because Phase 3B persists compact
execution metadata, not full runtime/doc source payloads.

### Settings workspace

The settings page consumes:

~~~text
GET /agent-configurations/docker_support/effective
~~~

and displays:

- effective value;
- persisted/environment/default source;
- editable vs environment-owned status;
- redacted configured/not-configured state for secure fields.

Step 1 is read-only for settings. Editing persisted preferences is a later Phase 4 step.

## Validation

Frontend gate:

~~~powershell
cd web
npm install
npm run typecheck
npm run build
~~~

Backend remains:

~~~powershell
uv run ruff check .
uv run pytest -v
~~~

## Next

Step 2 will harden the conversation workspace:

1. remove browser prompt/confirm interactions in favor of product dialogs;
2. improve optimistic/loading/error states;
3. preserve latest-turn details across normal navigation where appropriate;
4. add responsive behavior and empty/error boundaries;
5. add focused frontend tests for API and conversation state transitions.

After the chat workspace stabilizes, Step 3 will make supported agent settings editable.
