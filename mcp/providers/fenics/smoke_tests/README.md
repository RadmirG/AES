# FEniCS Provider Smoke Tests

These tests are intended for a live `dolfinx-mcp` provider.

Required environment:

```text
DOLFINX_MCP_URL=http://127.0.0.1:8003/mcp
```

First smoke-test target:

1. initialize MCP session,
2. call `tools/list`,
3. verify required allowlisted tool names exist,
4. run a tiny Poisson or heat-equation workflow once the live schemas are known.

Run:

```bash
DOLFINX_MCP_URL=http://127.0.0.1:8003/mcp \
python mcp/providers/fenics/smoke_tests/smoke_tools_list.py
```

If the server returns plain text, HTML, or a wrong endpoint response, the smoke
test prints the content type and a body preview. Use that output together with:

```bash
docker compose -f deploy/compose.dev.yaml --profile fenics logs -f dolfinx-mcp
curl -i http://127.0.0.1:8003/mcp
```
