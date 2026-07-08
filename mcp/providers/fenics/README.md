# FEniCS/DOLFINx MCP Provider

This provider runs the external `dolfinx-mcp` MCP server. It is responsible for
the actual FEniCS/DOLFINx installation and numerical execution.

AES does not install FEniCS. AES only:

1. validates the user problem through LangGraph,
2. builds a numerical recipe,
3. selects the high-level `fenics_forward_solve` wrapper,
4. calls this provider through MCP.

## Build Provider Image

```bash
git clone https://github.com/ekstanley/ccFenics-plugin.git
cd ccFenics-plugin
docker build -t dolfinx-mcp:latest .
```

## Start Provider

From the AES repository root:

```bash
docker compose -f mcp/compose.mcp.yaml --profile fenics up -d
```

The provider is reachable from AES on the Docker network at:

```text
http://dolfinx-mcp:8000/mcp
```

It is reachable from the host at:

```text
http://127.0.0.1:8003/mcp
```

## Safety Boundary

AES should expose only the high-level `fenics_forward_solve` tool to the LLM.
The low-level DOLFINx MCP tools are allowlisted in `allowlist.yaml`.

`run_custom_code` is intentionally blocked in the first integration.

