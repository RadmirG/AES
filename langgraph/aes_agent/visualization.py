from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List

from aes_agent.state import AgentState


VISUALIZATION_TOOL_NAME = "visualization_postprocess"
VISUALIZATION_PROVIDER = "local:visualization"
PREVIEW_NAME = "preview.svg"
VIEWER_MANIFEST_NAME = "viewer_manifest.json"
VIEWER_HTML_NAME = "viewer.html"


def build_visualization_artifacts(state: AgentState) -> Dict[str, Any]:
    source = _latest_solver_result(state.get("tool_results", []))
    if not source:
        return {
            "schema_version": "1.0",
            "provider": VISUALIZATION_PROVIDER,
            "execution_mode": "skipped",
            "generated_file_names": [],
            "generated_files": [],
            "message": "No completed FEniCS result was available for visualization.",
            "errors": [],
            "warnings": [],
        }

    solver_output = source.get("output") or {}
    fenics_result = solver_output.get("fenics_result") or {}
    diagnostics = fenics_result.get("diagnostics") or _execution_diagnostics(solver_output)
    artifacts = _artifact_references(fenics_result, solver_output)
    manifest = _viewer_manifest(
        state=state,
        source=source,
        diagnostics=diagnostics,
        artifacts=artifacts,
    )

    generated_files = [
        {
            "name": VIEWER_MANIFEST_NAME,
            "kind": "visualization_manifest",
            "media_type": "application/json",
            "content": json.dumps(manifest, indent=2, sort_keys=True),
        },
        {
            "name": PREVIEW_NAME,
            "kind": "preview",
            "media_type": "image/svg+xml",
            "content": _render_preview_svg(manifest),
        },
        {
            "name": VIEWER_HTML_NAME,
            "kind": "interactive_viewer",
            "media_type": "text/html",
            "content": _render_viewer_html(manifest),
        },
    ]

    return {
        "schema_version": "1.0",
        "provider": VISUALIZATION_PROVIDER,
        "execution_mode": "generated",
        "source_tool": source.get("tool_name", ""),
        "generated_file_names": [file["name"] for file in generated_files],
        "generated_files": generated_files,
        "viewer_manifest": manifest,
        "preview_name": PREVIEW_NAME,
        "viewer_name": VIEWER_HTML_NAME,
        "errors": [],
        "warnings": manifest.get("warnings", []),
    }


def _latest_solver_result(tool_results: Any) -> Dict[str, Any]:
    if not isinstance(tool_results, list):
        return {}
    for result in reversed(tool_results):
        if not isinstance(result, dict):
            continue
        if result.get("status") != "completed":
            continue
        if result.get("tool_name") in {"fenics_code_solve", "fenics_forward_solve"}:
            output = result.get("output") or {}
            if isinstance(output, dict) and output.get("fenics_result"):
                return result
    return {}


def _execution_diagnostics(output: Dict[str, Any]) -> Dict[str, Any]:
    execution = output.get("execution") if isinstance(output.get("execution"), dict) else {}
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    diagnostics = result.get("diagnostics") if isinstance(result, dict) else {}
    return diagnostics if isinstance(diagnostics, dict) else {}


def _artifact_references(
    fenics_result: Dict[str, Any],
    solver_output: Dict[str, Any],
) -> List[Dict[str, Any]]:
    artifacts = fenics_result.get("artifacts") if isinstance(fenics_result, dict) else []
    if isinstance(artifacts, list) and artifacts:
        return [artifact for artifact in artifacts if isinstance(artifact, dict)]

    execution = (
        solver_output.get("execution")
        if isinstance(solver_output.get("execution"), dict)
        else {}
    )
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    execution_artifacts = result.get("artifacts") if isinstance(result, dict) else []
    if isinstance(execution_artifacts, list):
        return [artifact for artifact in execution_artifacts if isinstance(artifact, dict)]
    return []


