# AES Command Guide

This file collects the practical commands for developing, starting, testing, and
stopping the AES stack. 

The current recommended workflow is:

1. Develop on Windows if that is comfortable.
2. Keep a separate WSL clone for Linux/Docker testing.
3. Pull the latest Git state in WSL before each test cycle.
4. Use Docker Compose as the real runtime.
5. Use the `models` Compose profile so Ollama model pulling is automated.
6. Start without FEniCS first, then enable the `fenics` profile after the
   `dolfinx-mcp:latest` image exists.

## 1. Original Useful Linux Commands

Show disk space usage for mounted filesystems in human-readable form:

```bash
df -h
```

Show large directories/files in the current folder:

```bash
du -sh *
```

Check inode usage. This helps when disk space looks available but the filesystem
cannot create new files:

```bash
df -i
```

## 2. WSL Setup From Windows PowerShell

List installed WSL distributions:

```powershell
wsl -l -v
```

Ensure Ubuntu 26.04 uses WSL 2:

```powershell
wsl --set-version Ubuntu-26.04 2
```

Set Ubuntu 26.04 as the default WSL distribution:

```powershell
wsl --set-default Ubuntu-26.04
```

Open Ubuntu 26.04:

```powershell
wsl -d Ubuntu-26.04
```

## 3. WSL Base Packages

Run these inside Ubuntu WSL:

```bash
sudo apt update
sudo apt install -y git curl jq rsync python3 python3-venv python3-pip
```

Check that Docker Desktop is visible from WSL:

```bash
docker version
docker compose version
```

If these commands fail, enable Docker Desktop WSL integration:

```text
Docker Desktop -> Settings -> General -> Use WSL 2 based engine
Docker Desktop -> Settings -> Resources -> WSL Integration -> Ubuntu-26.04
```

## 4. Clone Or Update The Project In WSL

Recommended for performance: keep the WSL test copy inside the WSL filesystem,
not under `/mnt/c`.

Clone once. Use your own repository URL locally, but do not commit a personal
fork URL into shared documentation:

```bash
mkdir -p ~/projects
cd ~/projects
git clone <repository-url> AES
cd AES
```

Before each WSL test cycle, pull the latest pushed state:

```bash
cd ~/projects/AES
git pull --ff-only
```

Optional fallback if you want to copy a Windows working tree into WSL without
using Git. Replace the placeholders locally:

```bash
mkdir -p ~/projects/AES
rsync -a \
  --exclude '.vs/' \
  --exclude '.idea/' \
  --exclude '**/__pycache__/' \
  --exclude 'ollama/data/' \
  --exclude 'open-webui/data/' \
  /mnt/c/Users/<windows-user>/<path-to-AES>/ \
  ~/projects/AES/
cd ~/projects/AES
```

## 5. PyCharm With WSL

For Docker-only execution, a PyCharm Python interpreter is not strictly needed.
The containers install their own Python dependencies.

A WSL interpreter or local test environment is still useful for IDE code
completion, local unit tests, and running helper scripts.

Open the project in PyCharm from:

```text
\\wsl.localhost\Ubuntu-26.04\home\<your-linux-user>\projects\AES
```

Set the PyCharm terminal to WSL:

```text
Settings -> Tools -> Terminal -> Shell path:
wsl.exe -d Ubuntu-26.04
```

The repository has a central Python requirement aggregator:

```text
aes_requirements.txt
```

That file includes the subproject requirement files:

```text
langgraph/requirements.txt
mcp/requirements.txt
ollama/requirements.txt
open-webui/requirements.txt
```

Create the WSL test environment named `aes_test_env`:

```bash
cd ~/projects/AES
python3 -m venv ~/.venvs/aes_test_env
source ~/.venvs/aes_test_env/bin/activate
python -m pip install --upgrade pip
python -m pip install -r aes_requirements.txt
```

Reactivate it later:

```bash
source ~/.venvs/aes_test_env/bin/activate
```

## 6. Create The Shared Docker Network

The AES services use the external Docker network `ai-stack-net`.

Create it once:

```bash
docker network create ai-stack-net
```

Safer idempotent version:

```bash
docker network inspect ai-stack-net >/dev/null 2>&1 || docker network create ai-stack-net
```

## 7. First Local Unit Tests

These tests run in WSL with the central `aes_test_env` environment.

```bash
cd ~/projects/AES
git pull --ff-only
source ~/.venvs/aes_test_env/bin/activate
```

Run LangGraph/AES tests:

