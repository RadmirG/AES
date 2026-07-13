# AES Visualization UI

This subproject is the browser-side visualization frontend for AES artifacts.
It is intentionally separate from Open WebUI:

- Open WebUI remains the chat interface for `aes-agent`.
- AES/LangGraph serves stored artifacts through `/artifacts/{run_id}/{file}`.
- This UI loads `viewer_manifest.json` and renders scientific result data.
- OpenUI can be used to prototype or refine the React dashboard shell.
- VTK.js is the rendering engine for `.vtu`, `.vtp`, `.vtk`, or `.vtkjs` data.

## Development

```bash
npm install
npm run dev
```

Pass the manifest URL with a query parameter:

```text
http://localhost:5173/?manifest=http://127.0.0.1:8002/artifacts/<run_id>/viewer_manifest.json
```

## Current Scope

The first version renders diagnostics and artifact links immediately. VTK.js
interactive rendering is enabled when `viewer_manifest.json` contains a
browser-readable dataset URL. Provider-owned `mcp://...` URIs must first be
materialized or proxied by AES before the browser can fetch them.

