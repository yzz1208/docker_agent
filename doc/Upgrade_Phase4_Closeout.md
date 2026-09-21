# Upgrade Phase 4 Closeout

## Status

**Phase 4 — Web Product Shell: COMPLETE pending final local validation gate**

Phase 4 converts the Phase 3B product backend into a usable Vue web product while keeping
frontend contracts aligned with the backend DTO boundary.

## Final Product Architecture

~~~text
Browser
  ↓
Vue 3 / TypeScript
  ├─ Chat workspace
  ├─ Conversation history
  ├─ Execution/source inspection
  ├─ Agent settings
  └─ Backend health
  ↓
typed fetch client
  ↓
Vite local proxy
  ↓
FastAPI product APIs
  ↓
Persistence + Effective Config + LangGraph Agent
~~~

The frontend does not consume ORM rows or GraphState directly.

## Conversation Product Surface

The web shell supports:

- list/open durable conversations;
- create a new conversation through chat;
- preserve clarification session identity separately from durable conversation identity;
- render persisted user/assistant history;
- show compact persisted execution metadata;
- show latest-turn runtime/docs source metadata for the current browser session;
- rename conversations;
- delete conversations;
- recover from list/detail/action failures;
- protect against stale conversation-request races.

## Settings Product Surface

The settings workspace supports:

- display name;
- enabled/disabled state;
- allowlisted model preferences;
- allowlisted retrieval preferences;
- allowlisted runtime preferences;
- per-field Override semantics;
- first-save POST and later PATCH flows;
- removing persisted overrides to return to environment/default values;
- effective/persisted/environment/default source visibility;
- redacted infrastructure/secret status.

Every successful write is followed by a fresh effective-config read.

## Reliability Surface

The app shell adds:

- FastAPI liveness visibility;
- PostgreSQL health visibility;
- healthy/degraded/offline states;
- periodic health polling;
- manual health refresh;
- route-level Vue error fallback;
- catch-all 404 route;
- responsive desktop/tablet/mobile shell behavior.

## Test and Smoke Policy

Normal frontend gate:

~~~powershell
cd web
npm run typecheck
npm test
npm run build
~~~

Normal backend gate:

~~~powershell
uv run ruff check .
uv run pytest -v
~~~

Read-only integration smoke with backend + PostgreSQL running:

~~~powershell
cd web
npm run smoke
~~~

Optional real-agent smoke:

~~~powershell
$env:SMOKE_CHAT_MESSAGE="Docker daemon 连不上，先帮我判断可能原因"
npm run smoke
Remove-Item Env:SMOKE_CHAT_MESSAGE
~~~

The optional real-agent smoke may consume model/tool resources and is therefore not part of
the ordinary unit-test loop.

## Phase 4 Completion Criteria

Phase 4 is considered complete when the final local gate confirms:

- backend Ruff passes;
- backend pytest passes;
- frontend typecheck passes;
- frontend Vitest passes;
- frontend production build passes;
- read-only integration smoke passes against the local backend/database;
- one manual browser pass confirms Chat and Settings render normally.

## Deliberately Deferred

Phase 4 does not add:

- streaming token transport;
- WebSocket/SSE infrastructure;
- authentication or multi-user tenancy;
- arbitrary secret editing;
- a generic multi-agent admin console;
- a large UI component framework;
- browser end-to-end automation.

Those should only be added when a later product requirement needs them.

## Next Stage

Start the next upgrade phase from a new branch after this closeout gate is green.

The next phase should target a meaningful new capability, such as broader multi-agent
extensibility, observability/evaluation operations, deployment hardening, or realtime
interaction, instead of continuing to enlarge the first web shell.
