# OpenUI Prompt For AES Visualization Dashboard

Use this prompt in OpenUI to refine the dashboard shell. Keep VTK.js rendering
logic in `src/components/VtkResultViewer.tsx`.

```text
Create a dark scientific visualization dashboard for AES finite-element
simulation results.

Layout:
- Left: large interactive VTK.js render viewport.
- Right: diagnostics panel with PDE type, run id, runtime, DOFs, time step,
  final time, min/max/mean solution stats, and warnings.
- Bottom/right section: artifact list with links to preview.svg,
  viewer_manifest.json, solution.xdmf, solution.h5, and VTK datasets if present.

Style:
- Professional engineering UI.
- Dark background, high contrast, compact typography.
- Use cards, tables, and clear status badges.

Behavior:
- Load data from an AES viewer_manifest.json URL.
- If no browser-fetchable VTK dataset exists, show a helpful placeholder and
  artifact links.
- If a .vtu or .vtp dataset exists, render it with VTK.js and provide camera
  reset, scalar range, and colormap controls.

Generate React + TypeScript components compatible with Vite.
```

