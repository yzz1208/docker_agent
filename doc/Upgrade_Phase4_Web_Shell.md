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

## Step 2 — Conversation Workspace Hardening

The chat page is now split into a rendering layer and a reusable workspace state layer:

~~~text
ChatView.vue
    ↓
useConversationWorkspace()
    ↓
typed API client
~~~

This removes request/state-transition logic from the page component and gives later
streaming, multi-agent, and frontend-test work a stable boundary.

### Product dialogs

Browser-native `window.prompt` and `window.confirm` are removed.

Rename and delete now use a reusable:

~~~text
AppDialog.vue
~~~

The dialog supports:

- explicit busy state;
- Escape-to-close when safe;
- backdrop dismissal;
- destructive confirmation styling;
- keyboard rename submission.

### Conversation state hardening

The workspace now tracks independent states for:

~~~text
conversation list loading/error
conversation detail loading/error
chat submission
rename mutation
delete mutation
action-level error
active clarification session
latest turn by conversation
~~~

A request-version guard prevents a slower previous conversation request from overwriting a
newer selection.

Latest-turn route/source metadata remains transient, but is cached per conversation for the
current browser session so normal navigation no longer clears it immediately.

### Local mutation behavior

Rename updates the active detail and sidebar summary locally after the backend succeeds.

Delete removes the conversation and transient latest-turn metadata locally, then returns
the workspace to a new-conversation state.

### Error recovery

The workspace now exposes local retry/dismiss paths rather than routing every failure into
one global message:

- sidebar list retry;
- conversation detail retry;
- action error dismissal.

### Responsive shell

The original three-column desktop layout now degrades to:

~~~text
wide desktop: sidebar | chat | execution
medium:       sidebar | chat
              execution
small:        stacked panels
~~~

Settings tables remain horizontally inspectable on narrow screens.

### Frontend tests

Vitest is added with focused tests for:

- chat request identity serialization;
- backend `detail` -> `ApiError` conversion;
- clarification session continuity;
- latest-turn preservation across navigation;
- stale conversation request protection;
- rename/delete local state transitions.

Updated frontend gate:

~~~powershell
cd web
npm install
npm run typecheck
npm test
npm run build
~~~

## Next

Step 3 will make supported Docker Support preferences editable from the settings page.

The form will use the persisted configuration API for writes and the effective
configuration API for source/effective-value feedback. Secure environment-owned fields
will remain read-only and redacted.
