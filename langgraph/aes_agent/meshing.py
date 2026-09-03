from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from aes_agent.mcp_client import StreamableHTTPMCPClient
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.mesh import MeshArtifact, MeshQualityReport
from aes_agent.specs.validation import validate_geometry_spec
from aes_agent.state import AgentState


MESHING_TOOL_NAME = "mesh_geometry"
MESHING_PROVIDER = "mcp:meshing"
AES_MESH_URI_PREFIX = "aes://artifacts/meshes/"
logger = logging.getLogger("aes_agent.meshing")


class MeshingClient(Protocol):
    def list_tools(self) -> list[dict[str, Any]]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


def execute_mesh_geometry(
    state: AgentState,
    *,
    client: MeshingClient | None = None,
    execute: bool | None = None,
) -> dict[str, Any]:
    geometry_value = state.get("geometry_spec")
    geometry, report = (
        validate_geometry_spec(geometry_value)
        if isinstance(geometry_value, dict) and geometry_value
        else (None, None)
    )
    if geometry is None:
        errors = report.errors if report else ["A validated GeometrySpec is required."]
        return _output("failed", errors=errors)
    if geometry.source.kind == "surface_scan":
        return _output(
            "unsupported_not_implemented",
            errors=[
                "STL/OBJ/PLY surface reconstruction is a declared placeholder and is not implemented."
            ],
            capability="surface_scan_reconstruction",
        )

    should_execute = _execution_enabled() if execute is None else bool(execute)
    if not should_execute:
        planned = _planned_mesh_artifact(geometry)
        return _output(
            "planned",
            execution_mode="planned",
            mesh_artifact=planned.model_dump(mode="json"),
            warnings=["Meshing execution is disabled; AES produced a planned MeshArtifact."],
        )

    client = client or _default_client()
    if client is None:
        return _output(
            "failed",
            errors=["MESHING_MCP_URL is not configured."],
        )
    tools = {item.get("name") for item in client.list_tools() if isinstance(item, dict)}
    if "generate_mesh" not in tools:
        return _output(
            "failed",
            errors=["The configured meshing provider does not expose generate_mesh."],
        )
    logger.info("Meshing MCP generation started: source_kind=%s", geometry.source.kind)
    result = client.call_tool(
        "generate_mesh",
        {"geometry_spec": geometry.model_dump(mode="json")},
    )
    errors = _result_errors(result)
    if errors:
        return _output(
            "failed",
            execution_mode="failed",
            errors=errors,
            warnings=_strings(result.get("warnings")),
            provider_result=result,
        )
    mesh_value = result.get("mesh_artifact")
    try:
        mesh = MeshArtifact.model_validate(mesh_value)
    except Exception as exc:
        return _output(
            "failed",
            execution_mode="failed",
            errors=[f"Meshing provider returned an invalid MeshArtifact: {exc}"],
            provider_result=result,
        )
    return _output(
        "completed",
        execution_mode="executed",
        mesh_artifact=mesh.model_dump(mode="json"),
        artifacts=list(result.get("artifacts") or mesh.artifacts),
        warnings=_strings(result.get("warnings")),
        provider_result=result,
    )


def mesh_artifact_from_state(state: AgentState) -> MeshArtifact | None:
    direct = state.get("mesh_artifact")
    if isinstance(direct, dict) and direct:
        try:
            return MeshArtifact.model_validate(direct)
        except Exception:
            pass
    for result in reversed(state.get("tool_results", [])):
        if not isinstance(result, dict) or result.get("tool_name") != MESHING_TOOL_NAME:
            continue
        output = result.get("output") or {}
        value = output.get("mesh_artifact") if isinstance(output, dict) else None
        if isinstance(value, dict):
            try:
                return MeshArtifact.model_validate(value)
            except Exception:
                return None
    return None


def mesh_runner_inputs(mesh: MeshArtifact | None) -> list[dict[str, str]]:
    if mesh is None or mesh.mesh_uri.startswith("builtin://") or mesh.mesh_uri.startswith("mesh://"):
        return []
    if not mesh.mesh_uri.startswith(AES_MESH_URI_PREFIX):
        raise ValueError(
            "The solver accepts only AES-owned mesh artifacts. Persist the "
            "validated provider mesh before FEniCS execution."
        )
    return [{"uri": mesh.mesh_uri, "target": "mesh.msh"}]


def _planned_mesh_artifact(geometry: GeometrySpec) -> MeshArtifact:
    primitive_rectangle = (
        geometry.source.kind == "primitives"
        and len(geometry.source.primitives) == 1
        and geometry.source.primitives[0].shape == "rectangle"
    )
    uri = "builtin://rectangle" if primitive_rectangle else "mesh://pending"
    return MeshArtifact(
        status="planned",
        source_kind=geometry.source.kind,
        dimension=geometry.dimension,
        cell_type=geometry.mesh.cell_type,
        mesh_uri=uri,
        tag_map={region.name: index + 1 for index, region in enumerate(geometry.regions)},
        quality=MeshQualityReport(
            status="not_evaluated",
            warnings=["Mesh quality requires live provider execution."],
        ),
        provenance={"provider": MESHING_PROVIDER, "mode": "planned"},
    )


def _default_client() -> MeshingClient | None:
    url = os.getenv("MESHING_MCP_URL", "").strip()
    if not url:
        return None
    return StreamableHTTPMCPClient(
        url,
        timeout=int(os.getenv("MESHING_MCP_TIMEOUT", "180")),
        protocol_version=os.getenv("MESHING_MCP_PROTOCOL", "2025-06-18"),
    )


def _execution_enabled() -> bool:
    return os.getenv("MESHING_EXECUTE", "false").lower() in {"1", "true", "yes", "on"}


def _result_errors(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return ["Meshing provider returned a non-object result."]
    errors = _strings(result.get("errors"))
    if errors:
        return errors
    if str(result.get("status", "")).lower() in {"failed", "unsupported_not_implemented"}:
        return [str(result.get("message") or "Meshing provider failed.")]
    return []


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if value else []


def _output(
    status: str,
    *,
    execution_mode: str = "failed",
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": status,
        "execution_mode": execution_mode,
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        **extra,
    }
