from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aes_agent.state import AgentState


ARTIFACT_STORE_PROVIDER = "local:artifact_store"
DEFAULT_ARTIFACT_ROOT = "artifacts"


def persist_artifacts(state: AgentState) -> Dict[str, Any]:
    manifest = build_artifact_manifest(state)
    root = Path(os.getenv("AES_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT))
    run_dir = root / manifest["run_id"]
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.md"

    try:
        _ensure_directory(run_dir)
        _write_text(
            manifest_path,
            json.dumps(manifest, indent=2, sort_keys=True),
        )
        _write_text(
            summary_path,
            _render_summary(manifest),
        )
    except OSError as exc:
        return {
            "schema_version": "1.0",
            "provider": ARTIFACT_STORE_PROVIDER,
            "execution_mode": "failed",
            "manifest": manifest,
            "artifact_root": str(root),
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
            "summary_path": str(summary_path),
            "errors": [f"Failed to persist artifact manifest: {exc}"],
        }

    return {
        "schema_version": "1.0",
        "provider": ARTIFACT_STORE_PROVIDER,
        "execution_mode": "stored",
        "manifest": manifest,
        "artifact_root": str(root),
        "run_dir": str(run_dir),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "errors": [],
    }


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def build_artifact_manifest(state: AgentState) -> Dict[str, Any]:
    tool_results = [
        result
        for result in state.get("tool_results", [])
        if isinstance(result, dict)
    ]
    fenics_output = _latest_tool_output(tool_results, "fenics_forward_solve")
    fenics_result = (
        fenics_output.get("fenics_result", {})
        if isinstance(fenics_output, dict)
        else {}
    )
    artifacts = _collect_artifact_references(fenics_result)
    errors = _collect_errors(tool_results, fenics_result)
    warnings = _collect_warnings(tool_results, fenics_result)

    return {
        "schema_version": "1.0",
        "run_id": _build_run_id(state),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": _manifest_status(tool_results, fenics_result),
        "problem": {
            "class": state.get("problem_class", ""),
            "pde": state.get("pde_info", ""),
            "domain": state.get("domain_info", ""),
            "source": state.get("source_info", ""),
            "boundary_conditions": state.get("bc_info", ""),
            "time": state.get("time_info", ""),
        },
        "sources": _summarize_tool_results(tool_results),
        "artifacts": artifacts,
        "errors": errors,
        "warnings": warnings,
    }


def _latest_tool_output(
    tool_results: List[Dict[str, Any]],
    tool_name: str,
) -> Dict[str, Any]:
    for result in reversed(tool_results):
        if result.get("tool_name") != tool_name:
            continue
        output = result.get("output") or {}
        return output if isinstance(output, dict) else {}
    return {}


def _collect_artifact_references(fenics_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(fenics_result, dict):
        return []

    fenics_status = str(fenics_result.get("status", ""))
    artifacts = fenics_result.get("artifacts") or []
    if isinstance(artifacts, list) and artifacts:
        return [
            _normalize_artifact_reference(artifact, final_status="referenced")
            for artifact in artifacts
            if isinstance(artifact, dict)
        ]

    if fenics_status == "failed":
        return []

    requested = fenics_result.get("requested_artifacts") or []
    if isinstance(requested, list):
        return [
            _normalize_artifact_reference(artifact, final_status="planned")
            for artifact in requested
            if isinstance(artifact, dict)
        ]

    return []


def _normalize_artifact_reference(
    artifact: Dict[str, Any],
    *,
    final_status: str,
) -> Dict[str, Any]:
    return {
        "name": str(artifact.get("name", "")),
        "kind": str(artifact.get("kind", "")),
        "status": final_status,
        "uri": str(artifact.get("uri", "")),
        "storage": str(artifact.get("storage", "")),
        "media_type": str(artifact.get("media_type", "")),
        "producer": artifact.get("producer", {}),
        "metadata": artifact.get("metadata", {}),
    }


def _collect_errors(
    tool_results: List[Dict[str, Any]],
    fenics_result: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    for result in tool_results:
        if result.get("status") == "failed" and result.get("error"):
            errors.append(f"{result.get('tool_name', 'tool')}: {result['error']}")

    raw_errors = fenics_result.get("errors", []) if isinstance(fenics_result, dict) else []
    if isinstance(raw_errors, list):
        errors.extend(str(error) for error in raw_errors if str(error).strip())
    elif raw_errors:
        errors.append(str(raw_errors))

    return list(dict.fromkeys(errors))


def _collect_warnings(
    tool_results: List[Dict[str, Any]],
    fenics_result: Dict[str, Any],
) -> List[str]:
    warnings: List[str] = []
    raw_warnings = (
        fenics_result.get("warnings", [])
        if isinstance(fenics_result, dict)
        else []
    )
    if isinstance(raw_warnings, list):
        warnings.extend(str(warning) for warning in raw_warnings if str(warning).strip())
    elif raw_warnings:
        warnings.append(str(raw_warnings))

    for result in tool_results:
        output = result.get("output") or {}
        if not isinstance(output, dict):
            continue
        output_warnings = output.get("warnings", [])
        if isinstance(output_warnings, list):
            warnings.extend(
                str(warning)
                for warning in output_warnings
                if str(warning).strip()
            )

    return list(dict.fromkeys(warnings))


def _manifest_status(
    tool_results: List[Dict[str, Any]],
    fenics_result: Dict[str, Any],
) -> str:
    if any(result.get("status") == "failed" for result in tool_results):
        return "failed"

    fenics_status = (
        str(fenics_result.get("status", ""))
        if isinstance(fenics_result, dict)
        else ""
    )
    if fenics_status in {"completed", "planned", "unverified", "failed"}:
        return fenics_status

    return "stored"


def _summarize_tool_results(tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "tool_name": str(result.get("tool_name", "")),
            "provider": str(result.get("provider", "")),
            "status": str(result.get("status", "")),
        }
        for result in tool_results
    ]


def _build_run_id(state: AgentState) -> str:
    configured = os.getenv("AES_ARTIFACT_RUN_ID", "").strip()
    if configured:
        return _slug(configured)

    seed = {
        "raw_user_input": state.get("raw_user_input", ""),
        "numerical_recipe": state.get("numerical_recipe", {}),
    }
    digest = hashlib.sha256(
        json.dumps(seed, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{digest}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return slug.strip("-._") or "aes-run"


def _render_summary(manifest: Dict[str, Any]) -> str:
    lines = [
        f"# AES Artifact Run {manifest.get('run_id', '')}",
        "",
        f"Status: {manifest.get('status', '')}",
        f"Created: {manifest.get('created_at', '')}",
        "",
        "## Artifacts",
    ]

    artifacts = manifest.get("artifacts") or []
    if artifacts:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            lines.append(
                "- "
                f"{artifact.get('kind', 'artifact')}: "
                f"{artifact.get('name', '')} "
                f"({artifact.get('status', '')}) "
                f"{artifact.get('uri', '')}"
            )
    else:
        lines.append("- No artifact references were produced.")

    errors = manifest.get("errors") or []
    if errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error}" for error in errors)

    warnings = manifest.get("warnings") or []
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines).strip() + "\n"
