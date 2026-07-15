# AES Workbench Architecture

The `web-ui/` component is the browser-facing AES Workbench. It replaces the
previous generic browser UI with an AES-native application: chat on the left,
results and visualization on the right.

```mermaid
flowchart TD
    A["Browser"] --> B["web-ui Nginx"]
    B --> C["React Workbench"]
    C --> AUTH["/api/auth/login, /me, /logout"]
    AUTH --> B
    C --> D["Left pane<br/>chat + history"]
    C --> E["Right pane<br/>result workspace"]
    D --> F["POST /v1/chat/completions"]
    F --> B
    B --> G["langgraph:8001"]
    G --> H["aes_result"]
    H --> D
    H --> E
    D --> CACHE["Compact per-user local chat cache"]
    E --> I["/artifacts/..."]
    I --> B
    B --> G
```

## Ownership

`web-ui/` owns:

- authenticated login/session UI,
- server-authenticated session bootstrap and logout,
- browser-local conversation storage scoped by authenticated username,
- chat panel against `aes-agent`,
- persisted AES progress turns,
- result workspace,
- artifact links and diagnostics rendering,
- VTK.js viewer shell,
- Nginx proxy for `/api/`, `/v1/`, and `/artifacts/`.

It does not own:

- LangGraph execution,
- Ollama model selection,
- artifact generation,
- FEniCS execution.

## Layout

```mermaid
flowchart TD
    A["AES Workbench"] --> B["Header"]
    A --> C["Left side"]
    A --> D["Right side"]
    C --> E["Conversation history"]
    C --> F["Chat turns"]
    C --> G["Composer"]
    D --> H["Run summary"]
    D --> I["Preview / VTK.js viewer"]
    D --> J["Diagnostics"]
    D --> K["Artifact panel"]
```

The visual target is a bright ChatGPT-like theme. The saved-chat sidebar is
slightly darker than the main chat surface.

## Scroll Model

The page body should not be the normal scroll container. Each pane owns its own
scroll behavior.

```mermaid
flowchart TD
    A["body / #root"] -->|"overflow hidden"| B["workbench"]
    B --> C["conversationList<br/>own scrollbar"]
    B --> D["turnList<br/>own scrollbar"]
    B --> E["resultPane<br/>own scrollbar"]
```

This keeps the composer and layout stable while long chats or large result
panels are inspected.

## Session Model

Identity is server-authenticated. The browser receives an opaque `HttpOnly`
session cookie and never stores the password or raw token in JavaScript-accessible
storage. On every page load the Workbench asks the AES API for the current user.

```mermaid
flowchart TD
    A["Load Workbench"] --> B["GET /api/auth/me<br/>with session cookie"]
    B --> C{"Authenticated?"}
    C -->|no| D["Show login form"]
    D --> E["POST /api/auth/login"]
    E --> B
    C -->|yes| F["Receive public user profile"]
    F --> G["Load local conversation cache<br/>for authenticated username"]
    G --> H["Select active conversation"]
    H --> I["Render chat + latest result"]
```

PostgreSQL is authoritative for users and sessions. Conversation content is
still stored in browser `localStorage` as a transitional implementation. The
next database slice moves conversations and messages to authenticated APIs;
local storage then becomes only an optimistic cache and UI preference store.

Saved conversations contain:

- chat turns,
- persisted progress turns,
- compact latest `aes_result`,
- artifact/result links.

The Workbench never persists raw graph/tool payloads, inline generated files,
or sampled numerical arrays in `localStorage`. The API response projection and
the browser storage projection both retain only status, answer text, and the
artifact-store manifest references needed by the result pane. Large viewer
manifests, diagnostics, previews, and solution data are fetched on demand from
authenticated `/artifacts/...` URLs. This keeps a single solve from exceeding
the browser storage quota.

When a page reload interrupts an in-flight request, the restored progress turn
is marked as interrupted instead of remaining permanently active at `Waiting
for final response`.

## Persistent Progress Turns

AES progress is represented as a real chat turn, not transient component state.

```mermaid
flowchart TD
    A["User sends request"] --> B["Append user turn"]
    B --> C["Append progress turn"]
    C --> D["POST /v1/chat/completions"]
    D --> E["Advance progress steps while running"]
    E --> F["Response received"]
    F --> G["Mark progress done"]
    G --> H["Append AES assistant answer"]
    H --> I["Persist conversation"]
```

This means refresh does not remove the progress record. Each question keeps its
own progress block between the user request and AES answer.

## Result Workspace

The right pane reads `aes_result` from the OpenAI-compatible response.

```mermaid
flowchart TD
    A["compact aes_result"] --> B["ResultWorkspace"]
    B --> C["Status and next action"]
    B --> D["Artifact manifest references"]
    D --> H["Authenticated /artifacts fetch"]
    B --> E["DiagnosticsPanel"]
    B --> F["Preview iframe"]
    B --> G["VtkResultViewer"]
```

The viewer has two rendering paths:

- sampled-field rendering from `viewer_manifest.datasets.sampled_field`, used
  for stationary fields such as \(u(x,y)\) and transient fields such as
  \(u(x,y,t)\) before full VTK conversion exists;
- VTK.js rendering when AES serves browser-fetchable `.vtu`, `.vtp`, `.vtk`, or
  `.vtkjs` datasets.

Until at least sampled-field data or a VTK dataset exists, the UI shows
diagnostics, SVG previews, and raw artifact references.

## Proxy Boundary

Container deployment uses same-origin proxying:

```text
/v1/*         -> http://langgraph:8001/v1/*
/api/*        -> http://langgraph:8001/api/*
/artifacts/* -> http://langgraph:8001/artifacts/*
```

The `/v1/` proxy has long timeouts because first model loads and FEniCS runs can
take several minutes. Browser requests include credentials so the same-origin
session cookie protects chat and artifact access.
