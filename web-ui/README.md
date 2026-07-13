# AES Web UI

`web-ui` is the future AES Workbench prototype: one browser window with chat on
the left and numerical results on the right.

Open WebUI remains the current deployment chat client. This project implements
an AES-native chat panel against the same OpenAI-compatible AES endpoint:

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
VITE_OPEN_WEBUI_URL=http://127.0.0.1:3001
```

If `VITE_OPEN_WEBUI_URL` is set, the left panel can show an experimental iframe
mode. Open WebUI may block iframe embedding depending on its headers and auth
settings, so the reliable default is the native AES chat panel.

