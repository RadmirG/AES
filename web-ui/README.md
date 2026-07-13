# AES Web UI

`web-ui` is the default AES Workbench: one browser window with chat on the left
and numerical results on the right.

It implements an AES-native chat panel against the OpenAI-compatible AES
endpoint:

```text
POST /v1/chat/completions
model: aes-agent
```

The right panel reads `aes_result`, artifact manifests, and visualization
artifacts such as `preview.svg`, `viewer_manifest.json`, and `viewer.html`.
VTK.js rendering is activated when AES serves browser-fetchable `.vtu`, `.vtp`,
`.vtk`, or `.vtkjs` datasets.

## Development

```bash
npm install
npm run dev
```

Useful environment variables:

```text
VITE_AES_API_BASE_URL=http://127.0.0.1:8002
```

The variable is optional in container deployment because Nginx proxies `/v1/`
and `/artifacts/` from the same origin.

## Container Deployment

The default dev/prod Compose entrypoints include `web-ui/web-ui.yaml`. The
container joins `ai-stack-net`, publishes `http://127.0.0.1:3000`, and proxies:

```text
/v1/*        -> http://langgraph:8001/v1/*
/artifacts/* -> http://langgraph:8001/artifacts/*
```

Because the browser talks to the same origin, `VITE_AES_API_BASE_URL` can stay
empty in container deployment.