```bash
cd ~/projects/AES/langgraph
PYTHONPATH=. python -m unittest discover -s tests -v
```

Run Ollama model-puller tests:

```bash
cd ~/projects/AES
python -m unittest discover -s ollama/tests -v
```

Dry-run model selection without downloading anything:

```bash
cd ~/projects/AES
python ollama/pull_models.py --profile dev --group minimal --include-default --model qwen3:4b --dry-run
```

## 8. Recommended Dev Stack Startup

Start with the small pull group on the laptop. This is the safest first smoke
test.

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=qwen3:4b
export AES_OLLAMA_PULL_GROUP=minimal
docker compose -f deploy/compose.dev.yaml --profile models up -d --build
```

For the fuller dev model set later:

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=qwen3:4b
export AES_OLLAMA_PULL_GROUP=recommended
docker compose -f deploy/compose.dev.yaml --profile models up -d --build
```

The `models` profile starts the one-shot `ollama-model-puller` service. It pulls
both the selected pull group and the exact model in `AES_OLLAMA_MODEL`.

Wait for the model puller on first startup:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f ollama-model-puller
```

Check running services:

```bash
docker compose -f deploy/compose.dev.yaml --profile models ps
```

## 9. Dev Stack Logs

Show all logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f
```

Show Ollama logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f ollama
```

Show LangGraph/AES logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f langgraph
```

Show Open WebUI logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f openwebui
```

## 10. Dev Stack Smoke Tests

Check Ollama models:

```bash
curl -s http://127.0.0.1:11435/api/tags | jq .
```

Check AES health:

```bash
curl -s http://127.0.0.1:8002/health | jq .
```

Check OpenAI-compatible AES model listing:

```bash
curl -s http://127.0.0.1:8002/v1/models | jq .
```

Invoke the AES graph directly:

```bash
curl -s -X POST http://127.0.0.1:8002/invoke \
  -H "Content-Type: application/json" \
  -d '{"text":"Solve a steady heat equation on a unit square with u=0 on the boundary and source f=1."}' \
  | jq .
```

Test the OpenAI-compatible chat endpoint:

```bash
curl -s -X POST http://127.0.0.1:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"aes-agent",
    "messages":[
      {"role":"user","content":"Solve a steady heat equation on a unit square with u=0 on the boundary and source f=1."}
    ],
    "stream":false
  }' \
  | jq .
```

Open WebUI locally:

```text
http://127.0.0.1:3000
```

If `aes-agent` is not visible in Open WebUI, first verify that AES exposes the
model:

```bash
curl -s http://127.0.0.1:8002/v1/models | jq .
```

Expected result:

```json
{
  "object": "list",
  "data": [
    {
      "id": "aes-agent",
      "object": "model",
      "created": 0,
      "owned_by": "aes"
    }
  ]
}
```

Open WebUI runs inside a container, so its OpenAI-compatible base URL for AES is
the Docker-internal service URL:

```text
http://langgraph:8001/v1
```

Do not configure Open WebUI with `http://127.0.0.1:8002/v1` from inside the
container. That address points back to the Open WebUI container itself, not the
LangGraph container.

The compose file sets these Open WebUI variables:

```text
ENABLE_OPENAI_API=True
OPENAI_API_BASE_URL=http://langgraph:8001/v1
OPENAI_API_KEY=aes-dev-no-auth
DEFAULT_MODELS=aes-agent
```

Open WebUI persists some settings in its database after first startup. If you
started Open WebUI before these variables existed and `aes-agent` still does not
appear, configure the same OpenAI-compatible connection in the Open WebUI admin
settings or recreate the local Open WebUI data directory.

## 11. Stop The Dev Stack

Stop containers but keep volumes/data:

```bash
docker compose -f deploy/compose.dev.yaml --profile models down
```

Stop containers including optional FEniCS profile if it was started:

```bash
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics down
```

## 12. Manual Ollama Commands

Enter the Ollama container shell:

```bash
docker exec -it ollama-server bash
```

Pull a model manually:

```bash
docker exec -it ollama-server ollama pull qwen3:4b
```

Run a model manually:

```bash
docker exec -it ollama-server ollama run qwen3:4b
```

Original model command preserved from old notes:

```bash
docker exec -it ollama-server ollama pull gemma4:31b
docker exec -it ollama-server ollama run gemma4:31b
```

Use `gemma4:31b` only on a strong enough production/server GPU setup, not for
normal laptop development.

## 13. Production Stack Startup

