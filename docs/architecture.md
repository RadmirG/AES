# AES System Architecture

This document is the central architecture map for AES. It shows how the main
components interact. Component-internal details live beside the code in each
component's own `architecture.md`.

## Component Docs

```mermaid
flowchart TD
    A["docs/architecture.md<br/>System map"] --> B["langgraph/architecture.md<br/>Orchestration and graph"]
    A --> C["web-ui/architecture.md<br/>AES Workbench"]
    A --> D["mcp/architecture.md<br/>Provider layer"]
    A --> E["mcp/providers/fenics/architecture.md<br/>FEniCS providers"]
    A --> F["mcp/providers/retrieval/architecture.md<br/>Planned retrieval provider"]
    A --> G["mcp/providers/filesystem/architecture.md<br/>Planned filesystem provider"]
    A --> H["ollama/architecture.md<br/>Model runtime"]
    A --> I["deploy/architecture.md<br/>Compose topology"]
    A --> J["docs/artifact_store.md<br/>Artifact ownership"]
    A --> K["database/architecture.md<br/>PostgreSQL + pgvector"]
```

## System Overview

AES is an agentic engineering system for PDE/FEM workflows. The browser talks
to an AES-native Workbench. The Workbench calls the LangGraph service through an
OpenAI-compatible API. LangGraph orchestrates the engineering workflow, calls
Ollama for structured model reasoning, invokes governed tools, executes FEniCS
workloads through MCP providers, and stores final artifacts through the AES
artifact store.

```mermaid
flowchart LR
    subgraph CLIENT["Client"]
        direction TB
        user["User"] --> web["web-ui"]
    end

    subgraph CORE["AES Core"]
        direction TB
        api["LangGraph API"] --> orchestrator["StateGraph"]
    end

    subgraph COMPUTE["Models and Tools"]
        direction TB
        ollama["Ollama"]
        mcp["MCP Providers"]
    end

    subgraph PERSISTENCE["Persistence"]
        direction TB
        postgres[("PostgreSQL + pgvector")]
        artifacts[("Artifact Store<br/>files")]
    end

    web --> api
    orchestrator --> ollama
    orchestrator --> mcp
    api --> postgres
    orchestrator --> postgres
    orchestrator --> artifacts
```

The database component now deploys one PostgreSQL container with `pgvector`, a
versioned migration job, separate schemas, and restricted runtime roles. The
implemented identity slice stores users and opaque server sessions. Large
numerical files remain in the artifact store; chat, workflow, checkpoint,
artifact-metadata, and retrieval persistence follow in later slices.

```mermaid
flowchart LR
    U["User"] --> W["web-ui<br/>AES Workbench"]
    W -->|"same-origin API"| API["LangGraph FastAPI"]
    API --> G["LangGraph StateGraph"]
    API --> DB[("users, chats, runs")]
    G --> DB
    G --> O["Ollama"]
    G --> T["AES tool registry"]
    T --> MCP["FEniCS MCP providers"]
    T --> RET["Retrieval MCP"]
    RET --> VEC[("pgvector embeddings")]
    T --> AS["artifact_store"]
    AS --> FILES["/artifacts/<run_id>"]
    AS --> META[("artifact metadata")]
    FILES -->|"same-origin /artifacts"| W
```

## Source Layout

```text
AES/
  langgraph/     # orchestration service, graph, tools, API
  mcp/           # MCP provider layer and provider governance
  ollama/        # model runtime compose files and model manifests
  web-ui/        # AES Workbench browser application
  database/      # PostgreSQL/pgvector persistence architecture and service
  deploy/        # dev/prod Compose entrypoints
  docs/          # cross-component documentation
```

## Main Runtime Flow

