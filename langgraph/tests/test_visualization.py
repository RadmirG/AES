import json
import unittest

from aes_agent.visualization import (
    aes_artifact_uri_to_public_url,
    build_visualization_artifacts,
)


class VisualizationPostprocessTests(unittest.TestCase):
    def test_visualization_artifacts_are_generated_from_fenics_result(self):
        output = build_visualization_artifacts(_state_with_completed_fenics_code())

        self.assertEqual(output["execution_mode"], "generated")
        self.assertEqual(
            output["generated_file_names"],
            ["viewer_manifest.json", "preview.svg", "viewer.html"],
        )

        generated = {
            item["name"]: item["content"]
            for item in output["generated_files"]
        }
        manifest = json.loads(generated["viewer_manifest.json"])

        self.assertEqual(manifest["source_tool"], "fenics_code_solve")
        self.assertEqual(
            manifest["diagnostics"]["script"]["problem"],
            "transient_heat_equation",
        )
        self.assertIn("solution.xdmf", generated["viewer.html"])
        self.assertIn("Numerical solution field u(x,y,t)", generated["preview.svg"])
        self.assertIn("sampled_field", manifest["datasets"])
        self.assertTrue(manifest["capabilities"]["sampled_field_preview"])

    def test_stationary_sampled_field_preview_uses_spatial_label(self):
        output = build_visualization_artifacts(_state_with_completed_stationary_fenics_code())
        generated = {
            item["name"]: item["content"]
            for item in output["generated_files"]
        }
        manifest = json.loads(generated["viewer_manifest.json"])

        self.assertEqual(output["execution_mode"], "generated")
        self.assertIn("Numerical solution field u(x,y)", generated["preview.svg"])
        self.assertNotIn("Numerical solution field u(x,y,t)", generated["preview.svg"])
        self.assertIn("stationary solution", generated["preview.svg"])
        self.assertIn("sampled_field", manifest["datasets"])
        self.assertEqual(manifest["datasets"]["sampled_field"]["type"], "dof_point_cloud")
        self.assertTrue(manifest["capabilities"]["sampled_field_preview"])

    def test_visualization_artifacts_skip_without_completed_solver_result(self):
        output = build_visualization_artifacts({"tool_results": []})

        self.assertEqual(output["execution_mode"], "skipped")
        self.assertEqual(output["generated_files"], [])
        self.assertEqual(output["errors"], [])

    def test_aes_artifact_uri_converts_to_relative_public_url(self):
        self.assertEqual(
            aes_artifact_uri_to_public_url(
                "aes://artifacts/20260713T122829Z-test/preview.svg"
            ),
            "/artifacts/20260713T122829Z-test/preview.svg",
        )


def _state_with_completed_fenics_code():
    return {
        "problem_class": "forward_problem",
        "pde_info": "time_dependent_heat_equation",
        "domain_info": "unit_square",
        "source_info": "1",
        "bc_info": "dirichlet_boundary_condition",
        "time_info": "T=1, dt=0.01",
        "tool_results": [
            {
                "tool_name": "fenics_code_solve",
                "provider": "local:fenics_code",
                "status": "completed",
                "output": {
                    "fenics_result": {
                        "status": "completed",
                        "diagnostics": {
                            "return_code": 0,
                            "run_id": "provider-run",
                            "elapsed_seconds": 1.25,
                            "script": {
                                "problem": "transient_heat_equation",
                                "num_dofs": 1089,
                                "num_steps": 100,
                                "dt": 0.01,
                                "final_time": 1.0,
                                "solution_min": 0.0,
                                "solution_max": 0.12,
                                "solution_mean": 0.04,
                                "time_series": [
                                    {"time": 0.01, "max": 0.01, "mean": 0.004},
                                    {"time": 1.0, "max": 0.12, "mean": 0.04},
                                ],
                                "field_samples": {
                                    "type": "dof_point_cloud_time_series",
                                    "field": "u",
                                    "domain": "unit_square",
                                    "space": "P1",
                                    "coordinates": [
                                        [0.0, 0.0],
                                        [1.0, 0.0],
                                        [0.0, 1.0],
                                        [1.0, 1.0],
                                    ],
                                    "samples": [
                                        {
                                            "step": 0,
                                            "time": 0.0,
                                            "values": [0.0, 0.0, 0.0, 0.0],
                                        },
                                        {
                                            "step": 100,
                                            "time": 1.0,
                                            "values": [0.0, 0.1, 0.1, 0.0],
                                        },
                                    ],
                                    "value_range": {"min": 0.0, "max": 0.1},
                                },
                            },
                        },
                        "artifacts": [
                            {
                                "name": "solution.xdmf",
                                "kind": "solution",
                                "media_type": "application/x-xdmf",
                                "uri": "mcp://fenics-code-runner/workspace/code-runs/provider-run/solution.xdmf",
                                "storage": "provider_workspace",
                                "status": "available",
                            },
                            {
                                "name": "solution.vtu",
                                "kind": "solution",
                                "media_type": "application/vnd.vtk",
                                "uri": "mcp://fenics-code-runner/workspace/code-runs/provider-run/solution.vtu",
                                "storage": "provider_workspace",
                                "status": "available",
                            },
                        ],
                    },
                },
                "error": "",
            }
        ],
    }


def _state_with_completed_stationary_fenics_code():
    return {
        "problem_class": "forward_problem",
        "pde_info": "stationary_diffusion_equation",
        "domain_info": "unit_square",
        "source_info": "1",
        "bc_info": "dirichlet_boundary_condition",
        "time_info": "unknown_time",
        "tool_results": [
            {
                "tool_name": "fenics_code_solve",
                "provider": "local:fenics_code",
                "status": "completed",
                "output": {
                    "fenics_result": {
                        "status": "completed",
                        "diagnostics": {
                            "return_code": 0,
                            "run_id": "provider-run",
                            "elapsed_seconds": 0.5,
                            "script": {
                                "problem": "stationary_diffusion_equation",
                                "num_dofs": 4,
                                "solution_min": 0.0,
                                "solution_max": 0.12,
                                "solution_mean": 0.03,
                                "field_samples": {
                                    "type": "dof_point_cloud",
                                    "field": "u",
                                    "domain": "unit_square",
                                    "space": "P1",
                                    "coordinates": [
                                        [0.0, 0.0],
                                        [1.0, 0.0],
                                        [0.0, 1.0],
                                        [1.0, 1.0],
                                    ],
                                    "samples": [
                                        {
                                            "step": 0,
                                            "time": 0.0,
                                            "values": [0.0, 0.12, 0.12, 0.0],
                                        },
                                    ],
                                    "value_range": {"min": 0.0, "max": 0.12},
                                },
                            },
                        },
                        "artifacts": [
                            {
                                "name": "solution.xdmf",
                                "kind": "solution",
                                "media_type": "application/x-xdmf",
                                "uri": "mcp://fenics-code-runner/workspace/code-runs/provider-run/solution.xdmf",
                                "storage": "provider_workspace",
                                "status": "available",
                            },
                        ],
                    },
                },
                "error": "",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
