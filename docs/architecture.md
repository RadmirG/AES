# AES Architecture

AES is split into orchestration, model runtime, user interface, MCP providers,
deployment composition, and documentation.

```text
Open WebUI
  -> AES FastAPI / OpenAI-compatible endpoint
  -> LangGraph StateGraph
  -> AES tool registry
  -> MCP provider adapter
  -> provider-specific MCP servers
```

## Source Layout

```text
AES/
  langgraph/     # AES orchestration service
  mcp/           # MCP provider infrastructure
  ollama/        # model runtime compose file and data
  open-webui/    # user interface compose file and data
  deploy/        # combined deployment compose files
  docs/          # architecture and operation docs
```

## Design Principles

- Keep LangGraph as the workflow and routing spine.
- Keep the LLM behind explicit nodes and schemas.
- Expose high-level AES wrapper tools to the model, not every low-level MCP tool.
- Keep heavy execution backends in separate provider containers.
- Use planning mode by default for expensive numerical tools.
- Add live execution only after schema and smoke-test validation.

## MCP Provider Layer

`mcp/` is not a monolithic tool server. It is a provider-management layer for
multiple independent MCP servers.

Each provider should own:

- compose configuration,
- allowlist,
- schema snapshot,
- workspace,
- smoke tests,
- README with operational notes.