def _viewer_manifest(
    *,
    state: AgentState,
    source: Dict[str, Any],
    diagnostics: Dict[str, Any],
    artifacts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    vtk_datasets = [
        _manifest_artifact(artifact)
        for artifact in artifacts
        if _is_vtkjs_readable(str(artifact.get("name", "")))
    ]
    raw_solution_artifacts = [
        _manifest_artifact(artifact)
        for artifact in artifacts
        if _is_raw_solution_artifact(str(artifact.get("name", "")))
    ]

    warnings = []
    if not vtk_datasets:
        warnings.append(
            "No VTK.js-readable dataset was produced yet. The viewer will show "
            "diagnostics and artifact links until a .vtu, .vtp, or .vtkjs export "
            "is available."
        )

    return {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": VISUALIZATION_PROVIDER,
        "source_tool": source.get("tool_name", ""),
        "problem": {
            "class": state.get("problem_class", ""),
            "pde": state.get("pde_info", ""),
            "domain": state.get("domain_info", ""),
            "source": state.get("source_info", ""),
            "boundary_conditions": state.get("bc_info", ""),
            "time": state.get("time_info", ""),
        },
        "diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
        "datasets": {
            "vtkjs_readable": vtk_datasets,
            "raw_solution": raw_solution_artifacts,
            "all_artifacts": [_manifest_artifact(artifact) for artifact in artifacts],
        },
        "preview": {
            "static": PREVIEW_NAME,
            "interactive": VIEWER_HTML_NAME,
            "recommended_frontend": "web-ui with VTK.js",
        },
        "capabilities": {
            "static_preview": True,
            "diagnostics_chart": True,
            "vtkjs_interactive": bool(vtk_datasets),
            "openui_dashboard_scaffold": True,
        },
        "warnings": warnings,
    }


def _manifest_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(artifact.get("name", "")),
        "kind": str(artifact.get("kind", "")),
        "media_type": str(artifact.get("media_type", "")),
        "uri": str(artifact.get("uri", "")),
        "storage": str(artifact.get("storage", "")),
        "status": str(artifact.get("status", "")),
        "metadata": artifact.get("metadata", {}),
    }


def _is_vtkjs_readable(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".vtu", ".vtp", ".vtk", ".vtkjs"))


def _is_raw_solution_artifact(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".xdmf", ".h5", ".bp", ".vtu", ".vtp", ".vtk", ".vtkjs"))


