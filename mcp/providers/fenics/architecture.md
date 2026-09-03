# FEniCS Provider Architecture

The FEniCS provider is the numerical execution boundary for DOLFINx/FEniCS
workflows. AES does not install or run FEniCS inside the LangGraph container.
All FEniCS execution happens in provider containers.

```mermaid
flowchart TD
    A["LangGraph AES"] --> B["typed DOLFINx compiler<br/>high-level AES tool"]
    A --> C["fenics_forward_solve<br/>deterministic smoke path"]

    B --> D["fenics-code-runner MCP"]
    C --> E["dolfinx-mcp MCP"]

    D --> F["Run checked solve.py"]
    E --> G["Call low-level DOLFINx workflow tools"]

    F --> H["stdout/stderr/diagnostics/files"]
    G --> I["MCP call evidence/results"]

    H --> J["AES artifact_store"]
    I --> J
```

## Services

This provider owns two services:

- `dolfinx-mcp`: external workflow-oriented MCP server used by the older
  deterministic `fenics_forward_solve` path,
- `fenics-code-runner`: AES-owned MCP script runner used by the typed compiler
  and the optional experimental generated-code path.

The typed compiler path is the preferred architecture. The low-level
deterministic path remains useful for provider smoke tests and constrained
workflows.

## Typed Compiler And Execution Path

```mermaid
flowchart TD
    A["Validated PDEProblemSpec"] --> C["Versioned DOLFINx compiler"]
    B["Validated MeshArtifact"] --> C
    C --> D["AES syntax and safety preflight"]
    D --> E{"Safe?"}
    E -->|no| R["Compiler error report"]
    E -->|yes| F["run_python_script via fenics-code-runner"]
    F --> G["Runner writes /workspace/code-runs/<run_id>/solve.py"]
    G --> H["Execute with timeout"]
    H --> I["Capture stdout/stderr"]
    H --> J["Collect produced files"]
    I --> K["Return MCP result"]
    J --> K
    K --> L["AES result review + artifact_store"]
```

The code runner exposes:

```text
run_python_script(filename, code, timeout_seconds, inputs)
```

It returns:

- provider run id,
- return code,
- runtime seconds,
- timeout,
- stdout/stderr,
- diagnostics if `diagnostics.json` is produced,
- provider artifact references for generated files.

`inputs` accepts only governed `mcp://meshing/workspace/...` references. The
runner copies the selected `mesh.msh` through a read-only mount into the
isolated execution directory. Free-form LLM code is disabled by default and
requires `AES_EXPERIMENTAL_LLM_CODE_ENABLED=true`.

## Deterministic MCP Path

The deterministic path maps a constrained numerical recipe to low-level MCP tool
calls.

```mermaid
flowchart TD
    A["numerical_recipe"] --> B["reset_session"]
    B --> C["create mesh"]
    C --> D["create function space"]
    D --> E["set material/source"]
    E --> F["define variational form"]
    F --> G["apply boundary condition"]
    G --> H["solve"]
    H --> I["diagnostics/export/plot/report"]
```

This path is intentionally narrow because every new PDE family can require new
tool argument logic. It should not be the primary path for general PDE work.

## Safety Boundary

Security policy:

- raw user code is never executed in the LangGraph container,
- LLM-generated code must pass static checks before execution,
- user-provided code is checked and either accepted or rejected; AES does not
  auto-rewrite user code,
- `run_custom_code` remains blocked on the external `dolfinx-mcp` service,
- arbitrary execution is isolated in `fenics-code-runner`.

## Artifact Ownership

Provider workspaces are scratch spaces. AES-owned artifacts are materialized by
the LangGraph artifact store.

```mermaid
flowchart LR
    A["/workspace/code-runs/<run_id>"] --> B["provider artifact refs"]
    B --> C["LangGraph artifact_store"]
    C --> D["/artifacts/<aes_run_id>"]
    D --> E["/artifacts HTTP API"]
    E --> F["web-ui result pane"]
```

Current limitation: raw `mcp://...` solution references must be copied or
converted into AES-owned `/artifacts` before the browser can directly fetch
them.

## Operational Inputs

LangGraph uses:

```text
DOLFINX_MCP_URL=http://dolfinx-mcp:8000/mcp
DOLFINX_MCP_EXECUTE=true|false
DOLFINX_CODE_MCP_URL=http://fenics-code-runner:8000/mcp
DOLFINX_CODE_EXECUTE=true|false
DOLFINX_CODE_GENERATION_ATTEMPTS=2
DOLFINX_CODE_REPAIR_ATTEMPTS=2
AES_EXPERIMENTAL_LLM_CODE_ENABLED=false
```

Production enables generated-code execution by default. Development may keep it
disabled until the provider is available.