```mermaid
sequenceDiagram
    participant User
    participant UI as web-ui
    participant LG as LangGraph API
    participant O as Ollama
    participant MCP as FEniCS MCP Provider
    participant DB as PostgreSQL pgvector
    participant Store as Artifact Store

    User->>UI: Submit PDE / engineering request
    UI->>LG: Submit authenticated chat message
    LG->>DB: Store message and create AES run
    LG->>LG: Run LangGraph StateGraph
    LG->>DB: Store checkpoints and run events
    LG->>O: Structured JSON reasoning calls
    O-->>LG: Parsed model output
    LG->>MCP: Execute governed MCP tool if needed
    MCP-->>LG: stdout, diagnostics, provider artifact refs
    LG->>Store: Store manifest, summary, inline artifacts
    Store-->>LG: AES artifact run id and URLs
    LG->>DB: Store tool/artifact metadata and final run status
    LG->>DB: Store assistant message
    LG-->>UI: Final answer + aes_result
    UI->>Store: Load /artifacts links through proxy
```

Identity/session operations in this sequence are implemented. Message, run,
checkpoint, tool, and artifact-metadata operations describe the next
persistence slices; the current Workbench still stores conversations in
browser `localStorage` and the graph invokes without a persistent checkpointer.

## Component Responsibilities

| Component | Responsibility | Detailed Architecture |
| --- | --- | --- |
| `web-ui/` | Browser Workbench, authenticated session UI, local chat cache, progress turns, result workspace, VTK.js shell | [`web-ui/architecture.md`](../web-ui/architecture.md) |
| `langgraph/` | FastAPI auth/API boundary, LangGraph workflow, state, routing, Ollama calls, tool execution, final answer renderer | [`langgraph/architecture.md`](../langgraph/architecture.md) |
| `ollama/` | LLM runtime, dev/prod model manifests, pull automation, model warmup/runtime settings | [`ollama/architecture.md`](../ollama/architecture.md) |
| `mcp/` | Provider registry, provider manifests, allowlists, contracts, Compose provider includes | [`mcp/architecture.md`](../mcp/architecture.md) |
| `mcp/providers/fenics/` | DOLFINx/FEniCS execution boundary, code runner, deterministic MCP smoke path | [`mcp/providers/fenics/architecture.md`](../mcp/providers/fenics/architecture.md) |
| `database/` | PostgreSQL schemas, pgvector retrieval index, LangGraph checkpoints, migrations, backups, and database service roles | [`database/architecture.md`](../database/architecture.md) |
| `deploy/` | Dev/prod Compose entrypoints and profile composition | [`deploy/architecture.md`](../deploy/architecture.md) |
| artifact store | AES-owned run manifests, summaries, materialized artifacts, public artifact URLs | [`docs/artifact_store.md`](artifact_store.md) |
| observability | Component-prefixed logs, content preview controls, live Docker log workflow | [`docs/logging.md`](logging.md) |

## Integration Contracts

### Browser To LangGraph

The Workbench calls the LangGraph API through the same-origin Nginx proxy:

```text
Browser -> web-ui:3000
web-ui /api/*        -> http://langgraph:8001/api/*
web-ui /v1/*         -> http://langgraph:8001/v1/*
web-ui /artifacts/*  -> http://langgraph:8001/artifacts/*
```

The browser authenticates through `/api/auth/login`. LangGraph stores the
session server-side and returns an opaque `HttpOnly` cookie; protected chat,
invoke, and artifact requests carry that cookie through the same-origin proxy.

The public model is:

```text
aes-agent
```

This is an AES wrapper model, not the raw Ollama model.

### LangGraph To Ollama

LangGraph calls Ollama through the configured internal service URL.

```mermaid
flowchart LR
    A["AES_OLLAMA_MODEL"] --> B["Compose env"]
    B --> C["OLLAMA_MODEL"]
    C --> D["LangGraph Ollama client"]
    D --> E["Ollama /api/generate"]
```

### LangGraph To MCP Providers

LangGraph exposes only high-level AES wrapper tools to the workflow. Low-level
provider tools remain behind wrapper code and allowlists.

