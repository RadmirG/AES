# AES Deployment

## Required Docker Network

Create the shared network once:

```bash
docker network create ai-stack-net
```

## Component Compose Files

Each subproject owns its own service definition:

```bash
docker compose -f ollama/ollama-server.dev.yaml up -d
docker compose -f ollama/ollama-server.prod.yaml up -d
docker compose -f web-ui/web-ui.yaml up -d --build
docker compose -f mcp/compose.mcp.yaml --profile fenics up -d
docker compose -f langgraph/langgraph.yaml up -d --build
docker compose -f langgraph/langgraph.prod.yaml up -d --build
```

`mcp/compose.mcp.yaml` is itself a thin MCP entrypoint. It includes the
provider-owned Compose files under `mcp/providers/`.

## New Deployment Layer

The `deploy/` directory provides two thin entrypoint files. They include the
component-owned Compose files rather than duplicating the service definitions.

This requires a Docker Compose version that supports the top-level `include`
field. If a target machine does not support `include`, upgrade Docker Compose
before using the deployment entrypoints.

Development stack with model pull automation:

```bash
AES_OLLAMA_MODEL=qwen3:4b docker compose -f deploy/compose.dev.yaml --profile models up -d --build
```

Production/server stack with model pull automation:

```bash
AES_OLLAMA_MODEL=gemma4:26b docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build
```

