from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any


SERVER_NAME = "aes-meshing-mcp"
SERVER_VERSION = "0.1.0"
WORKSPACE_URI_PREFIX = "mcp://meshing/workspace/"
TOOLS = {
    "inspect_geometry": {
        "description": "Inspect typed CSG, CAD, or mesh-file geometry without solving a PDE.",
        "required": ["geometry_spec"],
    },
    "generate_mesh": {
        "description": "Compile a typed GeometrySpec into a validated MeshArtifact.",
        "required": ["geometry_spec"],
    },
    "validate_mesh": {
        "description": "Validate an MSH or XDMF mesh stored in the provider workspace.",
        "required": ["artifact_path"],
        "optional": ["geometry_spec", "dimension"],
    },
    "convert_mesh": {
        "description": "Convert a provider-workspace MSH or XDMF mesh.",
        "required": ["artifact_path", "target_format"],
    },
}
GMSH_LOCK = Lock()


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("MESHING_LOG_LEVEL", "INFO").upper(),
        format="meshing-mcp | %(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,
    )


configure_logging()
logger = logging.getLogger("meshing_mcp")


class RpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION})
            return
        self._send_json(404, {"error": "not_found", "message": "Use POST /mcp."})

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._send_json(404, {"error": "not_found"})
            return
        request_id: Any = None
        try:
            payload = self._read_json()
            request_id = payload.get("id")
            method = str(payload.get("method", ""))
            params = payload.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(-32602, "JSON-RPC params must be an object.")
            logger.info("MCP request: method=%s id=%s", method, request_id)
            if _content_logging_enabled():
                logger.info("MCP request content: %s", _truncate(json.dumps(params, default=str)))
            if request_id is None:
                self.send_response(202)
                self.end_headers()
                return
            result = _handle_request(method, params)
            self._send_json(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except RpcError as exc:
            logger.warning("MCP request rejected: %s", exc.message)
            self._send_json(
                200,
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": exc.code, "message": exc.message}},
            )
        except Exception as exc:
            logger.exception("Unhandled meshing provider error")
            self._send_json(
                500,
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}},
            )

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("HTTP access: client=%s message=%s", self.address_string(), fmt % args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RpcError(-32700, f"Invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise RpcError(-32600, "JSON-RPC payload must be an object.")
        return value

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _handle_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": str(params.get("protocolVersion", "2025-06-18")),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    if method == "tools/list":
        return {"tools": [_tool_schema(name, data) for name, data in TOOLS.items()]}
    if method != "tools/call":
        raise RpcError(-32601, f"Unknown method: {method}")
    name = str(params.get("name", ""))
    arguments = params.get("arguments") or {}
    if name not in TOOLS:
        raise RpcError(-32601, f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise RpcError(-32602, "Tool arguments must be an object.")
    missing = [field for field in TOOLS[name]["required"] if field not in arguments]
    if missing:
        raise RpcError(-32602, f"Missing required arguments: {missing}")
    if name == "inspect_geometry":
        return _inspect_geometry(arguments["geometry_spec"])
    if name == "generate_mesh":
        return _generate_mesh(arguments["geometry_spec"])
    if name == "validate_mesh":
        return _validate_mesh_tool(arguments)
    return _convert_mesh_tool(arguments)


def _tool_schema(name: str, data: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "geometry_spec": {"type": "object"},
        "artifact_path": {"type": "string"},
        "target_format": {"type": "string", "enum": ["msh", "xdmf"]},
        "dimension": {"type": "integer", "minimum": 1, "maximum": 3},
    }
    fields = [*data["required"], *data.get("optional", [])]
    return {
        "name": name,
        "description": data["description"],
        "inputSchema": {
            "type": "object",
            "required": data["required"],
            "properties": {key: properties[key] for key in fields},
            "additionalProperties": False,
        },
    }


def _inspect_geometry(value: Any) -> dict[str, Any]:
    spec = _geometry_spec(value)
    source = spec["source"]
    if source["kind"] == "surface_scan":
        return _surface_placeholder(source)
    if source["kind"] == "mesh_file":
        path = _workspace_input(source["artifact_path"])
        quality = _meshio_quality(path, spec)
        return {
            "schema_version": "1.0",
            "status": "completed" if quality["status"] == "valid" else "failed",
            "source_kind": "mesh_file",
            "path": str(path),
            "quality": quality,
            "errors": quality["errors"],
            "warnings": quality["warnings"],
        }

    with _gmsh_session() as gmsh:
        gmsh.model.add("aes_geometry_inspection")
        entity_map, primitive_map, top_entities = _build_occ_geometry(gmsh, spec)
        gmsh.model.occ.synchronize()
        entities = _entity_descriptions(gmsh)
        return {
            "schema_version": "1.0",
            "status": "completed",
            "source_kind": source["kind"],
            "top_entities": [list(item) for item in top_entities],
            "named_objects": {key: [list(item) for item in items] for key, items in entity_map.items()},
            "primitive_count": len(primitive_map),
            "entities": entities,
            "errors": [],
            "warnings": [],
        }


def _generate_mesh(value: Any) -> dict[str, Any]:
    spec = _geometry_spec(value)
    source_kind = spec["source"]["kind"]
    if source_kind == "surface_scan":
        return _surface_placeholder(spec["source"])

    run_id, run_dir = _new_run_dir()
    (run_dir / "geometry_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    logger.info("Mesh generation started: run_id=%s source=%s", run_id, source_kind)
    try:
        if source_kind == "mesh_file":
            result = _import_existing_mesh(spec, run_id, run_dir)
        else:
            result = _generate_with_gmsh(spec, run_id, run_dir)
    except Exception as exc:
        message = f"Meshing provider failed for {source_kind}: {exc}"
        logger.exception("Mesh generation failed: run_id=%s source=%s", run_id, source_kind)
        return {
            "schema_version": "1.0",
            "status": "failed",
            "message": message,
            "run_id": run_id,
            "artifacts": _collect_artifacts(run_id, run_dir),
            "errors": [message],
            "warnings": [],
        }
    logger.info(
        "Mesh generation finished: run_id=%s status=%s elements=%s",
        run_id,
        result.get("status"),
        (result.get("mesh_artifact") or {}).get("quality", {}).get("element_count", 0),
    )
    return result


def _generate_with_gmsh(spec: dict[str, Any], run_id: str, run_dir: Path) -> dict[str, Any]:
    with _gmsh_session() as gmsh:
        gmsh.model.add(f"aes_{run_id}")
        entity_map, primitive_map, top_entities = _build_occ_geometry(gmsh, spec)
        gmsh.model.occ.synchronize()
        tag_map, region_entities = _create_physical_groups(
            gmsh, spec, entity_map, primitive_map, top_entities
        )
        _configure_mesh(gmsh, spec, region_entities)
        dimension = int(spec["dimension"])
        gmsh.model.mesh.generate(dimension)
        gmsh.model.mesh.setOrder(int(spec["mesh"].get("order", 1)))
        quality = _gmsh_quality(gmsh, spec)
        mesh_path = run_dir / "mesh.msh"
        gmsh.write(str(mesh_path))
        geometry_report = {
            "source_kind": spec["source"]["kind"],
            "dimension": dimension,
            "entities": _entity_descriptions(gmsh),
            "regions": {key: [list(item) for item in values] for key, values in region_entities.items()},
        }

    (run_dir / "tag_map.json").write_text(json.dumps(tag_map, indent=2), encoding="utf-8")
    (run_dir / "geometry_report.json").write_text(json.dumps(geometry_report, indent=2), encoding="utf-8")
    conversion_warnings = _write_xdmf_outputs(run_dir / "mesh.msh", run_dir, spec)
    quality["warnings"].extend(conversion_warnings)
    (run_dir / "mesh_quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
    return _mesh_result(spec, run_id, run_dir, quality, tag_map, imported=False)


def _import_existing_mesh(
    spec: dict[str, Any], run_id: str, run_dir: Path
) -> dict[str, Any]:
    source = _workspace_input(spec["source"]["artifact_path"])
    suffix = source.suffix.lower()
    destination = run_dir / source.name
    shutil.copy2(source, destination)
    meshio = _import_meshio()
    mesh = meshio.read(destination)
    _normalize_physical_cell_data(mesh, spec)
    msh_path = run_dir / "mesh.msh"
    if suffix == ".msh":
        if destination != msh_path:
            shutil.copy2(destination, msh_path)
    else:
        meshio.write(msh_path, mesh, file_format="gmsh22")
    quality = _meshio_quality(msh_path, spec)
    tag_map = {
        str(name): int(value[0])
        for name, value in (mesh.field_data or {}).items()
        if len(value) >= 2
    }
    tag_map.update(
        {
            str(name): int(tag)
            for name, tag in (spec["source"].get("tag_map") or {}).items()
        }
    )
    for region in spec["regions"]:
        selector = region.get("selector") or {}
        explicit = selector.get("entity_tags") or []
        if region["name"] not in tag_map and selector.get("kind") == "entity_tags" and len(explicit) == 1:
            tag_map[region["name"]] = int(explicit[0])
    missing_regions = sorted({region["name"] for region in spec["regions"]} - set(tag_map))
    if missing_regions:
        quality["errors"].append(
            f"Imported mesh does not provide physical tags for regions: {missing_regions}."
        )
        quality["status"] = "invalid"
    _validate_imported_region_tags(mesh, spec, tag_map, quality)
    (run_dir / "tag_map.json").write_text(json.dumps(tag_map, indent=2), encoding="utf-8")
    quality["warnings"].extend(_write_xdmf_outputs(msh_path, run_dir, spec))
    (run_dir / "mesh_quality.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")
    return _mesh_result(spec, run_id, run_dir, quality, tag_map, imported=True)


def _build_occ_geometry(gmsh: Any, spec: dict[str, Any]):
    source = spec["source"]
    dimension = int(spec["dimension"])
    entity_map: dict[str, list[tuple[int, int]]] = {}
    primitive_map: dict[str, dict[str, Any]] = {}
    if source["kind"] == "cad":
        path = _workspace_input(source["artifact_path"])
        imported = gmsh.model.occ.importShapes(str(path), highestDimOnly=False)
        repair = source.get("repair") or {}
        if repair.get("heal_shapes", True):
            imported = gmsh.model.occ.healShapes(
                imported,
                tolerance=float(repair.get("tolerance", 1.0e-8)),
                fixDegenerated=True,
                fixSmallEdges=True,
                fixSmallFaces=True,
                sewFaces=True,
                makeSolids=dimension == 3,
            )
        if repair.get("remove_duplicates", True):
            gmsh.model.occ.removeAllDuplicates()
        top_entities = [tuple(item) for item in gmsh.model.occ.getEntities(dimension)]
        if not top_entities:
            top_entities = [tuple(item) for item in imported if int(item[0]) == dimension]
        if not top_entities:
            raise RpcError(-32602, "CAD import produced no top-dimensional entities.")
        entity_map["domain"] = top_entities
        return entity_map, primitive_map, top_entities

    for primitive in source["primitives"]:
        dim_tag = _add_primitive(gmsh, primitive, dimension)
        entity_map[primitive["id"]] = [dim_tag]
        primitive_map[primitive["id"]] = primitive

    top_entities = [item for values in entity_map.values() for item in values]
    if source["kind"] == "csg":
        for operation in source["operations"]:
            objects = _named_entities(entity_map, operation["objects"])
            tools = _named_entities(entity_map, operation.get("tools", []))
            op_type = operation["type"]
            if op_type == "union":
                result, mapping = gmsh.model.occ.fuse(objects, tools, removeObject=True, removeTool=True)
            elif op_type == "difference":
                result, mapping = gmsh.model.occ.cut(objects, tools, removeObject=True, removeTool=True)
            elif op_type == "intersection":
                result, mapping = gmsh.model.occ.intersect(objects, tools, removeObject=True, removeTool=True)
            else:
                result, mapping = gmsh.model.occ.fragment(objects, tools, removeObject=True, removeTool=True)
            result = [tuple(item) for item in result if int(item[0]) == dimension]
            entity_map[operation["result"]] = result
            for name, mapped in zip([*operation["objects"], *operation.get("tools", [])], mapping):
                same_dim = [tuple(item) for item in mapped if int(item[0]) == dimension]
                if same_dim:
                    entity_map[name] = same_dim
            top_entities = result
    entity_map.setdefault("domain", top_entities)
    return entity_map, primitive_map, top_entities


def _add_primitive(gmsh: Any, primitive: dict[str, Any], dimension: int) -> tuple[int, int]:
    shape = primitive["shape"]
    if shape == "rectangle":
        x, y = _vector(primitive["origin"], 2)
        dx, dy = _vector(primitive["size"], 2)
        return 2, gmsh.model.occ.addRectangle(x, y, 0.0, dx, dy)
    if shape == "disk":
        x, y = _vector(primitive["center"], 2)
        return 2, gmsh.model.occ.addDisk(x, y, 0.0, float(primitive["radius"]), float(primitive["radius"]))
    if shape == "box":
        x, y, z = _vector(primitive["origin"], 3)
        dx, dy, dz = _vector(primitive["size"], 3)
        return 3, gmsh.model.occ.addBox(x, y, z, dx, dy, dz)
    if shape == "sphere":
        x, y, z = _vector(primitive["center"], 3)
        return 3, gmsh.model.occ.addSphere(x, y, z, float(primitive["radius"]))
    if shape == "cylinder":
        x, y, z = _vector(primitive["origin"], 3)
        dx, dy, dz = _vector(primitive["axis"], 3)
        return 3, gmsh.model.occ.addCylinder(x, y, z, dx, dy, dz, float(primitive["radius"]))
    raise RpcError(-32602, f"Unsupported primitive shape: {shape}")


def _create_physical_groups(
    gmsh: Any,
    spec: dict[str, Any],
    entity_map: dict[str, list[tuple[int, int]]],
    primitive_map: dict[str, dict[str, Any]],
    top_entities: list[tuple[int, int]],
) -> tuple[dict[str, int], dict[str, list[tuple[int, int]]]]:
    tag_map: dict[str, int] = {}
    region_entities: dict[str, list[tuple[int, int]]] = {}
    for physical_tag, region in enumerate(spec["regions"], start=1):
        entities = _resolve_region(gmsh, region, entity_map, primitive_map, top_entities)
        dimension = int(region["dimension"])
        tags = sorted({tag for dim, tag in entities if dim == dimension})
        if not tags:
            raise RpcError(-32602, f"Region {region['name']!r} resolved to no entities.")
        gmsh.model.addPhysicalGroup(dimension, tags, physical_tag)
        gmsh.model.setPhysicalName(dimension, physical_tag, region["name"])
        tag_map[region["name"]] = physical_tag
        region_entities[region["name"]] = [(dimension, tag) for tag in tags]
    return tag_map, region_entities


def _resolve_region(
    gmsh: Any,
    region: dict[str, Any],
    entity_map: dict[str, list[tuple[int, int]]],
    primitive_map: dict[str, dict[str, Any]],
    top_entities: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    selector = region["selector"]
    kind = selector["kind"]
    dimension = int(region["dimension"])
    reference = selector.get("reference") or "domain"
    if kind == "object":
        return [item for item in entity_map.get(reference, []) if item[0] == dimension]
    if kind == "entity_tags":
        return [(dimension, int(tag)) for tag in selector.get("entity_tags", [])]
    if kind == "bounding_box":
        bounds = list(selector.get("bounds") or [])
        if len(bounds) not in {4, 6}:
            raise RpcError(-32602, "bounding_box selector requires 4 or 6 values.")
        if len(bounds) == 4:
            bounds = [bounds[0], bounds[1], -1.0e-12, bounds[2], bounds[3], 1.0e-12]
        # OpenCASCADE entity boxes commonly extend about 1e-7 beyond their
        # mathematical coordinates. Pad selectors at the model scale so an
        # exact semantic face selector remains stable across Gmsh versions.
        scale = max(1.0, *(abs(float(value)) for value in bounds))
        tolerance = max(1.0e-9, 1.0e-7 * scale)
        padded = [
            bounds[0] - tolerance,
            bounds[1] - tolerance,
            bounds[2] - tolerance,
            bounds[3] + tolerance,
            bounds[4] + tolerance,
            bounds[5] + tolerance,
        ]
        return [
            tuple(item)
            for item in gmsh.model.getEntitiesInBoundingBox(*padded, dim=dimension)
        ]
    boundaries = [
        tuple(item)
        for item in gmsh.model.getBoundary(top_entities, combined=False, oriented=False, recursive=False)
        if int(item[0]) == dimension
    ]
    if kind == "all_boundary" or reference in {"domain", ""}:
        return boundaries
    primitive = primitive_map.get(reference)
    if primitive:
        matches = [item for item in boundaries if _matches_primitive_boundary(gmsh, item, primitive)]
        if matches:
            return matches
    direct = entity_map.get(reference, [])
    if direct:
        try:
            return [
                tuple(item)
                for item in gmsh.model.getBoundary(direct, combined=False, oriented=False, recursive=False)
                if int(item[0]) == dimension
            ]
        except Exception:
            pass
    return []


def _matches_primitive_boundary(gmsh: Any, entity: tuple[int, int], primitive: dict[str, Any]) -> bool:
    bbox = gmsh.model.getBoundingBox(*entity)
    scale = max(1.0, *(abs(float(value)) for value in bbox))
    tolerance = 1.0e-6 * scale
    shape = primitive["shape"]
    if shape == "disk":
        cx, cy = _vector(primitive["center"], 2)
        radius = float(primitive["radius"])
        expected = (cx - radius, cy - radius, cx + radius, cy + radius)
        actual = (bbox[0], bbox[1], bbox[3], bbox[4])
        return all(abs(a - b) <= tolerance * max(1.0, abs(b)) for a, b in zip(actual, expected))
    if shape == "sphere":
        cx, cy, cz = _vector(primitive["center"], 3)
        radius = float(primitive["radius"])
        expected = (cx - radius, cy - radius, cz - radius, cx + radius, cy + radius, cz + radius)
        return all(abs(a - b) <= tolerance * max(1.0, abs(b)) for a, b in zip(bbox, expected))
    if shape == "cylinder":
        x, y, z = _vector(primitive["origin"], 3)
        dx, dy, dz = _vector(primitive["axis"], 3)
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= tolerance:
            return False
        direction = (dx / length, dy / length, dz / length)
        radius = float(primitive["radius"])
        start = (x, y, z)
        end = (x + dx, y + dy, z + dz)
        radial = tuple(radius * math.sqrt(max(0.0, 1.0 - component * component)) for component in direction)
        expected = (
            min(start[0], end[0]) - radial[0],
            min(start[1], end[1]) - radial[1],
            min(start[2], end[2]) - radial[2],
            max(start[0], end[0]) + radial[0],
            max(start[1], end[1]) + radial[1],
            max(start[2], end[2]) + radial[2],
        )
        return all(
            abs(actual - target) <= tolerance * max(1.0, abs(target))
            for actual, target in zip(bbox, expected)
        )
    origin = primitive.get("origin") or []
    size = primitive.get("size") or []
    if shape in {"rectangle", "box"} and origin and size:
        limits = [*origin, *[origin[index] + size[index] for index in range(len(size))]]
        entity_limits = [bbox[0], bbox[1], bbox[3], bbox[4]] if len(size) == 2 else list(bbox)
        return any(abs(value - target) <= tolerance for value in entity_limits for target in limits)
    return False


def _configure_mesh(gmsh: Any, spec: dict[str, Any], regions: dict[str, list[tuple[int, int]]]) -> None:
    size = float(spec["mesh"]["global_size"])
    gmsh.option.setNumber("Mesh.MeshSizeMin", size)
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    cell_type = spec["mesh"]["cell_type"]
    if cell_type in {"quadrilateral", "hexahedron"}:
        gmsh.option.setNumber("Mesh.RecombineAll", 1)
    fields: list[int] = []
    for refinement in spec["mesh"].get("refinements", []):
        entities = regions.get(refinement["region"], [])
        if not entities:
            continue
        distance_field = gmsh.model.mesh.field.add("Distance")
        dimension = entities[0][0]
        key = "CurvesList" if dimension == 1 else "SurfacesList"
        gmsh.model.mesh.field.setNumbers(distance_field, key, [tag for _, tag in entities])
        threshold = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(threshold, "InField", distance_field)
        gmsh.model.mesh.field.setNumber(threshold, "SizeMin", float(refinement["size"]))
        gmsh.model.mesh.field.setNumber(threshold, "SizeMax", size)
        gmsh.model.mesh.field.setNumber(threshold, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(threshold, "DistMax", float(refinement.get("distance") or size * 5))
        fields.append(threshold)
    if fields:
        minimum = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(minimum, "FieldsList", fields)
        gmsh.model.mesh.field.setAsBackgroundMesh(minimum)


def _gmsh_quality(gmsh: Any, spec: dict[str, Any]) -> dict[str, Any]:
    dimension = int(spec["dimension"])
    _, element_blocks, _ = gmsh.model.mesh.getElements(dimension)
    element_tags = [int(tag) for block in element_blocks for tag in block]
    node_tags, _, _ = gmsh.model.mesh.getNodes()
    qualities = list(gmsh.model.mesh.getElementQualities(element_tags, "minSJ")) if element_tags else []
    minimum = min(qualities) if qualities else None
    maximum = max(qualities) if qualities else None
    errors: list[str] = []
    requested = spec["mesh"].get("quality", {})
    max_elements = min(
        int(requested.get("maximum_elements", 2_000_000)),
        int(os.getenv("MESHING_MAX_ELEMENTS", "2000000")),
    )
    threshold = float(requested.get("minimum_scaled_jacobian", 0.0))
    if not element_tags:
        errors.append("Generated mesh contains no top-dimensional elements.")
    if len(element_tags) > max_elements:
        errors.append(f"Mesh contains {len(element_tags)} elements; limit is {max_elements}.")
    if minimum is not None and minimum <= threshold:
        errors.append(f"Minimum scaled Jacobian {minimum:.6g} does not exceed {threshold:.6g}.")
    return {
        "schema_version": "1.0",
        "status": "invalid" if errors else "valid",
        "element_count": len(element_tags),
        "node_count": len(node_tags),
        "minimum_quality": minimum,
        "maximum_quality": maximum,
        "metrics": {"minimum_scaled_jacobian": minimum or 0.0},
        "errors": errors,
        "warnings": [],
    }


def _normalize_physical_cell_data(mesh: Any, spec: dict[str, Any]) -> None:
    """Map common XDMF tag arrays to the Gmsh names used by DOLFINx."""

    if "gmsh:physical" in mesh.cell_data:
        return
    source = spec.get("source") or {}
    configured_name = str(source.get("physical_data_name") or "name_to_read")
    values = mesh.cell_data.get(configured_name)
    if values is None:
        return
    import numpy as np

    physical = [np.asarray(block, dtype=np.int32) for block in values]
    mesh.cell_data["gmsh:physical"] = physical
    mesh.cell_data.setdefault(
        "gmsh:geometrical",
        [np.asarray(block, dtype=np.int32) for block in values],
    )


def _validate_imported_region_tags(
    mesh: Any,
    spec: dict[str, Any],
    tag_map: dict[str, int],
    quality: dict[str, Any],
) -> None:
    source = spec.get("source") or {}
    configured_name = str(source.get("physical_data_name") or "name_to_read")
    physical = mesh.cell_data.get("gmsh:physical")
    if physical is None:
        physical = mesh.cell_data.get(configured_name)
    if physical is None or len(physical) != len(mesh.cells):
        quality["errors"].append(
            "Imported mesh does not contain physical-tag cell data for semantic regions."
        )
        quality["status"] = "invalid"
        return

    import numpy as np

    tags_by_dimension: dict[int, set[int]] = {}
    for block, values in zip(mesh.cells, physical):
        dimension = _cell_dimension(block.type)
        tags_by_dimension.setdefault(dimension, set()).update(
            int(value) for value in np.asarray(values).reshape(-1)
        )
    for region in spec.get("regions", []):
        name = str(region.get("name", ""))
        tag = tag_map.get(name)
        dimension = int(region.get("dimension", -1))
        if tag is not None and tag not in tags_by_dimension.get(dimension, set()):
            quality["errors"].append(
                f"Imported mesh tag {tag} for region {name!r} has no {dimension}D cells."
            )
    if quality["errors"]:
        quality["status"] = "invalid"


def _cell_dimension(cell_type: str) -> int:
    if cell_type in {"vertex"}:
        return 0
    if cell_type.startswith("line"):
        return 1
    if cell_type.startswith(("triangle", "quad")):
        return 2
    if cell_type.startswith(("tetra", "hexahedron", "wedge", "pyramid")):
        return 3
    return -1


def _meshio_quality(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    meshio = _import_meshio()
    import numpy as np

    mesh = meshio.read(path)
    dimension = int(spec.get("dimension", 0))
    requested = str(spec.get("mesh", {}).get("cell_type", ""))
    expected = {
        "line": "line",
        "triangle": "triangle",
        "quadrilateral": "quad",
        "tetrahedron": "tetra",
        "hexahedron": "hexahedron",
    }.get(requested)
    allowed = {1: ("line",), 2: ("triangle", "quad"), 3: ("tetra", "hexahedron")}[dimension]
    accepted = (expected,) if expected else allowed
    blocks = [
        block for block in mesh.cells
        if any(block.type.startswith(cell_type) for cell_type in accepted)
    ]
    element_count = sum(len(block.data) for block in blocks)
    errors: list[str] = []
    if not len(mesh.points):
        errors.append("Mesh contains no points.")
    elif not np.isfinite(mesh.points).all():
        errors.append("Mesh coordinates contain non-finite values.")
    if element_count == 0:
        errors.append(
            f"Mesh contains no cells matching requested type {requested!r} in dimension {dimension}."
        )
    max_elements = int(spec.get("mesh", {}).get("quality", {}).get("maximum_elements", 2_000_000))
    if element_count > max_elements:
        errors.append(f"Mesh contains {element_count} elements; limit is {max_elements}.")
    return {
        "schema_version": "1.0",
        "status": "invalid" if errors else "valid",
        "element_count": element_count,
        "node_count": len(mesh.points),
        "minimum_quality": None,
        "maximum_quality": None,
        "metrics": {},
        "errors": errors,
        "warnings": ["Imported-mesh Jacobian quality was not evaluated by this provider version."],
    }


def _write_xdmf_outputs(msh_path: Path, run_dir: Path, spec: dict[str, Any]) -> list[str]:
    meshio = _import_meshio()
    warnings: list[str] = []
    try:
        source = meshio.read(msh_path)
        dimension = int(spec["dimension"])
        top_types = {2: ("triangle", "quad"), 3: ("tetra", "hexahedron")}.get(dimension, ("line",))
        facet_types = {2: ("line",), 3: ("triangle", "quad")}.get(dimension, ("vertex",))
        _write_selected_xdmf(meshio, source, run_dir / "mesh.xdmf", top_types)
        if any(block.type in facet_types for block in source.cells):
            _write_selected_xdmf(meshio, source, run_dir / "facet_tags.xdmf", facet_types)
    except Exception as exc:
        warnings.append(f"XDMF conversion failed: {exc}")
    return warnings


def _write_selected_xdmf(meshio: Any, source: Any, path: Path, cell_types: tuple[str, ...]) -> None:
    selected = [block for block in source.cells if block.type in cell_types]
    if not selected:
        return
    cell_data: dict[str, list[Any]] = {}
    physical = source.cell_data.get("gmsh:physical", [])
    if physical and len(physical) == len(source.cells):
        selected_data = [data for block, data in zip(source.cells, physical) if block.type in cell_types]
        cell_data["name_to_read"] = selected_data
    meshio.write(path, meshio.Mesh(points=source.points, cells=selected, cell_data=cell_data))


def _mesh_result(
    spec: dict[str, Any],
    run_id: str,
    run_dir: Path,
    quality: dict[str, Any],
    tag_map: dict[str, int],
    *,
    imported: bool,
) -> dict[str, Any]:
    artifacts = _collect_artifacts(run_id, run_dir)
    mesh_uri = _artifact_uri(run_id, "mesh.msh")
    artifact = {
        "schema_version": "1.0",
        "status": "imported" if imported else "completed",
        "source_kind": spec["source"]["kind"],
        "dimension": int(spec["dimension"]),
        "cell_type": spec["mesh"]["cell_type"],
        "mesh_uri": mesh_uri,
        "cell_tags_uri": _artifact_uri(run_id, "mesh.xdmf") if (run_dir / "mesh.xdmf").exists() else None,
        "facet_tags_uri": _artifact_uri(run_id, "facet_tags.xdmf") if (run_dir / "facet_tags.xdmf").exists() else None,
        "tag_map": tag_map,
        "quality": quality,
        "artifacts": artifacts,
        "provenance": {"provider": SERVER_NAME, "version": SERVER_VERSION, "run_id": run_id},
    }
    errors = list(quality["errors"])
    return {
        "schema_version": "1.0",
        "status": "failed" if errors else "completed",
        "message": "Mesh imported and validated." if imported else "Geometry compiled and mesh generated.",
        "run_id": run_id,
        "mesh_artifact": artifact,
        "artifacts": artifacts,
        "errors": errors,
        "warnings": quality["warnings"],
    }


def _validate_mesh_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _workspace_input(arguments["artifact_path"])
    spec = arguments.get("geometry_spec") or {
        "dimension": int(arguments.get("dimension", 2)),
        "mesh": {"quality": {"maximum_elements": int(os.getenv("MESHING_MAX_ELEMENTS", "2000000"))}},
    }
    quality = _meshio_quality(path, spec)
    return {"status": "completed" if quality["status"] == "valid" else "failed", "quality": quality, "errors": quality["errors"], "warnings": quality["warnings"]}


def _convert_mesh_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    source = _workspace_input(arguments["artifact_path"])
    target_format = str(arguments["target_format"]).lower()
    run_id, run_dir = _new_run_dir()
    target = run_dir / f"mesh.{target_format}"
    meshio = _import_meshio()
    mesh = meshio.read(source)
    if target_format == "msh":
        meshio.write(target, mesh, file_format="gmsh22")
    else:
        meshio.write(target, mesh)
    return {"status": "completed", "run_id": run_id, "artifacts": _collect_artifacts(run_id, run_dir), "errors": [], "warnings": []}


def _surface_placeholder(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "unsupported_not_implemented",
        "capability": "surface_scan_reconstruction",
        "source_format": source.get("format", ""),
        "message": "STL/OBJ/PLY surface validation, repair, and volume reconstruction are not implemented and are reserved for a later provider version.",
        "errors": ["Surface-scan meshing is not implemented."],
        "warnings": [],
    }


def _geometry_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RpcError(-32602, "geometry_spec must be an object.")
    required = {"schema_version", "dimension", "source", "regions", "mesh"}
    missing = sorted(required - set(value))
    if missing:
        raise RpcError(-32602, f"geometry_spec is missing fields: {missing}")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("kind") not in {"primitives", "csg", "cad", "mesh_file", "surface_scan"}:
        raise RpcError(-32602, "geometry_spec.source.kind is invalid.")
    return value


def _workspace_root() -> Path:
    root = Path(os.getenv("MESHING_WORKSPACE", "/workspace")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _workspace_input(value: Any) -> Path:
    raw = str(value).strip()
    if raw.startswith(WORKSPACE_URI_PREFIX):
        raw = raw.removeprefix(WORKSPACE_URI_PREFIX)
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = _workspace_root() / candidate
    resolved = candidate.resolve()
    root = _workspace_root()
    if resolved != root and root not in resolved.parents:
        raise RpcError(-32602, "Input path must remain inside the meshing workspace.")
    if not resolved.is_file():
        raise RpcError(-32602, f"Input artifact does not exist: {raw}")
    return resolved


def _new_run_dir() -> tuple[str, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-{uuid.uuid4().hex[:12]}"
    run_dir = _workspace_root() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir


def _collect_artifacts(run_id: str, run_dir: Path) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted(run_dir.iterdir()):
        if not path.is_file():
            continue
        artifacts.append({
            "name": path.name,
            "kind": _artifact_kind(path.suffix.lower()),
            "status": "available",
            "uri": _artifact_uri(run_id, path.name),
            "storage": "provider_workspace",
            "media_type": _media_type(path.suffix.lower()),
            "producer": {"provider": f"mcp:{SERVER_NAME}", "tool_name": "generate_mesh"},
            "metadata": {"size_bytes": path.stat().st_size},
        })
    return artifacts


def _artifact_uri(run_id: str, name: str) -> str:
    return f"{WORKSPACE_URI_PREFIX}runs/{run_id}/{name}"


def _artifact_kind(suffix: str) -> str:
    if suffix in {".msh", ".xdmf", ".h5"}:
        return "mesh"
    if suffix == ".json":
        return "mesh_metadata"
    return "artifact"


def _media_type(suffix: str) -> str:
    return {".msh": "application/x-gmsh", ".xdmf": "application/x-xdmf", ".h5": "application/x-hdf5", ".json": "application/json"}.get(suffix, "application/octet-stream")


def _entity_descriptions(gmsh: Any) -> list[dict[str, Any]]:
    result = []
    for dimension, tag in gmsh.model.getEntities():
        bbox = gmsh.model.getBoundingBox(dimension, tag)
        try:
            center = gmsh.model.occ.getCenterOfMass(dimension, tag)
        except Exception:
            center = ()
        result.append({"dimension": dimension, "tag": tag, "bounding_box": list(bbox), "center_of_mass": list(center)})
    return result


def _named_entities(entity_map: dict[str, list[tuple[int, int]]], names: list[str]) -> list[tuple[int, int]]:
    result = []
    for name in names:
        if name not in entity_map:
            raise RpcError(-32602, f"Unknown CSG object: {name}")
        result.extend(entity_map[name])
    return result


def _vector(value: Any, length: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) < length:
        raise RpcError(-32602, f"Expected a coordinate vector with {length} values.")
    numbers = tuple(float(value[index]) for index in range(length))
    if not all(math.isfinite(item) for item in numbers):
        raise RpcError(-32602, "Coordinates must be finite.")
    return numbers


def _import_gmsh():
    try:
        import gmsh
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            f"Gmsh could not be loaded. Verify its native runtime libraries: {exc}"
        ) from exc
    return gmsh


@contextmanager
def _gmsh_session():
    gmsh = _import_gmsh()
    with GMSH_LOCK:
        gmsh.initialize(interruptible=False)
        try:
            yield gmsh
        finally:
            if gmsh.isInitialized():
                gmsh.finalize()


def _import_meshio():
    try:
        import meshio
    except ImportError as exc:
        raise RuntimeError("The meshing provider image does not contain meshio.") from exc
    return meshio


def _content_logging_enabled() -> bool:
    return os.getenv("MESHING_LOG_CONTENT", "false").lower() in {"1", "true", "yes", "on"}


def _truncate(value: str, limit: int = 2000) -> str:
    return value if len(value) <= limit else value[:limit] + "..."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logger.info("%s %s listening on http://%s:%s/mcp", SERVER_NAME, SERVER_VERSION, args.host, args.port)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
