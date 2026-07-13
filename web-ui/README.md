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

The Nginx proxy allows long-running `/v1/chat/completions` calls. The right
result pane updates only after AES returns the final response containing
`aes_result`; if a proxy timeout occurs, artifacts may exist on disk while the
browser still shows no result.

## Local Sessions

On first load, the Workbench shows a local login screen. The user name selects a
browser-local chat history stored in `localStorage`; it is not a server-side
authentication mechanism yet.

Saved conversations include chat turns, the latest AES result, and artifact
links, so refreshing the page keeps both the chat history and the right-side
result workspace.
