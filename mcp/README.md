# AES MCP Provider Layer

This directory owns MCP provider infrastructure for AES.

AES itself remains the LangGraph orchestration host and MCP client. Provider
containers live here and expose external capabilities such as FEniCS/DOLFINx,
retrieval, filesystem access, symbolic computation, or other engineering tools.

The design goal is to keep tool execution modular and governed:

- each provider has its own container/process boundary,
- AES calls providers through MCP transports,
- provider tools are discovered with `tools/list`,
- AES exposes only approved high-level wrapper tools to the LLM,
- low-level MCP tools are allowlisted and contract-tested before live use.

## Layout

```text
mcp/
  compose.mcp.yaml
  providers.yaml
  providers/
    fenics/
    retrieval/
    filesystem/
  contracts/
```

## Execution Modes

The LangGraph service can run in planning mode without any MCP provider:

```text
DOLFINX_MCP_EXECUTE=false
```

Live FEniCS execution requires the `dolfinx-mcp` provider container:

```text
DOLFINX_MCP_EXECUTE=true
DOLFINX_MCP_URL=http://dolfinx-mcp:8000/mcp
```

## First Provider

The first concrete provider is `fenics`, backed by the external
`dolfinx-mcp` image built from:

```text
https://github.com/ekstanley/ccFenics-plugin
```

Build that image separately:

```bash
git clone https://github.com/ekstanley/ccFenics-plugin.git
cd ccFenics-plugin
docker build -t dolfinx-mcp:latest .
```

Then start the AES MCP providers:

```bash
docker compose -f mcp/compose.mcp.yaml --profile fenics up -d
```

