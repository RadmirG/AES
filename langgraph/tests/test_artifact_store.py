import os
import unittest
from unittest.mock import patch

from aes_agent.artifact_store import build_artifact_manifest, persist_artifacts


class ArtifactStoreTests(unittest.TestCase):
    def test_build_manifest_uses_fenics_artifact_references(self):
        manifest = build_artifact_manifest(_state_with_fenics_result())

        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(manifest["artifacts"]), 1)
        self.assertEqual(manifest["artifacts"][0]["name"], "heat_solution.png")
        self.assertEqual(manifest["artifacts"][0]["status"], "referenced")

    def test_failed_manifest_does_not_promote_requested_artifacts(self):
        manifest = build_artifact_manifest(_state_with_failed_fenics_result())

        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["artifacts"], [])
        self.assertTrue(manifest["errors"])

    def test_persist_artifacts_writes_manifest_and_summary(self):
        with patch.dict(
            os.environ,
            {
                "AES_ARTIFACT_ROOT": "test-artifacts",
                "AES_ARTIFACT_RUN_ID": "test-run",
            },
        ):
            with patch("aes_agent.artifact_store._ensure_directory") as mkdir:
                with patch("aes_agent.artifact_store._write_text") as write_text:
                    output = persist_artifacts(_state_with_fenics_result())

            self.assertEqual(output["execution_mode"], "stored")
            self.assertEqual(output["errors"], [])
            self.assertIn("test-run", output["manifest_path"])
            self.assertIn("test-run", output["summary_path"])
            mkdir.assert_called_once()
            self.assertEqual(write_text.call_count, 2)

    def test_persist_artifacts_materializes_generated_code_file(self):
        with patch.dict(
            os.environ,
            {
                "AES_ARTIFACT_ROOT": "test-artifacts",
                "AES_ARTIFACT_RUN_ID": "code-run",
            },
        ):
            with patch("aes_agent.artifact_store._ensure_directory"):
                with patch("aes_agent.artifact_store._write_text") as write_text:
                    output = persist_artifacts(_state_with_generated_code_result())

        self.assertEqual(output["execution_mode"], "stored")
        self.assertEqual(write_text.call_count, 3)
        written_paths = [str(call.args[0]) for call in write_text.call_args_list]
        self.assertTrue(any(path.endswith("solve.py") for path in written_paths))


def _state_with_fenics_result():
    return {
        "raw_user_input": "Solve heat equation on the unit square.",
        "problem_class": "forward_problem",
        "pde_info": "time_dependent_heat_equation",
        "domain_info": "unit_square",
        "source_info": "1",
        "bc_info": "dirichlet_boundary_condition",
        "time_info": "T=1, dt=0.01",
        "tool_results": [
            {
                "tool_name": "fenics_forward_solve",
                "provider": "mcp:dolfinx",
                "status": "completed",
                "output": {
                    "fenics_result": {
                        "schema_version": "1.0",
                        "provider": "mcp:dolfinx",
                        "status": "completed",
                        "execution_mode": "executed",
                        "workflow": "heat_equation_unit_domain_backward_euler_v1",
                        "problem_type": "heat_equation",
                        "artifacts": [
                            {
                                "name": "heat_solution.png",
                                "kind": "plot",
                                "status": "available",
                                "uri": "mcp://dolfinx/workspace/heat_solution.png",
                                "storage": "provider_workspace",
                                "media_type": "image/png",
                                "producer": {
                                    "provider": "mcp:dolfinx",
                                    "tool_name": "plot_solution",
                                },
                                "metadata": {},
                            }
                        ],
                        "requested_artifacts": [],
                        "errors": [],
                        "warnings": [],
                    }
                },
                "error": "",
            }
        ],
    }


def _state_with_failed_fenics_result():
    return {
        "raw_user_input": "Solve heat equation on the unit square.",
        "problem_class": "forward_problem",
        "pde_info": "time_dependent_heat_equation",
        "domain_info": "unit_square",
        "source_info": "1",
        "bc_info": "dirichlet_boundary_condition",
        "time_info": "T=1, dt=0.01",
        "tool_results": [
            {
                "tool_name": "fenics_forward_solve",
                "provider": "mcp:dolfinx",
                "status": "failed",
                "output": {
                    "fenics_result": {
                        "schema_version": "1.0",
                        "provider": "mcp:dolfinx",
                        "status": "failed",
                        "execution_mode": "failed",
                        "workflow": "heat_equation_unit_domain_backward_euler_v1",
                        "problem_type": "heat_equation",
                        "artifacts": [],
                        "requested_artifacts": [
                            {
                                "name": "heat_solution.png",
                                "kind": "plot",
                                "status": "requested",
                                "uri": "mcp://dolfinx/workspace/heat_solution.png",
                                "storage": "provider_workspace",
                                "media_type": "image/png",
                                "producer": {
                                    "provider": "mcp:dolfinx",
                                    "tool_name": "plot_solution",
                                },
                                "metadata": {},
                            }
                        ],
                        "errors": ["set_material_properties failed"],
                        "warnings": [],
                    }
                },
                "error": "set_material_properties failed",
            }
        ],
    }


def _state_with_generated_code_result():
    return {
        "raw_user_input": "Give me a FEniCS executable Python file.",
        "problem_class": "forward_problem",
        "pde_info": "stationary_diffusion_equation",
        "domain_info": "unit_square",
        "source_info": "1",
        "bc_info": "dirichlet_boundary_condition",
        "tool_results": [
            {
                "tool_name": "fenics_code_solve",
                "provider": "local:fenics_code",
                "status": "completed",
                "output": {
                    "generated_files": [
                        {
                            "name": "solve.py",
                            "kind": "source_code",
                            "media_type": "text/x-python",
                            "content": "print('ok')\n",
                        }
                    ],
                    "fenics_result": {
                        "schema_version": "1.0",
                        "provider": "local:fenics_code",
                        "status": "generated",
                        "execution_mode": "generated",
                        "workflow": "llm_generated_dolfinx_script_v1",
                        "problem_type": "stationary_diffusion_equation",
                        "artifacts": [
                            {
                                "name": "solve.py",
                                "kind": "source_code",
                                "status": "available",
                                "uri": "inline://fenics-code/solve.py",
                                "storage": "inline",
                                "media_type": "text/x-python",
                                "producer": {
                                    "provider": "local:fenics_code",
                                    "tool_name": "fenics_code_solve",
                                },
                                "metadata": {},
                            }
                        ],
                        "requested_artifacts": [],
                        "errors": [],
                        "warnings": [],
                    },
                },
                "error": "",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
