from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_PATH = (
    Path(__file__).resolve().parents[1]
    / "providers"
    / "fenics"
    / "code_runner"
    / "server.py"
)
SPEC = importlib.util.spec_from_file_location("aes_fenics_code_runner", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)


class FenicsCodeRunnerInputTests(unittest.TestCase):
    def test_materializes_governed_aes_mesh_uri(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root = root / "artifacts"
            source = artifact_root / "meshes" / "abc123" / "mesh.msh"
            source.parent.mkdir(parents=True)
            source.write_text("mesh-data", encoding="utf-8")
            run_dir = root / "runner" / "run-2"
            run_dir.mkdir(parents=True)

            with patch.dict(
                os.environ,
                {"FENICS_RUNNER_ARTIFACT_ROOT": str(artifact_root)},
            ):
                copied = server._materialize_inputs(
                    [
                        {
                            "uri": "aes://artifacts/meshes/abc123/mesh.msh",
                            "target": "mesh.msh",
                        }
                    ],
                    run_dir,
                )

            self.assertEqual(copied, ["mesh.msh"])
            self.assertEqual(
                (run_dir / "mesh.msh").read_text(encoding="utf-8"),
                "mesh-data",
            )

    def test_rejects_transient_provider_uri(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)

            with self.assertRaisesRegex(server.RpcError, "AES-owned"):
                server._materialize_inputs(
                    [
                        {
                            "uri": "mcp://meshing/workspace/runs/run-1/mesh.msh",
                            "target": "mesh.msh",
                        }
                    ],
                    run_dir,
                )

    def test_rejects_aes_mesh_uri_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()

            with patch.dict(
                os.environ,
                {"FENICS_RUNNER_ARTIFACT_ROOT": str(root / "artifacts")},
            ):
                with self.assertRaisesRegex(server.RpcError, "escapes"):
                    server._materialize_inputs(
                        [
                            {
                                "uri": "aes://artifacts/meshes/../secret",
                                "target": "mesh.msh",
                            }
                        ],
                        run_dir,
                    )


if __name__ == "__main__":
    unittest.main()
