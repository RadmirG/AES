from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_PATH = Path(__file__).resolve().parents[1] / "providers" / "meshing" / "server.py"
SPEC = importlib.util.spec_from_file_location("aes_meshing_provider", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)


class MeshingProviderContractTests(unittest.TestCase):
    def test_tool_discovery_lists_four_governed_tools(self):
        result = server._handle_request("tools/list", {})
        tools = {tool["name"]: tool for tool in result["tools"]}
        self.assertEqual(
            set(tools),
            {"inspect_geometry", "generate_mesh", "validate_mesh", "convert_mesh"},
        )
        validate_properties = tools["validate_mesh"]["inputSchema"]["properties"]
        self.assertIn("geometry_spec", validate_properties)
        self.assertIn("dimension", validate_properties)

    def test_surface_scan_is_an_explicit_placeholder(self):
        result = server._surface_placeholder(
            {"kind": "surface_scan", "format": "stl", "artifact_path": "uploads/a.stl"}
        )
        self.assertEqual(result["status"], "unsupported_not_implemented")
        self.assertIn("not implemented", result["message"].lower())

    def test_native_meshing_failure_returns_structured_tool_result(self):
        geometry = _rectangle_geometry()
        with tempfile.TemporaryDirectory() as workspace:
            with patch.dict(os.environ, {"MESHING_WORKSPACE": workspace}):
                with patch.object(
                    server,
                    "_generate_with_gmsh",
                    side_effect=RuntimeError(
                        "Gmsh could not be loaded: libGL.so.1 is missing"
                    ),
                ):
                    result = server._generate_mesh(geometry)

        self.assertEqual(result["status"], "failed")
        self.assertIn("libGL.so.1", result["errors"][0])
        self.assertIn("run_id", result)

    def test_gmsh_session_disables_signal_handlers_and_finalizes(self):
        class FakeGmsh:
            def __init__(self):
                self.initialized = False
                self.interruptible = None
                self.finalized = False

            def initialize(self, *, interruptible):
                self.initialized = True
                self.interruptible = interruptible

            def isInitialized(self):
                return self.initialized

            def finalize(self):
                self.initialized = False
                self.finalized = True

        fake = FakeGmsh()
        with patch.object(server, "_import_gmsh", return_value=fake):
            with server._gmsh_session() as session:
                self.assertIs(session, fake)
                self.assertTrue(fake.initialized)
                self.assertFalse(fake.interruptible)

        self.assertTrue(fake.finalized)


def _rectangle_geometry():
    return {
        "schema_version": "1.0",
        "dimension": 2,
        "units": "m",
        "source": {
            "kind": "primitives",
            "primitives": [
                {
                    "id": "domain",
                    "shape": "rectangle",
                    "origin": [0.0, 0.0],
                    "size": [1.0, 1.0],
                    "center": None,
                    "radius": None,
                    "axis": None,
                    "height": None,
                }
            ],
        },
        "regions": [
            {
                "name": "domain",
                "dimension": 2,
                "selector": {
                    "kind": "object",
                    "reference": "domain",
                    "bounds": None,
                    "entity_tags": [],
                },
            },
            {
                "name": "boundary",
                "dimension": 1,
                "selector": {
                    "kind": "all_boundary",
                    "reference": "domain",
                    "bounds": None,
                    "entity_tags": [],
                },
            },
        ],
        "mesh": {
            "cell_type": "triangle",
            "order": 1,
            "global_size": 0.1,
            "refinements": [],
            "quality": {
                "minimum_scaled_jacobian": 0.0,
                "maximum_elements": 10000,
            },
        },
        "metadata": {},
    }


if __name__ == "__main__":
    unittest.main()
