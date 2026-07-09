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
  providers.yaml              # provider index
  providers/
    fenics/provider.yaml      # provider-owned governance manifest
    retrieval/provider.yaml
    filesystem/provider.yaml
  contracts/
```

The central `compose.mcp.yaml` is only an MCP entrypoint. It includes the
provider-owned Compose files:

```text
mcp/compose.mcp.yaml
  -> providers/fenics/compose.yaml
  -> providers/retrieval/compose.yaml
  -> providers/filesystem/compose.yaml
```

This keeps every provider responsible for its own image, ports, volumes,
profiles, workspace, and operational README.

The central `providers.yaml` is only a provider index:

```text
mcp/providers.yaml
  -> providers/fenics/provider.yaml
  -> providers/retrieval/provider.yaml
  -> providers/filesystem/provider.yaml
```

Each provider owns its AES/governance metadata in its local `provider.yaml`,
including transport, profile, URLs, allowlist, schema snapshot, wrapper tools,
contracts, and operational notes.

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

Production defaults to live FEniCS execution and should be started with the
`fenics` profile. Development defaults to planning mode unless
`DOLFINX_MCP_EXECUTE=true` is exported.

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

## Provider Lifecycle

In the current Docker Compose setup, MCP providers are optional long-running
services selected with profiles. For example, the FEniCS provider starts only
when the `fenics` profile is active.

On-demand provider startup is a later architecture step. It would require a
controller that can start a provider before tool execution, wait for readiness,
run the tool, collect artifacts, and shut the provider down. Kubernetes Jobs,
a Docker API controller, or a workflow engine could provide that behavior later.
For the first reliable version, long-running optional providers are simpler and
easier to debug.
