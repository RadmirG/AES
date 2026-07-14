# AES Architecture

AES is split into orchestration, model runtime, user interface, MCP providers,
deployment composition, and documentation.

```text
AES Web UI / Workbench
  -> same-origin Nginx proxy
  -> AES FastAPI / OpenAI-compatible endpoint
  -> LangGraph StateGraph
  -> AES tool registry
  -> MCP provider adapter
  -> provider-specific MCP servers
  -> AES artifact store
```

## Source Layout

```text
AES/
  langgraph/     # AES orchestration service
  mcp/           # MCP provider infrastructure
  ollama/        # model runtime compose file and data
  web-ui/        # default AES Workbench: chat + result viewer container
  deploy/        # dev/prod deployment entrypoints
  docs/          # architecture and operation docs
```

## Design Principles

- Keep LangGraph as the workflow and routing spine.
- Keep the LLM behind explicit nodes and schemas.
- Expose high-level AES wrapper tools to the model, not every low-level MCP tool.
- Keep heavy execution backends in separate provider containers.
- Keep final artifact policy in AES, not inside provider containers.
- Use planning mode by default for expensive numerical tools.
- Add live execution only after schema and smoke-test validation.

## Flexible FEniCS Code Path

The first FEniCS integration used a deterministic `numerical_recipe` that AES
translated into a fixed sequence of low-level DOLFINx MCP calls. That path is
useful for narrow smoke tests, but it is too rigid for general PDE work because
each new equation family requires new hand-written recipe and provider-call
logic.

The preferred architecture is now a hybrid path: LangGraph still owns
orchestration, validation, and artifact policy, while the LLM generates a full
DOLFINx Python script for flexible numerical workflows. AES performs static
safety checks before execution, runs the script only inside the FEniCS provider
boundary, and stores final outputs through the AES artifact store.

```mermaid
flowchart TD
    A["User PDE request"] --> B["LangGraph intent + problem extraction"]
    B --> C["Requested output?"]

    C -->|executable Python file| D["LLM generate DOLFINx solve.py"]
    C -->|execute and solve| D

    D --> E["Static code safety check"]
    E -->|unsafe| F["Ask clarification / reject unsafe code"]
    E -->|safe| G["Run script in FEniCS container via MCP"]

    G --> H["Collect stdout, stderr, files, diagnostics"]
    H --> I{"Run successful?"}

    I -->|no| J["LLM repair loop with stderr, max N tries"]
    J --> D

    D -->|no usable code| D1["Conservative deterministic fallback template"]
    D1 --> E

    I -->|yes| K["Artifact store"]
    K --> L["Final AES answer with code + result links"]

    C -->|known low-level smoke workflow| M["Optional deterministic MCP recipe path"]
    M --> K
```

Implementation rule: high-level AES tools stay exposed to LangGraph and the LLM;
low-level provider tools remain hidden behind wrapper code. The current
`fenics_code_solve` path can already generate and persist a checked `solve.py`.
Live execution requires a FEniCS MCP script-runner contract, for example
`run_python_script`, because the existing `dolfinx-mcp` allowlist intentionally
blocks arbitrary `run_custom_code`.

The generated-code path is LLM-first. A conservative deterministic fallback
template is allowed only when the LLM returns no usable Python code, so common
smoke tests still produce a checked artifact instead of failing silently.

`fenics_code_solve` implements the repair loop internally. For LLM-generated
code, AES validates the script, runs it in the FEniCS code-runner when execution
is enabled, and sends static-validation errors or runtime stdout/stderr back to
the LLM for a bounded number of repair attempts. User-provided Python code is
not auto-repaired; unsafe user code is rejected before execution.

If the selected mode requests execution but generated-code execution is disabled
or no provider script-runner is configured, AES should report a blocked tool
result. Production sets `DOLFINX_CODE_EXECUTE=true` and
`DOLFINX_CODE_MCP_URL=http://fenics-code-runner:8000/mcp` by default so AES
attempts the provider execution path through the separate code-runner service,
while dev keeps execution overrideable and disabled by default. The checked
`solve.py` may still be stored as an artifact, but the run must not be reported
as a completed numerical execution.

