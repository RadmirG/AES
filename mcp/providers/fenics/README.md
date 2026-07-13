# FEniCS/DOLFINx MCP Provider

This provider owns two FEniCS-facing MCP services:

- `dolfinx-mcp`: the external workflow-oriented MCP server used by the
  deterministic `fenics_forward_solve` path.
- `fenics-code-runner`: the AES-owned script-runner service used by the
  flexible generated-code path.

Both services run inside FEniCS/DOLFINx-capable containers. AES does not install
FEniCS inside the LangGraph container.

AES does not install FEniCS. AES only:

1. validates the user problem through LangGraph,
2. builds a numerical recipe,
3. selects the high-level `fenics_forward_solve` wrapper,
4. calls this provider through MCP,
5. stores final manifests through the AES artifact store.

## Build Provider Image

```bash
git clone https://github.com/ekstanley/ccFenics-plugin.git
cd ccFenics-plugin
docker build -t dolfinx-mcp:latest .
```

The `fenics-code-runner` image is built from the local
`mcp/providers/fenics/code_runner/Dockerfile`. It uses `dolfinx-mcp:latest` as
its base image so the same FEniCS/DOLFINx runtime is available for generated
scripts.

## Start Provider

From the AES repository root:

```bash
docker compose -f mcp/compose.mcp.yaml --profile fenics up -d
```

The provider is reachable from AES on the Docker network at:

```text
http://dolfinx-mcp:8000/mcp
```

The generated-code runner is reachable from AES on the Docker network at:

```text
http://fenics-code-runner:8000/mcp
```

It is reachable from the host at:

```text
http://127.0.0.1:8003/mcp
```

The generated-code runner is reachable from the host at:

```text
http://127.0.0.1:8006/mcp
```

## Safety Boundary

AES should expose only high-level wrapper tools to the LLM. The low-level
DOLFINx MCP tools are allowlisted in `allowlist.yaml`.

`run_custom_code` remains blocked on the external `dolfinx-mcp` service.
Generated/user-provided Python code may execute only through
`fenics-code-runner` after AES has produced or received the code, run static
safety checks, and selected the execution mode.

The code runner exposes one tool:

```text
run_python_script(filename, code, timeout_seconds)
```

The runner writes the script into an isolated `/workspace/code-runs/<run_id>/`
directory, executes it with a timeout, captures stdout/stderr, and returns
provider artifact references for produced files.
