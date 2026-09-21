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

## Step 3 — Editable Agent Settings

The settings workspace now edits the same allowlisted Docker Support preferences that the
Phase 3B resolver applies at runtime.

### Override model

Each editable field has an explicit:

~~~text
Override
~~~

switch.

When Override is off:

~~~text
persisted field absent
        ↓
environment/default baseline
        ↓
effective runtime value
~~~

When Override is on:

~~~text
persisted preference
        ↓
effective runtime value
~~~

This avoids copying every current default into the database just because the user saved
one setting.

Turning an existing Override off removes that key from the replacement settings group on
the next save, restoring the environment/default value.

### First save vs later saves

The UI supports both backend write paths:

~~~text
no persisted docker_support record
→ POST /agent-configurations

existing persisted record
→ PATCH /agent-configurations/docker_support
~~~

The effective endpoint is reloaded after every successful write. The page therefore shows
the runtime-resolved value returned by the backend rather than assuming the submitted
value was accepted unchanged.

### Editable product preferences

Model:

~~~text
model_name
temperature
max_tokens
timeout_seconds
max_retries
retry_backoff_seconds
~~~

Retrieval:

~~~text
top_k
rrf_k
dense_weight
keyword_weight
rerank_top_k
context_max_chars
~~~

Runtime:

~~~text
max_steps
tool_timeout_seconds
logs_max_lines
evidence_max_chars
~~~

The page also edits:

~~~text
display_name
enabled
~~~

Disabling the agent remains inspectable and reversible through the settings page even
though new chat sessions are blocked by the backend.

### Validation

The frontend performs immediate shape/range validation and mirrors the two important
cross-field rules:

~~~text
rerank_top_k <= top_k
dense_weight and keyword_weight cannot both be zero
~~~

The backend remains authoritative and still revalidates every write.

### Secure boundary

Environment/infrastructure fields remain read-only.

Secure values such as:

~~~text
model_api_key
model_base_url
database_url
~~~

are never placed in an editable input and remain redacted as configured/not-configured.

### State layer

Settings state is isolated in:

~~~text
useAgentSettings()
~~~

It owns:

- loading/saving/error/success state;
- dirty detection;
- persisted-vs-first-save selection;
- override state;
- input parsing;
- cross-field validation;
- replacement-group payload construction;
- effective-config refresh after save.

### Frontend coverage

New tests cover:

- first-save POST with explicit overrides only;
- later PATCH updates;
- removing an override from a replacement group;
- retrieval cross-field validation before network writes;
- zero dense/keyword weight rejection;
- agent configuration API request serialization.

### Step 3 Validation Gate

~~~powershell
cd web
npm run typecheck
npm test
npm run build
~~~

Browser smoke test:

1. open Settings with no persisted configuration and save one override;
2. refresh and confirm the field source becomes persisted;
3. change the same value and save again;
4. turn Override off, save, and confirm the source returns to environment/default;
5. disable the agent, confirm a new chat is blocked, then re-enable it.

## Next

Step 4 will close Phase 4 with product-level integration hardening:

- frontend/backend startup and health state;
- navigation-level error boundaries;
- settings/chat integration smoke coverage;
- final UI cleanup;
- Phase 4 closeout documentation.

After that, the project can move to the next architecture/product capability rather than
continuing to expand the first web shell indefinitely.
