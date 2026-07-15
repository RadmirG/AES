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

The variable is optional in container deployment because Nginx proxies
`/api/`, `/v1/`, and `/artifacts/` from the same origin.

## Container Deployment

The default dev/prod Compose entrypoints include `web-ui/web-ui.yaml`. The
container joins `ai-stack-net`, publishes `http://127.0.0.1:3000`, and proxies:

```text
/api/*       -> http://langgraph:8001/api/*
/v1/*        -> http://langgraph:8001/v1/*
/artifacts/* -> http://langgraph:8001/artifacts/*
```

Because the browser talks to the same origin, `VITE_AES_API_BASE_URL` can stay
empty in container deployment.

The Nginx proxy allows long-running `/v1/chat/completions` calls. The right
result pane updates only after AES returns the final response containing
`aes_result`; if a proxy timeout occurs, artifacts may exist on disk while the
browser still shows no result.

## Authentication And Chat Cache

On first load, the Workbench restores the authenticated user through
`GET /api/auth/me` or displays the login form. LangGraph verifies credentials
against PostgreSQL and sets an opaque `HttpOnly` session cookie. Passwords and
raw session tokens are not stored in browser `localStorage`.

Conversation persistence is the next database slice. For now, saved
conversations remain a browser-local cache scoped by authenticated username.
They include chat turns, the latest AES result, and artifact links, so
refreshing keeps both the chat history and the right-side result workspace.
