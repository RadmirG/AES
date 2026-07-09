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
  -> AES artifact store
```

## Source Layout

```text
AES/
  langgraph/     # AES orchestration service
  mcp/           # MCP provider infrastructure
  ollama/        # model runtime compose file and data
  open-webui/    # user interface compose file and data
  deploy/        # dev/prod deployment entrypoints
  docs/          # architecture and operation docs
```

## Design Principles

- Keep LangGraph as the workflow and routing spine.
- Keep the LLM behind explicit nodes and schemas.
- Expose high-level AES wrapper tools to the model, not every low-level MCP tool.
- Keep heavy execution backends in separate provider containers.
- Keep final artifact policy in AES, not inside provider containers.
- Use planning mode by default for expensive numerical tools.
- Add live execution only after schema and smoke-test validation.

## Artifact Store

Providers return structured results and artifact references. AES owns the final
artifact manifest and storage policy through the local `artifact_store` tool.

The first implementation writes:

- `manifest.json`,
- `summary.md`.

Both files are written below `AES_ARTIFACT_ROOT`, mounted as `/artifacts` in the
LangGraph containers. Provider workspaces, such as the FEniCS `/workspace`, are
treated as scratch or provider-owned storage, not as final AES output locations.

## MCP Provider Layer

`mcp/` is a provider-management layer for multiple MCP servers. The central
`mcp/compose.mcp.yaml` file follows the same pattern as the top-level deployment
entrypoints: it includes provider-owned Compose files instead of defining every
service directly.

```text
mcp/compose.mcp.yaml
  -> mcp/providers/fenics/compose.yaml
  -> mcp/providers/retrieval/compose.yaml
  -> mcp/providers/filesystem/compose.yaml
```

The central `mcp/providers.yaml` file is also only an index. Provider-specific
AES/governance metadata is stored locally:

```text
mcp/providers.yaml
  -> mcp/providers/fenics/provider.yaml
  -> mcp/providers/retrieval/provider.yaml
  -> mcp/providers/filesystem/provider.yaml
```

Each provider should own:

- compose configuration,
- provider manifest,
- allowlist,
- schema snapshot,
- workspace,
- smoke tests,
- README with operational notes.

For now, providers are optional long-running services selected by Docker Compose
profiles. On-demand provider startup can be added later with a controller or
Kubernetes-style job lifecycle, but it is deliberately not part of the first
Compose-based version.

## Deployment Entry Points

The deployment layer has only two top-level entrypoints:

```text
deploy/compose.dev.yaml
deploy/compose.prod.yaml
```

Both files include the component-owned service definitions. The dev/prod
difference is intentionally concentrated in the Ollama component:

```text
ollama/ollama-server.dev.yaml
ollama/ollama-server.prod.yaml
```
