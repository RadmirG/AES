from __future__ import annotations

import unittest

from aes_agent.meshing import execute_mesh_geometry, mesh_runner_inputs


class FakeMeshingClient:
    def list_tools(self):
        return [{"name": "generate_mesh"}]

    def call_tool(self, name, arguments=None):
        return {
            "status": "completed",
            "mesh_artifact": {
                "schema_version": "1.0",
                "status": "completed",
                "source_kind": "primitives",
                "dimension": 2,
                "cell_type": "triangle",
                "mesh_uri": "mcp://meshing/workspace/runs/test/mesh.msh",
                "cell_tags_uri": None,
                "facet_tags_uri": None,
                "tag_map": {"domain": 1, "boundary": 2},
                "quality": {
                    "schema_version": "1.0",
                    "status": "valid",
                    "element_count": 100,
                    "node_count": 60,
                    "minimum_quality": 0.4,
                    "maximum_quality": 1.0,
                    "metrics": {"minimum_scaled_jacobian": 0.4},
                    "errors": [],
                    "warnings": [],
                },
                "artifacts": [],
                "provenance": {"provider": "test"},
            },
            "artifacts": [],
            "errors": [],
            "warnings": [],
        }


class MeshingToolTests(unittest.TestCase):
    def test_live_meshing_returns_validated_artifact_and_runner_input(self):
        output = execute_mesh_geometry(
            {"geometry_spec": _geometry()}, client=FakeMeshingClient(), execute=True
        )

        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["mesh_artifact"]["quality"]["status"], "valid")
        inputs = mesh_runner_inputs_from_output(output)
        self.assertEqual(inputs[0]["target"], "mesh.msh")

    def test_surface_scan_returns_explicit_placeholder_error(self):
        geometry = _geometry()
        geometry["source"] = {
            "kind": "surface_scan",
            "format": "stl",
            "artifact_path": "uploads/scan.stl",
        }

        output = execute_mesh_geometry({"geometry_spec": geometry}, execute=True)

        self.assertEqual(output["status"], "unsupported_not_implemented")
        self.assertEqual(output["capability"], "surface_scan_reconstruction")


def mesh_runner_inputs_from_output(output):
    from aes_agent.specs.mesh import MeshArtifact

    return mesh_runner_inputs(MeshArtifact.model_validate(output["mesh_artifact"]))


def _geometry():
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
                    "origin": [0, 0],
                    "size": [1, 1],
                    "center": None,
                    "radius": None,
                    "axis": None,
                    "height": None,
                }
            ],
        },
        "regions": [
            {"name": "domain", "dimension": 2, "selector": {"kind": "object", "reference": "domain", "bounds": None, "entity_tags": []}},
            {"name": "boundary", "dimension": 1, "selector": {"kind": "all_boundary", "reference": "domain", "bounds": None, "entity_tags": []}},
        ],
        "mesh": {
            "cell_type": "triangle",
            "order": 1,
            "global_size": 0.1,
            "refinements": [],
            "quality": {"minimum_scaled_jacobian": 0.0, "maximum_elements": 10000},
        },
        "metadata": {},
    }


if __name__ == "__main__":
    unittest.main()
