from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aes_agent.mesh_artifact_store import persist_mesh_artifact


class MeshArtifactStoreTests(unittest.TestCase):
    def test_persists_complete_mesh_bundle_and_returns_aes_uri(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider_root = root / "provider"
            artifact_root = root / "artifacts"
            state = _mesh_state(provider_root)

            with patch.dict(
                os.environ,
                {
                    "AES_MESH_PROVIDER_ROOT": str(provider_root),
                    "AES_ARTIFACT_ROOT": str(artifact_root),
                },
            ):
                output = persist_mesh_artifact(state)
                repeated = persist_mesh_artifact(state)

            self.assertEqual(output["status"], "completed")
            self.assertEqual(output["execution_mode"], "stored")
            self.assertEqual(repeated["execution_mode"], "reused")
            self.assertTrue(
                output["mesh_artifact"]["mesh_uri"].startswith(
                    "aes://artifacts/meshes/"
                )
            )
            stored_dir = Path(output["artifact_dir"])
            self.assertEqual((stored_dir / "mesh.msh").read_text(), "mesh-data")
            self.assertTrue((stored_dir / "mesh.xdmf").is_file())
            self.assertTrue((stored_dir / "mesh_artifact.json").is_file())
            manifest = json.loads((stored_dir / "manifest.json").read_text())
            self.assertEqual(
                manifest["source_mesh_uri"],
                "mcp://meshing/workspace/runs/run-1/mesh.msh",
            )
            self.assertEqual(
                output["mesh_artifact"]["provenance"]["source_mesh_uri"],
                manifest["source_mesh_uri"],
            )

    def test_missing_provider_artifact_fails_before_solver_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider_root = root / "provider"
            state = _mesh_state(provider_root)
            (provider_root / "runs" / "run-1" / "mesh.msh").unlink()

            with patch.dict(
                os.environ,
                {
                    "AES_MESH_PROVIDER_ROOT": str(provider_root),
                    "AES_ARTIFACT_ROOT": str(root / "artifacts"),
                },
            ):
                output = persist_mesh_artifact(state)

            self.assertEqual(output["status"], "failed")
            self.assertIn("does not exist", output["errors"][0])


def _mesh_state(provider_root: Path) -> dict:
    run_dir = provider_root / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    files = {
        "mesh.msh": "mesh-data",
        "mesh.xdmf": "mesh-xdmf",
        "mesh.h5": "mesh-h5",
        "tag_map.json": '{"domain": 1, "boundary": 2}',
    }
    artifacts = []
    for name, content in files.items():
        (run_dir / name).write_text(content, encoding="utf-8")
        artifacts.append(
            {
                "name": name,
                "kind": "mesh",
                "status": "available",
                "uri": f"mcp://meshing/workspace/runs/run-1/{name}",
                "storage": "provider_workspace",
                "media_type": "application/octet-stream",
                "producer": {
                    "provider": "mcp:meshing",
                    "tool_name": "generate_mesh",
                },
                "metadata": {},
            }
        )
    return {
        "mesh_artifact": {
            "schema_version": "1.0",
            "status": "completed",
            "source_kind": "primitives",
            "dimension": 2,
            "cell_type": "triangle",
            "mesh_uri": "mcp://meshing/workspace/runs/run-1/mesh.msh",
            "cell_tags_uri": "mcp://meshing/workspace/runs/run-1/mesh.xdmf",
            "facet_tags_uri": None,
            "tag_map": {"domain": 1, "boundary": 2},
            "quality": {
                "schema_version": "1.0",
                "status": "valid",
                "element_count": 10,
                "node_count": 8,
                "errors": [],
                "warnings": [],
            },
            "artifacts": artifacts,
            "provenance": {
                "provider": "aes-meshing-mcp",
                "run_id": "run-1",
            },
        }
    }


if __name__ == "__main__":
    unittest.main()