Production uses `deploy/compose.prod.yaml` and the production Ollama compose
file.

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=gemma4:e4b
export AES_OLLAMA_PULL_GROUP=baseline
docker compose -f deploy/compose.prod.yaml --profile models up -d --build
```

For stronger production/server models:

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=gemma4:12b
export AES_OLLAMA_PULL_GROUP=recommended
docker compose -f deploy/compose.prod.yaml --profile models up -d --build
```

Check production services:

```bash
docker compose -f deploy/compose.prod.yaml --profile models ps
```

Stop production services:

```bash
docker compose -f deploy/compose.prod.yaml --profile models down
```

## 14. Optional FEniCS MCP Provider

Do not enable this for the first smoke test unless the image already exists:

```bash
docker image inspect dolfinx-mcp:latest
```

Build the external provider image if needed:

```bash
git clone https://github.com/ekstanley/ccFenics-plugin.git
cd ccFenics-plugin
docker build -t dolfinx-mcp:latest .
```

Start the dev stack with FEniCS:

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=qwen3:4b
export AES_OLLAMA_PULL_GROUP=minimal
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics up -d --build
```

Smoke-test the FEniCS MCP tool list:

```bash
cd ~/projects/AES
DOLFINX_MCP_URL=http://127.0.0.1:8003/mcp \
python mcp/providers/fenics/smoke_tests/smoke_tools_list.py
```

FEniCS MCP endpoint:

```text
http://127.0.0.1:8003/mcp
```

## 15. Optional MCP Provider Profiles

These providers are scaffolded but require their images before use:

```bash
docker compose -f deploy/compose.dev.yaml --profile retrieval up -d --build
docker compose -f deploy/compose.dev.yaml --profile filesystem up -d --build
```

Current planned local ports:

```text
retrieval MCP:  http://127.0.0.1:8004
filesystem MCP: http://127.0.0.1:8005
```

## 16. Component-Level Compose Commands

Usually use `deploy/compose.dev.yaml` or `deploy/compose.prod.yaml`. These
component-level commands are useful for isolated debugging.

Start dev Ollama only:

```bash
docker compose -f ollama/ollama-server.dev.yaml up -d
```

Start prod Ollama only:

```bash
docker compose -f ollama/ollama-server.prod.yaml up -d
```

Start Open WebUI only:

```bash
docker compose -f open-webui/open-webui.yaml up -d
```

Start LangGraph only:

```bash
docker compose -f langgraph/langgraph.yaml up -d --build
```

Start FEniCS MCP only:

```bash
docker compose -f mcp/compose.mcp.yaml --profile fenics up -d
```

## 17. Original Legacy Docker Commands

These commands are preserved from the original `commands.sh`. Some filenames are
old and no longer match the redesigned repo layout.

Old Ollama startup command:

```bash
docker compose -f ollama-server.yaml up -d
```

Current equivalent:

```bash
docker compose -f ollama/ollama-server.dev.yaml up -d
```

Old Ollama shutdown command:

```bash
docker compose -f ollama-server.yaml down
```

Current equivalent:

```bash
docker compose -f ollama/ollama-server.dev.yaml down
```

Old LangGraph rebuild command:

```bash
docker compose -f langgraph.yaml up -d --build
```

Current equivalent:

```bash
docker compose -f langgraph/langgraph.yaml up -d --build
```

Old container status command:

```bash
docker compose -f ollama-server.yaml ps
```

Current equivalent:

```bash
docker compose -f deploy/compose.dev.yaml --profile models ps
```

Old logs commands:

```bash
docker compose -f ollama-server.yaml logs -f
docker compose -f ollama-server.yaml logs -f ollama
```

Current equivalents:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f
docker compose -f deploy/compose.dev.yaml --profile models logs -f ollama
```

## 18. Remote Access To Open WebUI

Optional SSH tunnel template. Replace the placeholders locally and do not commit
real usernames, hostnames, IP addresses, or credentials:

```bash
ssh -L 3000:127.0.0.1:3000 <ssh-user>@<server-host-or-ip>
```

Local browser URL:

```text
http://127.0.0.1:3000
```

Do not commit real Open WebUI usernames, email addresses, or passwords. Keep
test accounts and credentials in a local password manager or ignored `.env`
files only.

## 19. Useful Cleanup Commands

Show running AES-related containers:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Show Docker disk usage:

```bash
docker system df
```

Remove stopped containers and unused networks. This does not remove named
volumes:

```bash
docker system prune
```

Be careful with volume deletion commands because Ollama models and Open WebUI
data live in mounted data directories/volumes.
