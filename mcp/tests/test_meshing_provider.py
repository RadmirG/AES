from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
