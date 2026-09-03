from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aes_agent.meshing import AES_MESH_URI_PREFIX, mesh_artifact_from_state
from aes_agent.specs.mesh import MeshArtifact
from aes_agent.state import AgentState


MESH_ARTIFACT_STORE_TOOL_NAME = "mesh_artifact_store"
MESH_ARTIFACT_STORE_PROVIDER = "local:mesh_artifact_store"
MESHING_URI_PREFIX = "mcp://meshing/workspace/"
DEFAULT_ARTIFACT_ROOT = "artifacts"
DEFAULT_MESH_INPUT_ROOT = "/mesh-inputs"
logger = logging.getLogger("aes_agent.mesh_artifact_store")


def persist_mesh_artifact(state: AgentState) -> dict[str, Any]:
    mesh = mesh_artifact_from_state(state)
    if mesh is None:
        return _output(
            "failed",
            errors=["A validated MeshArtifact is required before mesh persistence."],
        )
    if mesh.quality.status != "valid":
        return _output(
            "failed",
            errors=["Only a quality-validated mesh can enter the AES artifact store."],
        )
    if mesh.mesh_uri.startswith(AES_MESH_URI_PREFIX):
        return _existing_mesh_output(mesh)
    if mesh.mesh_uri.startswith(("builtin://", "mesh://")):
        return _output(
            "planned",
            execution_mode="skipped",
            mesh_artifact=mesh.model_dump(mode="json"),
            artifacts=list(mesh.artifacts),
            warnings=["The planned built-in mesh has no provider bundle to persist."],
        )
    if not mesh.mesh_uri.startswith(MESHING_URI_PREFIX):
        return _output(
            "failed",
            errors=[f"Unsupported transient mesh URI: {mesh.mesh_uri}"],
        )

    try:
        sources = _resolve_mesh_bundle(mesh)
        digest = _bundle_digest(sources)
        artifact_root = Path(
            os.getenv("AES_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT)
        ).resolve()
        target_dir = artifact_root / "meshes" / digest
        created = _store_bundle(mesh, sources, target_dir, digest)
        stored_mesh = _stored_mesh_artifact(mesh, sources, target_dir, digest)
    except (OSError, ValueError) as exc:
        logger.exception("Durable mesh persistence failed: mesh_uri=%s", mesh.mesh_uri)
        return _output(
            "failed",
            errors=[f"Failed to persist the validated mesh bundle: {exc}"],
        )

    logger.info(
        "Durable mesh artifact ready: mesh_id=sha256:%s files=%s mode=%s path=%s",
        digest,
        len(sources),
        "stored" if created else "reused",
        target_dir,
    )
    return _output(
        "completed",
        execution_mode="stored" if created else "reused",
        mesh_id=f"sha256:{digest}",
        mesh_artifact=stored_mesh.model_dump(mode="json"),
        artifacts=list(stored_mesh.artifacts),
        artifact_dir=str(target_dir),
    )


def _resolve_mesh_bundle(mesh: MeshArtifact) -> list[tuple[dict[str, Any], Path]]:
    input_root = Path(
        os.getenv("AES_MESH_PROVIDER_ROOT", DEFAULT_MESH_INPUT_ROOT)
    ).resolve()
    candidates = [item for item in mesh.artifacts if isinstance(item, dict)]
    required_uris = [mesh.mesh_uri, mesh.cell_tags_uri, mesh.facet_tags_uri]
    known_uris = {str(item.get("uri", "")) for item in candidates}
    for uri in required_uris:
        if uri and uri not in known_uris:
            candidates.append(_synthetic_reference(uri))

    sources: list[tuple[dict[str, Any], Path]] = []
    names: set[str] = set()
    for artifact in candidates:
        uri = str(artifact.get("uri", ""))
        if not uri.startswith(MESHING_URI_PREFIX):
            continue
        relative = uri.removeprefix(MESHING_URI_PREFIX)
        source = (input_root / relative).resolve()
        if source != input_root and input_root not in source.parents:
            raise ValueError(f"Mesh artifact URI escapes the provider workspace: {uri}")
        if not source.is_file():
            raise ValueError(f"Mesh artifact does not exist: {uri}")
        name = source.name
        if name in names:
            raise ValueError(f"Duplicate mesh bundle filename: {name}")
        names.add(name)
        sources.append((dict(artifact), source))

    if not sources:
        raise ValueError("The MeshArtifact contains no materializable provider files.")
    if not any(source.name == "mesh.msh" for _, source in sources):
        raise ValueError("The mesh bundle does not contain the required mesh.msh file.")
    return sorted(sources, key=lambda item: item[1].name)


def _synthetic_reference(uri: str) -> dict[str, Any]:
    name = Path(uri.removeprefix(MESHING_URI_PREFIX)).name
    return {
        "name": name,
        "kind": "mesh",
        "status": "available",
        "uri": uri,
        "storage": "provider_workspace",
        "media_type": "application/octet-stream",
        "producer": {"provider": "mcp:meshing", "tool_name": "generate_mesh"},
        "metadata": {},
    }


def _bundle_digest(sources: list[tuple[dict[str, Any], Path]]) -> str:
    digest = hashlib.sha256()
    for _, source in sources:
        digest.update(source.name.encode("utf-8"))
        digest.update(b"\0")
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _store_bundle(
    mesh: MeshArtifact,
    sources: list[tuple[dict[str, Any], Path]],
    target_dir: Path,
    digest: str,
) -> bool:
    if target_dir.is_dir():
        if not (target_dir / "mesh.msh").is_file():
            raise ValueError(f"Existing mesh artifact is incomplete: {target_dir}")
        return False

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = target_dir.parent / f".{digest}.{uuid.uuid4().hex}.tmp"
    temporary_dir.mkdir(parents=False, exist_ok=False)
    try:
        for _, source in sources:
            shutil.copy2(source, temporary_dir / source.name)
        stored_mesh = _stored_mesh_artifact(mesh, sources, target_dir, digest)
        _write_json(
            temporary_dir / "mesh_artifact.json",
            stored_mesh.model_dump(mode="json"),
        )
        _write_json(
            temporary_dir / "manifest.json",
            {
                "schema_version": "1.0",
                "mesh_id": f"sha256:{digest}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_mesh_uri": mesh.mesh_uri,
                "mesh_artifact": stored_mesh.model_dump(mode="json"),
            },
        )
        try:
            temporary_dir.rename(target_dir)
        except FileExistsError:
            if not (target_dir / "mesh.msh").is_file():
                raise
            return False
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    return True


def _stored_mesh_artifact(
    mesh: MeshArtifact,
    sources: list[tuple[dict[str, Any], Path]],
    target_dir: Path,
    digest: str,
) -> MeshArtifact:
    uri_by_source: dict[str, str] = {}
    artifacts: list[dict[str, Any]] = []
    for artifact, source in sources:
        source_uri = str(artifact.get("uri", ""))
        uri = f"{AES_MESH_URI_PREFIX}{digest}/{source.name}"
        uri_by_source[source_uri] = uri
        artifacts.append(
            {
                "name": source.name,
                "kind": str(artifact.get("kind", "mesh")),
                "status": "stored",
                "uri": uri,
                "storage": "aes_artifact_store",
                "media_type": str(
                    artifact.get("media_type", "application/octet-stream")
                ),
                "producer": {
                    "provider": MESH_ARTIFACT_STORE_PROVIDER,
                    "tool_name": MESH_ARTIFACT_STORE_TOOL_NAME,
                },
                "metadata": {
                    "path": str(target_dir / source.name),
                    "size_bytes": source.stat().st_size,
                    "sha256": _file_digest(source),
                    "source_uri": source_uri,
                },
            }
        )

    value = mesh.model_dump(mode="json")
    value["mesh_uri"] = uri_by_source[mesh.mesh_uri]
    for field_name in ("cell_tags_uri", "facet_tags_uri"):
        source_uri = value.get(field_name)
        if source_uri:
            value[field_name] = uri_by_source.get(source_uri, source_uri)
    value["artifacts"] = artifacts
    value["provenance"] = {
        **mesh.provenance,
        "source_mesh_uri": mesh.mesh_uri,
        "artifact_store": {
            "provider": MESH_ARTIFACT_STORE_PROVIDER,
            "mesh_id": f"sha256:{digest}",
        },
    }
    return MeshArtifact.model_validate(value)


def _existing_mesh_output(mesh: MeshArtifact) -> dict[str, Any]:
    artifact_root = Path(
        os.getenv("AES_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT)
    ).resolve()
    relative = mesh.mesh_uri.removeprefix("aes://artifacts/")
    source = (artifact_root / relative).resolve()
    if source != artifact_root and artifact_root not in source.parents:
        return _output("failed", errors=["Stored mesh URI escapes the artifact root."])
    if not source.is_file():
        return _output(
            "failed",
            errors=[f"Stored mesh artifact does not exist: {mesh.mesh_uri}"],
        )
    mesh_id = mesh.mesh_uri.removeprefix(AES_MESH_URI_PREFIX).split("/", 1)[0]
    return _output(
        "completed",
        execution_mode="reused",
        mesh_id=f"sha256:{mesh_id}",
        mesh_artifact=mesh.model_dump(mode="json"),
        artifacts=list(mesh.artifacts),
        artifact_dir=str(source.parent),
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


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
