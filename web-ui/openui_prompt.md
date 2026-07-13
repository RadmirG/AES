# OpenUI Prompt For AES Workbench

```text
Create a professional engineering web application named AES Workbench.

Layout:
- Split screen with two primary panes.
- Left pane: chat interface for an AI engineering agent.
- Right pane: result workspace with tabs for Overview, Preview, Artifacts,
  Diagnostics, and Interactive VTK.js Viewer.

Chat behavior:
- Message list with user/assistant bubbles.
- Multiline PDE input.
- Send button and running state.
- Show the latest agent status and next action.

Results behavior:
- Read an AES response object containing aes_result.
- Extract artifact_store manifest data.
- Show direct links to viewer.html, preview.svg, viewer_manifest.json,
  diagnostics.json, solve.py, and stdout.txt.
- Show preview.svg inline when available.
- Show VTK.js viewport when a browser-fetchable .vtu/.vtp/.vtk/.vtkjs dataset
  is available.

Style:
- Dark, technical, compact.
- Clear separation between chat and results.
- Use status badges and artifact cards.

Generate React + TypeScript components compatible with Vite.
```