def _render_preview_svg(manifest: Dict[str, Any]) -> str:
    diagnostics = manifest.get("diagnostics") if isinstance(manifest, dict) else {}
    script = diagnostics.get("script") if isinstance(diagnostics, dict) else {}
    if not isinstance(script, dict):
        script = {}

    title = manifest.get("problem", {}).get("pde") or "AES simulation result"
    stats = _solution_stats(script)
    time_series = script.get("time_series") if isinstance(script.get("time_series"), list) else []
    polyline = _time_series_polyline(time_series)

    rows = [
        ("Problem", title),
        ("DOFs", script.get("num_dofs", "not available")),
        ("Steps", script.get("num_steps", "not available")),
        ("dt", script.get("dt", "not available")),
        ("T", script.get("final_time", "not available")),
    ]

    row_text = "\n".join(
        f'<text x="40" y="{90 + index * 26}" class="label">'
        f'{escape(str(label))}: <tspan class="value">{escape(str(value))}</tspan></text>'
        for index, (label, value) in enumerate(rows)
    )

    stat_text = escape(stats or "solution statistics not available")
    chart = ""
    if polyline:
        chart = f'''
  <rect x="40" y="250" width="520" height="180" rx="8" class="chart"/>
  <text x="40" y="238" class="section">Transient max(u) samples</text>
  <polyline points="{polyline}" class="series"/>
  <text x="40" y="458" class="hint">Generated from diagnostics.json. Full FEM field preview requires VTK/PyVista export.</text>
'''

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <style>
    .bg {{ fill: #0f172a; }}
    .panel {{ fill: #111827; stroke: #334155; stroke-width: 1.5; }}
    .chart {{ fill: #020617; stroke: #334155; }}
    .title {{ fill: #e5e7eb; font: 700 28px sans-serif; }}
    .section {{ fill: #cbd5e1; font: 700 17px sans-serif; }}
    .label {{ fill: #94a3b8; font: 15px monospace; }}
    .value {{ fill: #f8fafc; }}
    .stat {{ fill: #a7f3d0; font: 700 18px monospace; }}
    .hint {{ fill: #64748b; font: 13px sans-serif; }}
    .series {{ fill: none; stroke: #38bdf8; stroke-width: 3; }}
  </style>
  <rect class="bg" x="0" y="0" width="960" height="540"/>
  <rect class="panel" x="24" y="24" width="912" height="492" rx="18"/>
  <text x="40" y="62" class="title">AES Result Preview</text>
  {row_text}
  <text x="600" y="96" class="section">Final solution stats</text>
  <text x="600" y="130" class="stat">{stat_text}</text>
  <text x="600" y="178" class="section">Viewer path</text>
  <text x="600" y="210" class="label">Open viewer.html for the OpenUI/VTK.js shell.</text>
  {chart}
</svg>
'''


def _solution_stats(script: Dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("solution_min", "min"),
        ("solution_max", "max"),
        ("solution_mean", "mean"),
    ):
        value = script.get(key)
        if value is not None:
            parts.append(f"{label}={_format_number(value)}")
    return ", ".join(parts)


def _time_series_polyline(values: List[Any]) -> str:
    rows = [row for row in values if isinstance(row, dict) and row.get("max") is not None]
    if len(rows) < 2:
        return ""

    max_values = [_float_or_zero(row.get("max")) for row in rows]
    low = min(max_values)
    high = max(max_values)
    span = high - low or 1.0
    points = []
    for index, row in enumerate(rows):
        x = 60 + index * (480 / max(1, len(rows) - 1))
        normalized = (_float_or_zero(row.get("max")) - low) / span
        y = 410 - normalized * 140
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 0:
        return "0"
    if abs(number) >= 1000 or abs(number) < 0.001:
        return f"{number:.4e}"
    return f"{number:.6g}"


def _render_viewer_html(manifest: Dict[str, Any]) -> str:
    manifest_json = json.dumps(manifest, indent=2, sort_keys=True).replace(
        "</",
        "<\\/",
    )
    title = escape(str((manifest.get("problem") or {}).get("pde") or "AES viewer"))
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AES Visualization Viewer</title>
  <style>
    body {{
      margin: 0;
      background: #0f172a;
      color: #e5e7eb;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(360px, 1fr) 420px;
      min-height: 100vh;
    }}
    #viewer {{
      display: grid;
      place-items: center;
      border-right: 1px solid #334155;
      background: radial-gradient(circle at 30% 20%, #1e293b, #020617 68%);
    }}
    aside {{
      padding: 24px;
      overflow: auto;
      background: #111827;
    }}
    h1 {{ margin-top: 0; font-size: 24px; }}
    code, pre {{
      background: #020617;
      color: #d1d5db;
      border: 1px solid #334155;
      border-radius: 8px;
    }}
    pre {{ padding: 12px; overflow: auto; max-height: 360px; }}
    .card {{
      border: 1px solid #334155;
      border-radius: 14px;
      padding: 16px;
      margin: 16px 0;
      background: rgba(15, 23, 42, 0.7);
    }}
    .muted {{ color: #94a3b8; }}
    a {{ color: #38bdf8; }}
  </style>
</head>
<body>
  <main>
    <section id="viewer">
      <div class="card">
        <h1>{title}</h1>
        <p class="muted">OpenUI-style shell for AES visualization artifacts.</p>
        <p>This static viewer is ready for VTK.js datasets. If no .vtu/.vtp/.vtkjs dataset exists yet, use the diagnostics and raw artifact links on the right.</p>
      </div>
    </section>
    <aside>
      <h1>AES Visualization Manifest</h1>
      <div class="card">
        <p><strong>Static preview:</strong> <a href="{PREVIEW_NAME}">{PREVIEW_NAME}</a></p>
        <p><strong>Recommended app:</strong> <code>web-ui</code> with VTK.js</p>
      </div>
      <div class="card">
        <h2>VTK.js datasets</h2>
        <ul id="datasets"></ul>
      </div>
      <h2>Raw manifest</h2>
      <pre id="manifest"></pre>
    </aside>
  </main>
  <script type="application/json" id="aes-manifest">{manifest_json}</script>
  <script>
    const manifest = JSON.parse(document.getElementById("aes-manifest").textContent);
    document.getElementById("manifest").textContent = JSON.stringify(manifest, null, 2);
    const datasets = manifest.datasets?.vtkjs_readable || [];
    const list = document.getElementById("datasets");
    if (datasets.length === 0) {{
      list.innerHTML = "<li>No VTK.js-readable dataset yet.</li>";
    }} else {{
      list.innerHTML = datasets.map((item) => `<li>${{item.kind}}: ${{item.name}} <span class="muted">${{item.uri}}</span></li>`).join("");
    }}
  </script>
</body>
</html>
'''


def artifact_public_url(run_id: str, filename: str) -> str:
    base_url = os.getenv("AES_PUBLIC_BASE_URL", "").rstrip("/")
    safe_run_id = _safe_url_part(run_id)
    safe_filename = "/".join(_safe_url_part(part) for part in filename.split("/"))
    path = f"/artifacts/{safe_run_id}/{safe_filename}"
    return f"{base_url}{path}" if base_url else path


def aes_artifact_uri_to_public_url(uri: str) -> str:
    match = re.match(r"^aes://artifacts/([^/]+)/(.+)$", str(uri))
    if not match:
        return ""
    return artifact_public_url(match.group(1), match.group(2))


def _safe_url_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", str(value)).strip("-") or "artifact"