### Requested Output And Input Modes

AES should not assume that every PDE description is a request for generated
FEniCS code or immediate execution. A user may provide only a mathematical
problem statement, an explicit request for a Python file, a request to execute a
solve, or an already-written Python script. LangGraph should classify this
intent before selecting tools.

```mermaid
flowchart TD
    A["OpenAI chat history"] --> A1{"Latest user turn \n is output-mode reply?"}
    A1 -->|no| A2["Use latest user message as active request"]
    A1 -->|yes, AES asked for output| A3["Rebuild active request from previous PDE + selected output mode"]
    A2 --> B["Detect engineering intent"]
    A3 --> B
    B --> C["Detect input/output mode"]

    C -->|PDE text only| D["Ask requested output"]
    D --> E["Options: formulation summary, generate code, execute solve"]
    E --> H["Artifact store"]

    C -->|PDE text + asks for Python/FEniCS file| F["Generate DOLFINx solve.py"]
    F --> G["Static code safety check"]
    G -->|safe| H
    G -->|unsafe| R["Rejection / safety report"]
    R --> H

    C -->|PDE text + asks to execute/plot/compute| I["Generate DOLFINx solve.py"]
    I --> J["Static code safety check"]
    J -->|safe| K["Execute in FEniCS container via MCP"]
    J -->|unsafe| R
    K --> H

    C -->|User provides Python code directly| L["Treat code as candidate solve.py"]
    L --> M["Static code safety check"]
    M -->|unsafe| N["Reject or ask clarification"]
    M -->|safe| O["Execute in FEniCS container via MCP"]
    N --> H
    O --> H

    H --> Y["Result review renderer"]
    Y --> Z["Final AES response"]
```

The OpenAI-compatible adapter deliberately does not merge arbitrary chat
history into every AES request. This prevents a new operational message, such
as a Docker command, from inheriting an older PDE and accidentally triggering a
solver workflow. The controlled exception is AES's own requested-output
clarification: if AES asked what output the user wants and the next user turn is
a short reply such as `execution with stored result artifacts`, the adapter
rebuilds the active request as:

```text
previous PDE problem

Requested AES output: execute the generated DOLFINx/FEniCS solve and store result artifacts
```

This is a temporary lightweight resume rule until checkpoint-backed
conversation state is introduced.

Planned solution modes:

- `formulation_summary`: explain or derive the mathematical/FEM formulation
  without generating code.
- `needs_output_intent`: ask the user whether they want formulation, generated
  code, or execution.
- `generate_fenics_code`: generate and store a checked `solve.py`.
- `execute_generated_fenics_code`: generate, check, execute, and store results.
- `execute_user_fenics_code`: check user-provided Python code, execute it in the
  FEniCS container, and store results.
- `deterministic_mcp_recipe`: use the older constrained MCP recipe path for
  known simple workflows and smoke tests.

Direct user-provided Python code must use the same safety and artifact policy as
LLM-generated code. AES should never execute raw code directly in the LangGraph
container; execution belongs inside a sandboxed FEniCS provider boundary.

Artifact storage is a common terminal step for every path. A stored AES run may
contain a clarification question, formulation summary, generated `solve.py`,
execution diagnostics, solver files, an error report, or a rejected unsafe-code
report. In other words, artifact storage means traceability of the AES workflow,
not only successful numerical solver output.

### Result Review In The AES Workbench

Successful generated-code execution should not stop at `Next action:
review_tool_results`. AES renders a compact result review directly into the
chat answer from structured tool output:

- provider run id and return code,
- provider wall-clock runtime,
- timeout and artifact count,
- parsed script diagnostics from `diagnostics.json`,
- simulation parameters such as DOF count, time step count, `dt`, and final
  physical time,
- final solution statistics such as min, max, and mean,
- selected time samples for transient simulations,
- artifact references for `solve.py`, `diagnostics.json`, stdout/stderr logs,
  and solver outputs such as `solution.xdmf` / `solution.h5`.

