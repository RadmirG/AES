# LangGraph Architecture

The `langgraph/` component is the AES orchestration service. It exposes the
OpenAI-compatible `aes-agent` API, owns the LangGraph workflow, calls Ollama for
structured reasoning, selects high-level tools, and writes final user-facing
answers from graph state.

```mermaid
flowchart TD
    A["HTTP request<br/>/v1/chat/completions or /invoke"] --> B["FastAPI adapter"]
    B --> C["OpenAI chat adapter"]
    C --> D["Active AES request"]
    D --> E["LangGraph StateGraph"]
    E --> F["Ollama JSON calls"]
    E --> G["AES tool registry"]
    G --> H["MCP-backed tools"]
    G --> I["Local tools"]
    H --> J["Provider containers"]
    I --> K["Artifact store"]
    J --> K
    K --> L["Deterministic final renderer"]
    L --> M["OpenAI-compatible response<br/>aes_result included"]
```

## Ownership

`langgraph/` owns:

- the AES FastAPI service,
- the OpenAI-compatible API surface,
- `AgentState`,
- LangGraph nodes and routing,
- Ollama prompt builders and response parsing,
- high-level tool registry,
- MCP client boundary,
- generated-code safety checks and repair loop,
- final AES answer rendering,
- artifact-store invocation.

It does not own:

- Ollama model storage,
- FEniCS/DOLFINx installation,
- browser UI state,
- provider workspaces,
- production deployment topology.

## Graph Flow

The current graph is a guarded workflow, not a free-form agent loop.

```mermaid
flowchart TD
    A["ingest_problem"] --> B["detect_request_intent"]
    B --> C{"Engineering/ \n PDE request?"}
    C -->|no| D["handle_non_engineering_request"]
    C -->|yes| E["classify_problem"]
    E --> F["extract_mathematical_structure"]
    F --> G["check_problem_completeness"]
    G --> H{"Complete enough?"}
    H -->|no| I["generate_clarification"]
    H -->|yes| J["select_formulation"]
    J --> K["validate_formulation"]
    K --> L{"Valid?"}
    L -->|no| I
    L -->|yes| M["select_solution_mode"]
    M --> N{"Requested output mode"}
    N -->|ask output| I
    N -->|formulation summary| O["generate_formulation_summary"]
    N -->|code/execute| P["prepare_numerical_recipe"]
    P --> Q{"Recipe ready?"}
    Q -->|no| I
    Q -->|yes| R["select_tools"]
    R --> S["execute_tools"]
    D --> T["select_artifact_store"]
    I --> T
    O --> T
    T --> S
    S --> U["generate_artifact"]
    U --> V["END"]
```

## State Contract

`AgentState` is the current-run state. It should stay focused on the active
request and should not become a general memory database.

Important state groups:

- request and intent: `raw_user_input`, `request_intent`, `intent_reason`,
- problem extraction: `problem_class`, `domain_info`, `pde_info`,
  `coefficient_info`, `source_info`, `bc_info`, `initial_condition_info`,
  `time_info`,
- clarification and validation: `missing_information`,
  `clarification_questions`, `selected_formulation`, `validation_status`,
  `validation_errors`,
- execution planning: `solution_mode`, `numerical_recipe_status`,
  `numerical_recipe`, `numerical_recipe_errors`,
- tool phase: `selected_tools`, `tool_execution_status`, `tool_results`,
  `tool_errors`,
- final response: `generated_artifact`, `agent_status`, `next_action`.

Long-term memory, chat history, retrieval indexes, and project knowledge should
live outside `AgentState` and be injected through explicit nodes/tools.

## Solution Modes

AES classifies the requested output before selecting tools.

```mermaid
flowchart TD
    A["Validated problem"] --> B["select_solution_mode"]
    B --> C{"Mode"}
    C -->|"PDE text only"| D["needs_output_intent"]
    C -->|"Explain formulation"| E["formulation_summary"]
    C -->|"Generate file"| F["generate_fenics_code"]
    C -->|"Execute solve"| G["execute_generated_fenics_code"]
    C -->|"User code"| H["execute_user_fenics_code"]
    C -->|"Known smoke workflow"| I["deterministic_mcp_recipe"]
```

AES should not silently execute numerical tools for a PDE-only prompt. It asks
whether the user wants a formulation summary, generated code, or execution.

## Tool Layer

LangGraph exposes high-level AES tools, not raw provider tools. The current
important tools are:

- `fenics_code_solve`: generate/check/execute DOLFINx Python in a provider
  sandbox,
- `fenics_forward_solve`: older deterministic MCP recipe path for constrained
  smoke workflows,
- `visualization_postprocess`: create preview and viewer metadata from solver
  outputs,
- `artifact_store`: materialize final AES artifacts and manifests.

```mermaid
flowchart TD
    A["select_tools"] --> B["execute_tools"]
    B --> C["fenics_code_solve"]
    B --> D["visualization_postprocess"]
    B --> E["artifact_store"]
    C --> F["FEniCS code-runner MCP"]
    F --> G["provider artifact refs"]
    G --> D
    D --> H["preview/viewer artifacts"]
    H --> E
```

## Generated-Code Repair Loop

For LLM-generated FEniCS code, AES attempts bounded repair. User-provided code
is not auto-rewritten.

```mermaid
flowchart TD
    A["LLM-generated solve.py"] --> B["Strip invalid control characters"]
    B --> C["General Python extraction + syntax checker"]
    C --> D["FEniCS-specific safety allowlist"]
    D --> E{"Safe?"}
    E -->|no, attempts left| F["LLM repair with syntax/safety report"]
    F --> B
    E -->|no, no usable repairs| G["Deterministic fallback for supported simple PDEs"]
    G --> B
    E -->|yes| H["Execute in fenics-code-runner"]
    H --> I{"Return code 0?"}
    I -->|no| J["LLM repair with stdout/stderr/diagnostics"]
    J --> B
    I -->|yes| K["Return code, diagnostics, sampled u(x,y,t), artifact refs"]
```

Repair attempts are bounded by `DOLFINX_CODE_REPAIR_ATTEMPTS`.
The generic checker lives in `aes_agent/python_checker.py` and is intentionally
not FEniCS-specific: it extracts Python from common LLM response shapes, strips
invalid control characters, and catches syntax errors before the stricter
FEniCS import/call allowlist runs. If bounded static repairs return no usable
Python for a supported simple heat/Poisson-style problem, AES falls back only at
that point instead of repeatedly validating the same broken script.

For generated-code runs, scripts should write sampled field data for the
numerical solution into `diagnostics.json` under `field_samples`: stationary
problems provide \(u(x,y)\), while transient problems provide \(u(x,y,t)\).
The visualization layer can then render the actual sampled solution field in
the Workbench even before a full VTK `.vtu` or `.vtkjs` conversion exists.

## API Boundary

The public API exposes `aes-agent`; this is an AES wrapper model, not a raw LLM.
The raw backend model is selected through environment:

```text
AES_OLLAMA_MODEL -> OLLAMA_MODEL -> Ollama /api/generate payload model
```

The OpenAI-compatible adapter normally uses the latest user turn as the active
request. The controlled exception is AES-requested output clarification: when
AES asks what output the user wants, a short follow-up such as `execution with
stored result artifacts` is merged with the previous PDE problem.

## Tests

Focused tests live under `langgraph/tests/` and cover graph routing, parsing,
MCP client behavior, FEniCS tools, artifact storage, visualization, and API
behavior.