When upgrading after service-layout changes, remove orphaned containers once
before starting the new stack:

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics down --remove-orphans
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build --force-recreate
```

Production enables live FEniCS MCP execution by default through
`DOLFINX_MCP_EXECUTE=true`, so the `fenics` profile is part of the normal
production startup. To force planning-only mode, set
`DOLFINX_MCP_EXECUTE=false`.

`langgraph` intentionally does not declare a hard Compose `depends_on` on
`dolfinx-mcp`, because `dolfinx-mcp` is behind the optional `fenics` profile.
Use `--profile fenics` for live execution and for log/status commands that
include the FEniCS provider.

LangGraph writes AES-owned artifact manifests to `/artifacts` inside the
container. Both dev and prod Compose files mount this to the repository-level
`artifacts/` directory, and generated files there are ignored by Git.

The `models` profile starts a one-shot `ollama-model-puller` service. It waits
for Ollama, pulls the configured manifest group, and also pulls the exact model
named in `AES_OLLAMA_MODEL`.

Development stack with the optional FEniCS MCP provider:

```bash
AES_OLLAMA_MODEL=qwen3:4b docker compose -f deploy/compose.dev.yaml --profile models --profile fenics up -d --build
```

Production stack with explicit FEniCS MCP provider profile:

```bash
AES_OLLAMA_MODEL=gemma4:26b docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build
```

Additional MCP providers can be activated through their profiles once their
provider images exist:

```bash
docker compose -f deploy/compose.dev.yaml --profile retrieval up -d --build
docker compose -f deploy/compose.dev.yaml --profile filesystem up -d --build
```

The first implementation treats MCP providers as optional long-running
containers. Starting a provider only for one tool call and shutting it down
again is possible later, but requires a lifecycle controller and readiness
checks. Docker Compose profiles are the simpler first reliability layer.

The only intentional component difference between development and production is
the Ollama service file:

```text
dev:  ollama/ollama-server.dev.yaml
prod: ollama/ollama-server.prod.yaml
```

The LangGraph service reads the backend model from `AES_OLLAMA_MODEL`. When the
`models` profile is enabled, the same variable is also passed to the model
puller, so the runtime model is installed as part of deployment. On a first pull, wait for the one-shot puller to finish before sending the first AES request.

On Windows PowerShell, set the variable first:

```powershell
$env:AES_OLLAMA_MODEL = "qwen3:4b"
docker compose -f deploy/compose.dev.yaml --profile models up -d --build
```

## AES Web UI Connection

`web-ui` is the default browser-facing AES workbench. It is published on:

```text
http://127.0.0.1:3000
```

The container joins `ai-stack-net` and uses Nginx as a same-origin proxy:

```text
Browser -> web-ui:3000
web-ui /v1/*        -> http://langgraph:8001/v1/*
web-ui /artifacts/* -> http://langgraph:8001/artifacts/*
```

The `/v1/` proxy is configured for long-running AES requests. This matters for
first model loads, generated-code runs, FEniCS execution, and visualization
postprocessing: the browser result workspace updates only after the
OpenAI-compatible response returns with `aes_result`.

The AES endpoint is OpenAI-compatible and exposes model `aes-agent` through:

```text
GET /v1/models
POST /v1/chat/completions
```

`aes-agent` is the public wrapper model used by the AES workbench. It is not
the raw LLM. Inside the LangGraph service, AES calls Ollama with the
environment variable `OLLAMA_MODEL`, which is set by Compose from
`AES_OLLAMA_MODEL`:

```text
AES_OLLAMA_MODEL -> OLLAMA_MODEL -> Ollama /api/generate payload model
```

For development the default is:

```text
AES_OLLAMA_MODEL=qwen3:4b
```

For production the documented default is:

```text
AES_OLLAMA_MODEL=gemma4:26b
```

The generated-code path is LLM-first. AES only uses its conservative fallback
DOLFINx template when the configured LLM returns no usable Python code.

From the host or WSL, test AES through the direct LangGraph port:

```bash
curl -s http://127.0.0.1:8002/v1/models | jq .
```

From the browser-facing workbench, the same request is available through the
web UI proxy:

```bash
curl -s http://127.0.0.1:3000/v1/models | jq .
```

Final answer artifact links use `AES_PUBLIC_BASE_URL`. Dev and prod default it
to `http://127.0.0.1:3000`, so generated links go through the workbench's
`/artifacts/` proxy and work through a single browser port or SSH tunnel.
Inside `web-ui`, `aes://artifacts/...` URIs are converted to same-origin
`/artifacts/...` URLs before absolute public URLs are used, which keeps the
right result pane usable when the browser connects through a different local
tunnel port such as `3001`.

The AES Workbench is the only browser UI included by default in
`deploy/compose.dev.yaml` and `deploy/compose.prod.yaml`.

On first load, `web-ui` shows a local Workbench login screen. This login
separates saved browser-local conversations by user name. It is meant for the
prototype and does not authenticate against the server yet.

Chats, assistant answers, the latest `aes_result`, and right-pane result state
are stored in browser `localStorage`. Refreshing the page keeps the active
conversation and previously generated result links. Clearing browser storage or
using a different browser profile starts with an empty local history.

## Ollama Model Manifests and Pull Automation

Model recommendations are tracked in:

```text
ollama/models.dev.yaml
ollama/models.prod.yaml
```

These files are not interpreted by Ollama directly. They are AES deployment
manifests. They define hardware assumptions, default model choices, and named
pull groups such as `minimal`, `recommended`, `baseline`, or `high_capacity`.

Runtime model selection is still controlled by the LangGraph service through:

```text
AES_OLLAMA_MODEL
```

Model installation is handled by the AES puller script:

```bash
python ollama/pull_models.py --profile dev --group recommended --include-default
python ollama/pull_models.py --profile prod --group baseline --include-default
```

On Windows PowerShell:

```powershell
py -3 ollama\pull_models.py --profile dev --group recommended --include-default
```

The puller talks to the Ollama HTTP API. The default host URL is
`http://127.0.0.1:11435`, matching the local port exposed by the Ollama Compose
files. Override it when needed:

```bash
python ollama/pull_models.py --profile prod --group recommended --ollama-url http://127.0.0.1:11435
```

Dry-run the selected models without downloading them:

```bash
python ollama/pull_models.py --profile dev --group minimal --dry-run
```

The same pull step is also available through Docker Compose. For a full stack
startup, enable the `models` profile:

```bash
AES_OLLAMA_MODEL=qwen3:4b docker compose -f deploy/compose.dev.yaml --profile models up -d --build
AES_OLLAMA_MODEL=gemma4:26b docker compose -f deploy/compose.prod.yaml --profile models up -d --build
```

For a pull-only run, target the one-shot service directly:

```bash
docker compose -f deploy/compose.dev.yaml --profile models up ollama-model-puller
docker compose -f deploy/compose.prod.yaml --profile models up ollama-model-puller
```

The default Compose pull groups are:

```text
dev:  recommended
prod: baseline
```

Override the group with `AES_OLLAMA_PULL_GROUP`:

```powershell
$env:AES_OLLAMA_MODEL = "qwen3:4b"
$env:AES_OLLAMA_PULL_GROUP = "minimal"
docker compose -f deploy/compose.dev.yaml --profile models up -d --build
```

The puller installs both the selected pull group and the exact
`AES_OLLAMA_MODEL`. `AES_OLLAMA_MODEL` is still the runtime selector used by the
LangGraph service.

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

The development stack defaults to planning mode:

```text
DOLFINX_MCP_EXECUTE=false
```

The production stack defaults to live FEniCS MCP execution:

```text
DOLFINX_MCP_EXECUTE=true
```

Live execution requires the `fenics` Compose profile so the `dolfinx-mcp`
container is running. If the live provider schema changes, compare it against
`mcp/providers/fenics/tool_schemas.snapshot.json`.



