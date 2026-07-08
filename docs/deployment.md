# AES Deployment

## Required Docker Network

Create the shared network once:

```bash
docker network create ai-stack-net
```

## Existing Per-Service Compose Files

The original service files remain valid:

```bash
docker compose -f ollama/ollama-server.yaml up -d
docker compose -f open-webui/open-webui.yaml up -d
docker compose -f langgraph/langgraph.yaml up -d --build
```

## New Deployment Layer

The `deploy/` directory provides combined compose files.

Development LangGraph only:

```bash
docker compose -f deploy/compose.dev.yaml up -d --build
```

Ollama GPU runtime:

```bash
docker compose -f deploy/compose.gpu.yaml up -d
```

Full stack without live FEniCS provider:

```bash
docker compose -f deploy/compose.full.yaml up -d --build
```

Full stack with the FEniCS MCP provider:

```bash
docker compose -f deploy/compose.full.yaml --profile fenics up -d --build
```

## FEniCS Provider Prerequisite

The full stack expects a local Docker image:

```text
dolfinx-mcp:latest
```

Build it from the external provider repository:

```bash
git clone https://github.com/ekstanley/ccFenics-plugin.git
cd ccFenics-plugin
docker build -t dolfinx-mcp:latest .
```

## Execution Switch

The full stack still defaults to planning mode:

```text
DOLFINX_MCP_EXECUTE=false
```

Change this to `true` only after the live provider schemas have been checked
against `mcp/providers/fenics/tool_schemas.snapshot.json`.