```mermaid
flowchart LR
    A["LangGraph tool registry"] --> B["AES wrapper tool"]
    B --> C["MCP client"]
    C --> D["Provider MCP server"]
    D --> E["Provider tool"]
```

### Provider Outputs To AES Artifacts

Providers may return `mcp://...` references, inline artifacts, diagnostics, or
stdout/stderr. The AES artifact store owns the final user-facing run directory.

```mermaid
flowchart LR
    A["provider result"] --> B["tool_results"]
    B --> C["artifact_store"]
    C --> D["/artifacts/<run_id>/manifest.json"]
    C --> E["/artifacts/<run_id>/summary.md"]
    C --> F["materialized files"]
    F --> G["web-ui result pane"]
```

## Design Principles

- Keep LangGraph as the explicit workflow and routing spine.
- Keep model calls behind nodes and structured parsers.
- Expose high-level AES tools to the graph, not every low-level MCP tool.
- Keep heavy execution backends in provider containers.
- Keep final artifact policy in AES, not provider scratch workspaces.
- Keep browser clients and LLMs away from direct database access; persistence
  is exposed through authenticated APIs and typed retrieval tools.
- Keep full `AgentState` snapshots in the LangGraph checkpointer while
  projecting queryable run, event, tool, and artifact metadata into dedicated
  tables.
- Keep large numerical artifacts outside PostgreSQL and store only their
  ownership, status, checksum, metadata, and URI in the database.
- Treat artifact storage as workflow traceability, not only successful solver
  output.
- Use Mermaid diagrams as the default architecture communication format.
- Keep deployment composition thin: top-level Compose files include
  component-owned service definitions.

## Current Main Paths

### Flexible FEniCS Generated-Code Path

```mermaid
flowchart TD
    A["User PDE request"] --> B["LangGraph intent + problem extraction"]
    B --> C["Requested output mode"]
    C --> D["LLM generate DOLFINx solve.py"]
    D --> E["Static code safety check"]
    E -->|safe| F["Run in fenics-code-runner"]
    E -->|unsafe| G["Repair generated code or reject"]
    F --> H{"Run successful?"}
    H -->|no| I["LLM repair loop with stderr"]
    I --> D
    H -->|yes| J["Visualization postprocess"]
    J --> K["Artifact store"]
    K --> L["Final AES response + result links"]
```

### Deterministic MCP Smoke Path

```mermaid
flowchart TD
    A["Known constrained workflow"] --> B["numerical_recipe"]
    B --> C["fenics_forward_solve"]
    C --> D["dolfinx-mcp low-level calls"]
    D --> E["MCP call evidence"]
    E --> F["Artifact store"]
```

The generated-code path is the preferred flexible path. The deterministic MCP
path remains for controlled smoke workflows and provider contract validation.

## Deployment Topology

```mermaid
flowchart TD
    A["deploy/compose.dev.yaml"] --> DB["PostgreSQL + migration"]
    A --> B["ollama dev"]
    A --> C["web-ui"]
    A --> D["mcp providers"]
    A --> E["langgraph dev"]

    F["deploy/compose.prod.yaml"] --> DB
    F --> G["ollama prod"]
    F --> C
    F --> D
    F --> H["langgraph prod"]

    I["--profile models"] --> J["ollama-model-puller"]
    K["--profile fenics"] --> L["dolfinx-mcp + fenics-code-runner"]
```

See [`deploy/architecture.md`](../deploy/architecture.md) and
[`docs/deployment.md`](deployment.md) for commands.

## Planned Extensions

- Materialize provider-owned raw solution files into AES-owned `/artifacts`.
- Add real VTK conversion for `.xdmf`/`.h5` solution outputs.
- Add retrieval provider implementation for project/domain RAG.
- Migrate Workbench chats, run progress, artifact ownership, and LangGraph
  checkpoints from process/browser memory to server-side PostgreSQL
  persistence; identity and login sessions are already implemented.
- Add lifecycle controller for on-demand provider startup when Compose profiles
  are no longer enough.