The current text response shows diagnostics and artifact references. AES now
also has a first visualization postprocess step that creates browser-facing
preview artifacts before final artifact storage.

### Visualization UI With OpenUI And VTK.js

The visualization layer is now part of the AES web workbench. `web-ui/` is the
default browser-facing frontend for `aes-agent`: a split-pane application with
native chat on the left and numerical result review on the right. OpenUI is used
as a development/prototyping tool for the dashboard shell, while VTK.js is the
browser rendering engine for FEM datasets.

```mermaid
flowchart TD
    A["FEniCS solve completed"] --> B["fenics_code_solve result"]
    B --> C["visualization_postprocess"]

    C --> D["Read structured diagnostics"]
    C --> E["Inspect artifact references"]

    D --> F["preview.svg"]
    D --> G["viewer_manifest.json"]
    E --> G
    G --> H["viewer.html shell"]

    E --> I{"VTK.js-readable data?"}
    I -->|yes: .vtu/.vtp/.vtk/.vtkjs| J["Mark dataset interactive"]
    I -->|no| K["Show diagnostics + raw artifact links"]

    F --> L["artifact_store"]
    G --> L
    H --> L
    J --> L
    K --> L

    L --> M["AES artifact HTTP API"]
    M --> N["Chat answer result links"]
    M --> O["web-ui React app"]
    O --> P["VTK.js render viewport"]
    O --> Q["Diagnostics and artifact panels"]
```

Implemented pieces:

- `visualization_postprocess` tool runs after FEniCS solver tools and before
  `artifact_store`.
- It generates `preview.svg`, `viewer_manifest.json`, and `viewer.html` as
  inline AES artifacts.
- `artifact_store` materializes those files under `AES_ARTIFACT_ROOT`.
- The LangGraph API exposes stored artifacts through
  `/artifacts/{run_id}/{filename}`.
- `AES_PUBLIC_BASE_URL` controls the browser-facing base URL used in final
  artifact links; dev/prod Compose defaults it to `http://127.0.0.1:3000`,
  where the `web-ui` container reverse-proxies `/v1/` and `/artifacts/` to the
  LangGraph service on `ai-stack-net`.
- `web-ui/` is a Vite/React/TypeScript workbench with a left-side AES chat
  panel, result links, preview panel, diagnostics panel, artifact panel, VTK.js
  viewer component, and an `openui_prompt.md` for refining the UI shell in
  OpenUI.
- The `web-ui` Nginx proxy allows long-running `/v1/` requests so the browser
  can receive the final `aes_result` after FEniCS execution and artifact
  postprocessing. Without this, LangGraph may finish and store artifacts after
  the browser has already received a proxy timeout.

Current limitation: provider-owned `mcp://...` solver outputs such as
`solution.xdmf` and `solution.h5` are still references unless a provider
resource-read/copy step materializes them into AES-owned `/artifacts`. The
VTK.js viewport becomes active when the manifest contains a browser-fetchable
`.vtu`, `.vtp`, `.vtk`, or `.vtkjs` artifact URL. Until then the viewer shows
diagnostics, SVG preview, and raw artifact references. Later postprocessors can
add PyVista/Matplotlib PNG snapshots, MP4/GIF transient animations, and actual
VTK.js dataset conversion.

### Future Unified AES Workbench

The current and long-term user experience is a single OpenUI-inspired AES
workbench: one browser window containing chat, run status, artifacts,
diagnostics, and the interactive VTK.js result viewer. The integrated product
UI for AES is `web-ui`.

```mermaid
flowchart TD
    A["web-ui / AES Workbench / OpenUI"] --> LP["Left pane"]
    A --> RP["Right pane"]

    LP --> B["Native AES chat panel"]
    RP --> C["Run status"]
    RP --> D["Artifact browser"]
    RP --> E["VTK.js viewer"]

    B --> F["AES OpenAI-compatible API"]
    C --> G["AES run state"]
    D --> H["AES artifact API"]
    E --> H

    F --> I["LangGraph"]
    I --> J["FEniCS runner"]
    J --> K["Artifact store"]
    K --> H
```

