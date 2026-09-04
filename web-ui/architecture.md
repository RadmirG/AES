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
    SAMPLES["Versioned GeometrySpec samples"] --> E
    UPLOAD["Local GeometrySpec JSON or display-only VTP"] --> E
    E --> CTX["Conversation geometry context"]
    CTX --> D
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
- KaTeX rendering of the solved PDE and its conditions,
- persistent standard-geometry selection and local GeometrySpec upload,
- artifact links and diagnostics rendering,
- VTK.js geometry and numerical-result rendering,
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
    D --> H["KaTeX PDE formulation"]
    D --> I["Scientific VTK.js viewport"]
    D --> J["Manifest and stdout actions"]
    D --> K["Diagnostics"]
    D --> L["Artifact inventory"]
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
- an optional attached GeometrySpec for subsequent solve requests.

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

The right pane reads the bounded `aes_result` from the OpenAI-compatible
response. The public projection includes `pde_spec`, so the browser renders the
validated equation, domain, boundary conditions, initial condition, and time
configuration without parsing the assistant's prose.

```mermaid
flowchart TD
    A["compact aes_result"] --> B["ResultWorkspace"]
    B --> C["EquationSummary"]
    C --> D["KaTeX equation and conditions"]
    B --> E["GeometryExplorer"]
    S["Selected GeometrySpec sample"] --> CXT["Conversation attachment"]
    U["Uploaded GeometrySpec JSON"] --> CXT
    CXT --> API["POST geometry_spec with chat request"]
    API --> E
    VTP["Display-only VTP"] --> E
    E --> F{"Best available visualization"}
    F -->|unsolved| G["VTK geometry actors"]
    F -->|solver topology and nodal values| H["VTK.js scalar field on solver mesh"]
    F -->|provider VTP| HV["VTK.js provider dataset"]
    F -->|non-spatial result| HC["Dynamic result chart"]
    B --> I["Manifest and stdout actions"]
    B --> J["DiagnosticsPanel"]
    B --> K["ArtifactPanel"]
    H --> L["Authenticated /artifacts fetch"]
```

The single scientific viewport has these rendering paths:

- browser-generated VTK PolyData actors for the canonical primitive/CSG
  `GeometrySpec` samples;
- uploaded `GeometrySpec` JSON for supported rectangle/box and optional
  disk/cylinder-hole previews;
- display-only uploaded VTK XML PolyData (`.vtp`);
- topology-preserving VTK.js rendering from
  `viewer_manifest.datasets.sampled_field`: 2D cells render directly and 3D
  tetrahedral/hexahedral cells are reduced to their exterior faces, including
  internal hole walls; nodal scalar colors are interpolated over those faces
  and mesh edges remain visible;
- provider-produced VTK XML PolyData referenced by the viewer manifest.
- a dynamic line chart when a numerical result has a scalar history but no
  spatial dataset.

The initial 2D camera is top-down with parallel projection. The 3D plate camera
is isometric. VTK interaction supports rotate, pan, zoom, and cell picking;
picked semantic region actors are highlighted. Renderer instances are disposed
and their canvases removed on every sample change so browser and GPU resources
do not accumulate.

Selecting a standard sample or uploading a `GeometrySpec` JSON attaches that
typed contract to the current conversation. It is persisted with the local
conversation cache and sent as `geometry_spec` in the authenticated
OpenAI-compatible request. The latest solve records the geometry context it
used, preventing a newly selected geometry from being confused with an older
solution. Raw VTP data is never sent as a computational geometry.

The Workbench sends user and assistant chat turns with each request. The API
uses the latest user turn for ordinary new requests, but reconstructs the
active PDE request when the previous assistant turn explicitly requested AES
clarification. Progress turns are UI-only and are never sent to LangGraph.

```mermaid
flowchart LR
    A["Geometry described in chat"] --> R["Chat request"]
    B["Selected standard GeometrySpec"] --> C["Conversation geometry context"]
    D["Uploaded GeometrySpec JSON"] --> C
    C --> R
    H["Prior PDE plus clarification answers"] --> R
    R --> E["LangGraph validation and solve"]
    E --> F["geometry_spec plus viewer manifest"]
    F --> G["One result-aware viewport"]
```

Run-level shortcuts are placed below the viewer and expose only
`viewer_manifest.json` and `stdout.txt`. The full artifact inventory remains a
read-only provenance view below diagnostics.

## Standard Geometry Catalog

The canonical examples live outside the UI in `examples/geometries/`. Each
example has a human-readable YAML document and an equivalent JSON document.
LangGraph tests validate both representations against `GeometrySpec`; native
provider tests generate all four with Gmsh and validate their semantic tags.

```mermaid
flowchart LR
    A["examples/geometries/index.json"] --> B["GeometryExplorer"]
    B --> C["Unit square 2D"]
    B --> D["Square with hole 2D"]
    B --> E["Plate solid 3D"]
    B --> F["Plate solid with hole 3D"]
    C --> G["VTK.js PolyData compiler"]
    D --> G
    E --> G
    F --> G
    G --> H["Interactive scientific viewport"]
```

Vite exposes the catalog at `/geometries/`. The production Docker build uses
the repository root as its restricted build context so it can copy both
`web-ui/` and `examples/geometries/`; `.dockerignore` excludes every unrelated
repository path from that image context.

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
