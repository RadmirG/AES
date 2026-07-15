# Deployment Architecture

The `deploy/` component owns the top-level Docker Compose entrypoints. It does
not define every service directly; it includes component-owned Compose files.

```mermaid
flowchart TD
    A["deploy/compose.dev.yaml"] --> DB["database/compose.database.yaml"]
    A --> B["ollama/ollama-server.dev.yaml"]
    A --> C["web-ui/web-ui.yaml"]
    A --> D["mcp/compose.mcp.yaml"]
    A --> E["langgraph/langgraph.yaml"]

    F["deploy/compose.prod.yaml"] --> DB
    F --> G["ollama/ollama-server.prod.yaml"]
    F --> C
    F --> D
    F --> H["langgraph/langgraph.prod.yaml"]
```

## Ownership

`deploy/` owns:

- dev/prod entrypoint composition,
- profile activation strategy,
- cross-component startup commands.

It does not own:

- individual service definitions,
- provider implementation,
- model recommendation manifests,
- application code.

## Dev Versus Prod

The intentional dev/prod difference is concentrated in Ollama and LangGraph
runtime defaults.

```mermaid
flowchart LR
    A["dev"] --> B["qwen3:4b default"]
    A --> C["planning-friendly defaults"]
    D["prod"] --> E["gemma4:26b default"]
    D --> F["FEniCS execution enabled"]
```

Both stacks include:

- `aes-postgres` and the one-shot `aes-database-migrate`,
- `web-ui`,
- `langgraph`,
- `ollama`,
- `mcp/compose.mcp.yaml`.

## Profiles

```mermaid
flowchart TD
    A["base compose up"] --> DB["aes-postgres + migration"]
    A --> B["web-ui"]
    A --> C["langgraph"]
    A --> D["ollama"]
    E["--profile models"] --> F["ollama-model-puller"]
    G["--profile fenics"] --> H["dolfinx-mcp"]
    G --> I["fenics-code-runner"]
    J["--profile retrieval"] --> K["retrieval provider skeleton"]
    L["--profile filesystem"] --> M["filesystem provider skeleton"]
```

Use `--profile fenics` whenever live FEniCS execution or FEniCS logs are
expected.

## Network

All services communicate through the external Docker network:

```text
ai-stack-net
```

The browser enters through `web-ui` on host port `3000`. `web-ui` proxies to
LangGraph by Docker service name.

```mermaid
flowchart LR
    A["Browser<br/>127.0.0.1:3000"] --> B["web-ui"]
    B --> C["langgraph:8001"]
    C --> DB[("aes-postgres:5432")]
    C --> D["ollama-server:11434"]
    C --> E["fenics-code-runner:8000"]
    C --> F["dolfinx-mcp:8000"]
```

## Common Startup

Copy `database/.env.example` to the repository-root `.env` file and replace
both password placeholders before the first startup. Compose refuses to start
without the database administrator and application-role passwords.

Production full stack:

```bash
AES_OLLAMA_MODEL=gemma4:26b docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build
```

Development stack:

```bash
AES_OLLAMA_MODEL=qwen3:4b docker compose -f deploy/compose.dev.yaml --profile models up -d --build
```

## Recreate After Layout Changes

When service names/profiles/includes changed, remove orphans once:

```bash
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics down --remove-orphans
docker compose -f deploy/compose.prod.yaml --profile models --profile fenics up -d --build --force-recreate
```

## Deployment Rule

Component-owned Compose files stay with their component. `deploy/` wires them
together; it should not become another monolithic service-definition directory.