The first implemented Workbench session model is browser-local:

```mermaid
flowchart TD
    A["Load http://127.0.0.1:3000 or tunnel port"] --> B{"Stored Workbench user?"}
    B -->|no| C["Show login screen"]
    C --> D["Create local user session"]
    B -->|yes| D
    D --> E["Load saved conversations from localStorage"]
    E --> F["Select active chat"]
    F --> G["Left pane chat + progress log"]
    F --> H["Right pane latest result"]
    G --> I["POST /v1/chat/completions"]
    I --> J["Visible AES progress steps while request runs"]
    J --> K["Final response with aes_result"]
    K --> L["Persist turns, result, artifacts in localStorage"]
    L --> H
```

This is not a security boundary yet. It gives the prototype stable browser
sessions, saved chats, and refresh persistence. A later production account
system can replace the localStorage layer with a server-side conversation API.

Implementation direction:

- Run `web-ui` as the default UI container on `ai-stack-net`, published on
  host port `3000`.
- Keep building `web-ui/` as the `aes-workbench` application rather than a
  viewer-only page.
- Use the native chat panel that calls `/v1/chat/completions` with model
  `aes-agent`.
- Show a Workbench-side progress log during long AES requests so users can see
  the expected flow instead of a frozen chat.
- Persist per-user local conversations and the latest `aes_result` so refreshes
  do not clear the chat or result pane.
- Add a run panel that reads the latest `aes_result` and artifact manifest.
- Add artifact and visualization panels driven by `viewer_manifest.json`.
- CORS is configured through `AES_CORS_ORIGINS`; dev/prod defaults allow
  `http://127.0.0.1:5173` and `http://localhost:5173` for local Vite
  development. In container deployment, Nginx same-origin proxying avoids CORS
  for normal browser use.

## Artifact Store

Providers return structured results and artifact references. AES owns the final
artifact manifest and storage policy through the local `artifact_store` tool.

The first implementation writes:

- `manifest.json`,
- `summary.md`.

Both files are written below `AES_ARTIFACT_ROOT`, mounted as `/artifacts` in the
LangGraph containers. Provider workspaces, such as the FEniCS `/workspace`, are
treated as scratch or provider-owned storage, not as final AES output locations.
For generated-code runs, AES also materializes inline artifacts returned by
`fenics_code_solve`, currently including the checked `solve.py`, captured
`diagnostics.json`, stdout/stderr logs, and visualization files from
`visualization_postprocess` when available.

## MCP Provider Layer

`mcp/` is a provider-management layer for multiple MCP servers. The central
`mcp/compose.mcp.yaml` file follows the same pattern as the top-level deployment
entrypoints: it includes provider-owned Compose files instead of defining every
service directly.

```text
mcp/compose.mcp.yaml
  -> mcp/providers/fenics/compose.yaml
  -> mcp/providers/retrieval/compose.yaml
  -> mcp/providers/filesystem/compose.yaml
```

The central `mcp/providers.yaml` file is also only an index. Provider-specific
AES/governance metadata is stored locally:

```text
mcp/providers.yaml
  -> mcp/providers/fenics/provider.yaml
  -> mcp/providers/retrieval/provider.yaml
  -> mcp/providers/filesystem/provider.yaml
```

Each provider should own:

- compose configuration,
- provider manifest,
- allowlist,
- schema snapshot,
- workspace,
- smoke tests,
- README with operational notes.

For now, providers are optional long-running services selected by Docker Compose
profiles. On-demand provider startup can be added later with a controller or
Kubernetes-style job lifecycle, but it is deliberately not part of the first
Compose-based version.

## Deployment Entry Points

The deployment layer has only two top-level entrypoints:

```text
deploy/compose.dev.yaml
deploy/compose.prod.yaml
```

Both files include the component-owned service definitions. The dev/prod
difference is intentionally concentrated in the Ollama component:

```text
ollama/ollama-server.dev.yaml
ollama/ollama-server.prod.yaml
```
