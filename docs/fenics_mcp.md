# FEniCS/DOLFINx MCP Integration

AES integrates FEniCS through one high-level AES tool:

```text
fenics_forward_solve
```

The tool maps a validated AES numerical recipe to an allowlisted DOLFINx MCP
workflow. The LLM should not call low-level DOLFINx tools directly and should
not generate arbitrary FEniCS Python code.

FEniCS execution is followed by the AES-owned `artifact_store` tool. The MCP
provider may create temporary provider workspace files, but the agent records
final run metadata in an AES artifact manifest.

## First Supported Workflows

- Forward Poisson / stationary diffusion problems.
- Forward heat-equation problems.
- Unit square or rectangle domains.
- Scalar P1 Lagrange finite elements.
- Dirichlet boundary conditions.
- CG + Hypre AMG solver defaults.
- XDMF, PNG, diagnostics, and HTML report outputs.

## Result Contract

`fenics_forward_solve` returns a normalized `fenics_result` object with:

- provider status,
- planned and executed MCP tool names,
- requested artifacts,
- available provider artifact references,
- diagnostics,
- errors and warnings.

The artifact references are not final user storage locations. They are provider
references such as `mcp://dolfinx/workspace/heat_solution.png`. The
`artifact_store` tool consumes these references and writes an AES-owned
`manifest.json` plus `summary.md` under `AES_ARTIFACT_ROOT`.

## Execution Modes

The development stack returns a planned MCP workflow without contacting a live
solver unless explicitly overridden:

```text
DOLFINX_MCP_EXECUTE=false
```

To execute against a running `dolfinx-mcp` Streamable HTTP server:

```text
DOLFINX_MCP_URL=http://dolfinx-mcp:8000/mcp
DOLFINX_MCP_EXECUTE=true
DOLFINX_MCP_TIMEOUT=300
```

The production stack is configured this way by default in
`langgraph/langgraph.prod.yaml`. Start production with the `fenics` Compose
profile so the `dolfinx-mcp` container is available.

The flexible generated-code path has a separate execution flag:

```text
DOLFINX_CODE_EXECUTE=true
DOLFINX_CODE_TIMEOUT=300
```

Production enables this flag by default. This only tells AES to attempt
execution of checked generated/user-provided `solve.py` code. The provider must
still expose a safe script-runner MCP tool, currently expected under one of
these names:

```text
run_python_script
execute_python_script
run_script
```

If no such provider tool exists, AES should report a blocked tool result rather
than a completed numerical solve.

The external server can be built from:

```text
https://github.com/ekstanley/ccFenics-plugin
```

The referenced server supports Docker execution and a Streamable HTTP mode:

```text
docker run -p 8000:8000 dolfinx-mcp --transport streamable-http --host 0.0.0.0
```

## Safety Boundary

The first AES wrapper allowlists only workflow tools such as mesh creation,
function-space setup, variational-form definition, solving, export, plotting,
and reporting.

`run_custom_code` is intentionally not allowlisted in the first version.

## Current Limitation

The exact low-level argument names of the external DOLFINx MCP tools may need
one compatibility pass against the live server schemas. The AES side is already
structured so that only `fenics_mcp.py` should need adjustment for that pass.
