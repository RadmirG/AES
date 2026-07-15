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

Create the ignored repository-root database configuration before starting AES:

```bash
cd ~/projects/AES
cp database/.env.example .env
chmod 600 .env
```

Edit `.env` and replace both PostgreSQL password placeholders with different
random values. Never commit this file. Keep `AES_AUTH_COOKIE_SECURE=false` for
local HTTP/SSH-tunnel testing; use `true` only behind HTTPS.

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

Check the PostgreSQL and migration startup:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs aes-postgres aes-database-migrate
```

Create the first Workbench user interactively:

```bash
docker compose -f deploy/compose.dev.yaml exec langgraph \
  python -m aes_agent.create_user --username engineer --display-name "AES Engineer"
```

The command prompts for and confirms the password without placing it in shell
history or the process command line.

Clean rebuild/restart of the full dev stack after service-layout changes:

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=qwen3:4b
export AES_OLLAMA_PULL_GROUP=minimal
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics down --remove-orphans
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics up -d --build --force-recreate
```

## 9. Stack Logs

### Dev System 
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

Show PostgreSQL and migration logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f aes-postgres aes-database-migrate
```

Show AES Web UI logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models logs -f web-ui
```

FEniCS/Dolfin logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics logs -f dolfinx-mcp
```

FEniCS generated-code runner logs:

```bash
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics logs -f fenics-code-runner
```


### Prod System 
Show all logs:

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f --timestamps
```

Show AES-owned logs with richer workflow content previews. Content previews are
bounded and sanitized; disable them with `AES_LOG_CONTENT=false` and
`FENICS_RUNNER_LOG_CONTENT=false` before starting the stack.

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f langgraph
```
```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f web-ui
```
```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f fenics-code-runner
```

Show external component logs. These services use their own internal formats, but
LangGraph logs the AES-side calls to them.

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f ollama-server
```
```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f dolfinx-mcp
```

Follow the main runtime components together:

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics logs -f langgraph web-ui fenics-code-runner ollama-server dolfinx-mcp
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

Authenticate once and save the opaque session cookie in a temporary cookie
jar. The password remains in a temporary shell variable and is not written to
the command line:

```bash
read -rsp "AES password: " AES_PASSWORD; echo
jq -n --arg username engineer --arg password "$AES_PASSWORD" \
  '{username:$username,password:$password}' \
  | curl -s -c /tmp/aes.cookies \
      -H "Content-Type: application/json" \
      --data-binary @- \
      http://127.0.0.1:8002/api/auth/login \
  | jq .
unset AES_PASSWORD
curl -s -b /tmp/aes.cookies http://127.0.0.1:8002/api/auth/me | jq .
```

Invoke the AES graph directly:

```bash
curl -s -X POST http://127.0.0.1:8002/invoke \
  -b /tmp/aes.cookies \
  -H "Content-Type: application/json" \
  -d '{"text":"Solve a steady heat equation on a unit square with u=0 on the boundary and source f=1."}' \
  | jq .
```

Test the OpenAI-compatible chat endpoint:

```bash
curl -s -X POST http://127.0.0.1:8002/v1/chat/completions \
  -b /tmp/aes.cookies \
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

## 11. Providing PDE Formulations In Chat

AES currently folds all user messages in a chat into one problem statement, but
the safest interaction is to provide the problem data and formulation in one
message.

For a steady heat equation, use a stationary formulation. Example:

```text
Solve the stationary heat equation on the unit square Omega=[0,1]^2.
Use homogeneous Dirichlet boundary conditions u=0 on the boundary.
Use source f=1 and diffusion coefficient alpha=1.
Use the strong form -alpha * Delta(u) = f.
Use the weak FEM form: find u in H_0^1(Omega) such that
integral_Omega alpha * grad(u) dot grad(v) dx = integral_Omega f * v dx
for all test functions v in H_0^1(Omega).
```

For a transient heat equation, include initial and time data. Example:

```text
Solve the transient heat equation on the unit square Omega=[0,1]^2.
Use du/dt = alpha * Delta(u) + f with alpha=1 and f=1.
Use u=0 on the boundary.
Use initial condition u(x,y,0)=sin(pi*x)*sin(pi*y).
Use final time T=1 and time step dt=0.01.
```

Do not mix the word `steady` with a time derivative such as `du/dt` or
`partial u / partial t`. That describes a transient formulation and AES will ask
which problem type should be solved.

AES Workbench locally:

```text
http://127.0.0.1:3000
```

The workbench calls AES through its same-origin proxy. Verify the model through
the workbench port:

```bash
curl -s http://127.0.0.1:3000/v1/models | jq .
```

If needed, verify the direct LangGraph endpoint too:

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

The `web-ui` container runs Nginx and proxies these paths to LangGraph over
`ai-stack-net`:

```text
/v1/*        -> http://langgraph:8001/v1/*
/artifacts/* -> http://langgraph:8001/artifacts/*
```

`aes-agent` is the wrapper model exposed by AES to the workbench. The real LLM
used inside AES is selected by `AES_OLLAMA_MODEL`, which Compose passes into the
LangGraph container as `OLLAMA_MODEL`.

Current dev binding:

```text
AES_OLLAMA_MODEL=qwen3:4b -> OLLAMA_MODEL=qwen3:4b -> Ollama /api/generate
```

Check the running LangGraph container:

```bash
docker exec langgraph printenv OLLAMA_MODEL
```

If an old UI container is still running after the switch, use the
`down --remove-orphans` command in the production or development section once.

## 12. Stop The Dev Stack

Stop containers but keep volumes/data:

```bash
docker compose -f deploy/compose.dev.yaml --profile models down
```

Stop containers including optional FEniCS profile if it was started:

```bash
docker compose -f deploy/compose.dev.yaml --profile models --profile fenics down
```

## 13. Manual Ollama Commands

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

Use `gemma4:31b` only for high-capacity production/server checks. The default
production model below is `gemma4:26b` because it starts and responds faster.

## 14. Production Stack Startup

Production uses `deploy/compose.prod.yaml` and the production Ollama compose
file. The intended AES production runtime model is `gemma4:26b`.

Production enables live FEniCS MCP execution by default, so start it with the
`fenics` profile. Without this profile, `dolfinx-mcp` is not started.
LangGraph does not use a hard Compose `depends_on` on `dolfinx-mcp`, because
that would make commands using only `--profile models` invalid.

Production also enables generated-code execution attempts by default:

```text
DOLFINX_CODE_EXECUTE=true
DOLFINX_CODE_MCP_URL=http://fenics-code-runner:8000/mcp
```

That flag removes the "DOLFINX_CODE_EXECUTE is not enabled" block. The
`fenics-code-runner` service provides the safe script-runner tool
`run_python_script` for generated/user-provided `solve.py` execution.

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=gemma4:26b
export AES_OLLAMA_PULL_GROUP=baseline
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build
```

Clean rebuild/restart of the full production stack after service-layout changes:

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=gemma4:26b
export AES_OLLAMA_PULL_GROUP=baseline
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics down --remove-orphans
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build --force-recreate
```

For stronger production/server models:

```bash
cd ~/projects/AES
export AES_OLLAMA_MODEL=gemma4:26b
export AES_OLLAMA_PULL_GROUP=recommended
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build
```

Check production services:

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics ps
```

Check the generated-code execution flag inside LangGraph:

```bash
docker exec langgraph printenv DOLFINX_CODE_EXECUTE
```

Check the generated-code runner URL inside LangGraph:

```bash
docker exec langgraph printenv DOLFINX_CODE_MCP_URL
```

Stop production services:

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics down
```

## 15. Optional FEniCS MCP Provider

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

The AES-owned generated-code runner image is built automatically by Compose
from `mcp/providers/fenics/code_runner/Dockerfile`. It uses
`dolfinx-mcp:latest` as its base image, so build `dolfinx-mcp:latest` first.

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

If the smoke test reports a non-JSON response, inspect the provider directly:

```bash
docker compose -f deploy/compose.dev.yaml --profile fenics logs -f dolfinx-mcp
curl -i http://127.0.0.1:8003/mcp
```

FEniCS MCP endpoint:

```text
http://127.0.0.1:8003/mcp
```

FEniCS generated-code runner endpoint:

```text
http://127.0.0.1:8006/mcp
```

Smoke-test the generated-code runner tool list:

```bash
curl -s -X POST http://127.0.0.1:8006/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"tools/list",
    "params":{}
  }' | jq .
```

## 16. Optional MCP Provider Profiles

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

## 17. Component-Level Compose Commands

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

Start AES Web UI only:

```bash
docker compose -f web-ui/web-ui.yaml up -d --build
```

The Web UI service expects `langgraph` to be reachable on `ai-stack-net`.
Normally start it through `deploy/compose.dev.yaml` or
`deploy/compose.prod.yaml` instead of this isolated command.

Start LangGraph only for development defaults:

```bash
docker compose -f langgraph/langgraph.yaml up -d --build
```

Start LangGraph only for production defaults:

```bash
docker compose -f langgraph/langgraph.prod.yaml up -d --build
```

Start FEniCS MCP only:

```bash
docker compose -f mcp/compose.mcp.yaml --profile fenics up -d
```

## 18. Original Legacy Docker Commands

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

Production equivalent:

```bash
docker compose -f langgraph/langgraph.prod.yaml up -d --build
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

## 19. Remote Access To AES Workbench

Optional SSH tunnel template. Replace the placeholders locally and do not commit
real usernames, hostnames, IP addresses, or credentials:

```bash
ssh -L 3000:127.0.0.1:3000 <ssh-user>@<server-host-or-ip>
```

Local browser URL:

```text
http://127.0.0.1:3000
```

Do not commit real usernames, email addresses, passwords, hostnames, IP
addresses, or SSH details. Keep test accounts and credentials in a local
password manager or ignored `.env` files only.

## 20. Useful Cleanup Commands

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

Be careful with volume deletion commands because Ollama models and generated
AES artifacts live in mounted data directories/volumes.
