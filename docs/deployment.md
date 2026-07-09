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
docker compose -f open-webui/open-webui.yaml up -d
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
AES_OLLAMA_MODEL=gemma4:26b docker compose -f deploy/compose.prod.yaml --profile models up -d --build
```

The `models` profile starts a one-shot `ollama-model-puller` service. It waits
for Ollama, pulls the configured manifest group, and also pulls the exact model
named in `AES_OLLAMA_MODEL`.

Development stack with the optional FEniCS MCP provider:

```bash
AES_OLLAMA_MODEL=qwen3:4b docker compose -f deploy/compose.dev.yaml --profile models --profile fenics up -d --build
```

Production stack with the optional FEniCS MCP provider:

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

## Open WebUI AES Connection

Open WebUI is connected to two backends:

```text
Ollama: http://ollama-server:11434
AES:    http://langgraph:8001/v1
```

The AES endpoint is OpenAI-compatible and exposes model `aes-agent` through:

```text
GET /v1/models
POST /v1/chat/completions
```

`aes-agent` is the public wrapper model name shown to Open WebUI. It is not the
raw LLM. Inside the LangGraph service, AES calls Ollama with the environment
variable `OLLAMA_MODEL`, which is set by Compose from `AES_OLLAMA_MODEL`:

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

From the host or WSL, test AES through the published port:

```bash
curl -s http://127.0.0.1:8002/v1/models | jq .
```

From inside the Open WebUI container, use the Docker service URL:

```text
http://langgraph:8001/v1
```

Open WebUI persists some settings in its database. If Open WebUI was started
before the AES OpenAI-compatible environment variables were added, the new
variables may not appear automatically in the UI. Configure the AES OpenAI
connection in the Open WebUI admin settings or recreate the local Open WebUI
data directory for a fresh dev setup.

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

The full stack still defaults to planning mode:

```text
DOLFINX_MCP_EXECUTE=false
```

Change this to `true` only after the live provider schemas have been checked
against `mcp/providers/fenics/tool_schemas.snapshot.json`.



