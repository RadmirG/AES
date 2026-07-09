# FEniCS/DOLFINx MCP Integration

AES integrates FEniCS through one high-level AES tool:

```text
fenics_forward_solve
```

The tool maps a validated AES numerical recipe to an allowlisted DOLFINx MCP
workflow. The LLM should not call low-level DOLFINx tools directly and should
not generate arbitrary FEniCS Python code.

## First Supported Workflows

- Forward Poisson / stationary diffusion problems.
- Forward heat-equation problems.
- Unit square or rectangle domains.
- Scalar P1 Lagrange finite elements.
- Dirichlet boundary conditions.
- CG + Hypre AMG solver defaults.
- XDMF, PNG, diagnostics, and HTML report outputs.

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
