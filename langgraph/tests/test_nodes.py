import sys
import types
import unittest
from unittest.mock import patch


sys.modules.setdefault("requests", types.ModuleType("requests"))

from aes_agent import nodes


class ValidationNodeTests(unittest.TestCase):
    @patch.object(
        nodes,
        "ollama_json",
        return_value={
            "validation_status": "valid",
            "validation_errors": ["This must be discarded."],
        },
    )
    def test_valid_result_clears_validation_errors(self, _ollama_json):
        result = nodes.validate_formulation(
            {"selected_formulation": "weak_formulation_candidate"}
        )

        self.assertEqual(result["validation_status"], "valid")
        self.assertEqual(result["validation_errors"], [])

    @patch.object(nodes, "ollama_json", return_value={})
    def test_malformed_result_fails_closed(self, _ollama_json):
        result = nodes.validate_formulation(
            {"selected_formulation": "weak_formulation_candidate"}
        )

        self.assertEqual(result["validation_status"], "invalid")
        self.assertTrue(result["validation_errors"])

    @patch.object(nodes, "ollama_json", return_value={})
    def test_supported_forward_formulation_validates_deterministically(
        self,
        _ollama_json,
    ):
        result = nodes.validate_formulation(
            {
                "raw_user_input": (
                    "Solve a steady heat equation on a unit square with "
                    "u=0 on the boundary and source f=1."
                ),
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(result["validation_status"], "valid")
        self.assertEqual(result["validation_errors"], [])


class ClarificationNodeTests(unittest.TestCase):
    @patch.object(nodes, "ollama_json", return_value={})
    def test_empty_model_result_uses_issue_fallback(self, _ollama_json):
        result = nodes.generate_clarification(
            {"missing_information": ["Boundary conditions are missing."]}
        )

        self.assertEqual(result["agent_status"], "needs_clarification")
        self.assertEqual(result["next_action"], "request_clarification")
        self.assertEqual(
            result["clarification_questions"],
            ["Please clarify: Boundary conditions are missing."],
        )

    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("clarification with known issues must not call Ollama"),
    )
    def test_known_issues_use_deterministic_clarification(self, _ollama_json):
        result = nodes.generate_clarification(
            {"validation_errors": ["The selected formulation is inconsistent."]}
        )

        self.assertEqual(result["agent_status"], "needs_clarification")
        self.assertEqual(
            result["clarification_questions"],
            ["Please clarify: The selected formulation is inconsistent."],
        )


class ToolNodeTests(unittest.TestCase):
    @patch.object(
        nodes,
        "ollama_json",
        return_value={
            "selected_tools": [
                "problem_spec_exporter",
                "unknown_tool",
                "problem_spec_exporter",
            ]
        },
    )
    def test_tool_selection_keeps_only_registered_unique_tools(
        self,
        _ollama_json,
    ):
        result = nodes.select_tools({"selected_formulation": "weak_form"})

        self.assertEqual(
            result["selected_tools"],
            ["problem_spec_exporter"],
        )

    @patch.object(nodes, "ollama_json", return_value={"selected_tools": []})
    def test_empty_tool_selection_falls_back_to_available_tools(
        self,
        _ollama_json,
    ):
        result = nodes.select_tools({"selected_formulation": "weak_form"})

        self.assertEqual(result["selected_tools"], nodes.list_available_tools())

    @patch.object(nodes, "ollama_json", return_value={"selected_tools": []})
    def test_ready_recipe_adds_fenics_tool(
        self,
        _ollama_json,
    ):
        result = nodes.select_tools(
            {
                "selected_formulation": "weak_form",
                "numerical_recipe_status": "ready",
            }
        )

        self.assertIn("fenics_forward_solve", result["selected_tools"])

    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("ready recipe must not call Ollama for tool selection"),
    )
    def test_ready_recipe_selects_fenics_without_llm(
        self,
        _ollama_json,
    ):
        result = nodes.select_tools(
            {
                "selected_formulation": "fem_problem_setup",
                "numerical_recipe_status": "ready",
            }
        )

        self.assertEqual(result["selected_tools"], ["fenics_forward_solve"])

    def test_tool_execution_reports_completed_results(self):
        result = nodes.execute_tools(
            {
                "selected_tools": [
                    "problem_spec_exporter",
                    "workflow_plan_builder",
                ],
                "selected_formulation": "weak_formulation_candidate",
            }
        )

        self.assertEqual(result["tool_execution_status"], "completed")
        self.assertEqual(len(result["tool_results"]), 2)
        self.assertEqual(result["tool_errors"], [])

    def test_tool_execution_reports_unknown_tool_failure(self):
        result = nodes.execute_tools({"selected_tools": ["unknown_tool"]})

        self.assertEqual(result["tool_execution_status"], "failed")
        self.assertTrue(result["tool_errors"])


class ArtifactNodeTests(unittest.TestCase):
    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("final artifact must not call the LLM"),
    )
    def test_final_artifact_is_deterministic_and_bounded(self, _ollama_json):
        result = nodes.generate_artifact(
            {
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "unknown_initial_condition",
                "time_info": "unknown_time",
                "selected_formulation": "fem_problem_setup",
                "validation_status": "valid",
                "numerical_recipe_status": "ready",
                "numerical_recipe": {
                    "provider": "mcp:dolfinx",
                    "workflow": "poisson_unit_domain_v1",
                    "problem_type": "poisson_equation",
                    "domain": {
                        "type": "unit_square",
                        "nx": 32,
                        "ny": 32,
                    },
                    "equation": {
                        "diffusion_coefficient": "1.0",
                        "source": "1",
                    },
                    "solver": {
                        "type": "linear",
                        "solver_type": "cg",
                    },
                },
                "selected_tools": ["fenics_forward_solve"],
                "tool_execution_status": "completed",
                "tool_results": [
                    {
                        "tool_name": "fenics_forward_solve",
                        "provider": "mcp:dolfinx",
                        "status": "completed",
                        "output": {
                            "execution_mode": "planned",
                            "mcp_endpoint": "http://dolfinx-mcp:8000/mcp",
                            "executed_call_count": 3,
                            "non_empty_result_count": 3,
                            "mcp_calls": [
                                {"tool_name": "reset_session"},
                                {"tool_name": "create_unit_square"},
                                {"tool_name": "solve"},
                            ],
                        },
                        "error": "",
                    }
                ],
            }
        )

        artifact = result["generated_artifact"]
        self.assertEqual(result["agent_status"], "ok")
        self.assertIn("stationary_diffusion_equation", artifact)
        self.assertIn("fenics_forward_solve", artifact)
        self.assertIn("Execution mode: planned", artifact)
        self.assertIn("MCP endpoint: http://dolfinx-mcp:8000/mcp", artifact)
        self.assertIn("Executed MCP calls: 3", artifact)
        self.assertIn("Non-empty MCP results: 3", artifact)
        self.assertNotIn("topic_topic", artifact)
        self.assertLess(len(artifact), 3000)


class ExtractionFallbackTests(unittest.TestCase):
    STATIONARY_HEAT_REQUEST = (
        "Solve the stationary heat equation on the unit square Omega=[0,1]^2. "
        "Use homogeneous Dirichlet boundary conditions u=0 on the boundary. "
        "Use source f=1 and diffusion coefficient alpha=1. "
        "Use the strong form -alpha * Delta(u) = f. "
        "Use the weak FEM form: find u in H_0^1(Omega) such that "
        "integral_Omega alpha * grad(u) dot grad(v) dx = integral_Omega f * v dx "
        "for all test functions v in H_0^1(Omega)."
    )

    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("supported PDE path must not call Ollama"),
    )
    def test_supported_stationary_heat_uses_deterministic_path(self, _ollama_json):
        state = {
            "raw_user_input": self.STATIONARY_HEAT_REQUEST,
        }

        state.update(nodes.classify_problem(state))
        state.update(nodes.extract_mathematical_structure(state))
        state.update(nodes.check_problem_completeness(state))
        state.update(nodes.select_formulation(state))
        state.update(nodes.validate_formulation(state))

        self.assertEqual(state["problem_class"], "forward_problem")
        self.assertEqual(state["pde_info"], "stationary_diffusion_equation")
        self.assertEqual(state["domain_info"], "unit_square")
        self.assertEqual(state["source_info"], "1")
        self.assertEqual(state["coefficient_info"], "1")
        self.assertEqual(state["bc_info"], "dirichlet_boundary_condition")
        self.assertEqual(state["missing_information"], [])
        self.assertEqual(state["selected_formulation"], "fem_problem_setup")
        self.assertEqual(state["validation_status"], "valid")

    @patch.object(
        nodes,
        "ollama_json",
        return_value={
            "problem_class": "unknown_problem",
            "pde_info": "unknown_pde",
        },
    )
    def test_steady_heat_classifies_as_stationary_forward_problem(
        self,
        _ollama_json,
    ):
        result = nodes.classify_problem(
            {
                "raw_user_input": (
                    "Solve a steady heat equation on a unit square with "
                    "u=0 on the boundary and source f=1."
                )
            }
        )

        self.assertEqual(result["problem_class"], "forward_problem")
        self.assertEqual(result["pde_info"], "stationary_diffusion_equation")

    @patch.object(nodes, "ollama_json", return_value={})
    def test_structure_fallback_extracts_unit_square_source_and_bc(
        self,
        _ollama_json,
    ):
        result = nodes.extract_mathematical_structure(
            {
                "raw_user_input": (
                    "Solve a steady heat equation on a unit square with "
                    "u=0 on the boundary and source f=1."
                ),
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
            }
        )

        self.assertEqual(result["domain_info"], "unit_square")
        self.assertEqual(result["source_info"], "1")
        self.assertEqual(result["bc_info"], "dirichlet_boundary_condition")

    @patch.object(nodes, "ollama_json", return_value={})
    def test_structure_fallback_splits_source_from_coefficient_sentence(
        self,
        _ollama_json,
    ):
        result = nodes.extract_mathematical_structure(
            {
                "raw_user_input": (
                    "Solve the stationary heat equation on the unit square "
                    "Omega=[0,1]^2. Use homogeneous Dirichlet boundary "
                    "conditions u=0 on the boundary. Use source f=1 and "
                    "diffusion coefficient alpha=1."
                ),
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
            }
        )

        self.assertEqual(result["source_info"], "1")
        self.assertEqual(result["coefficient_info"], "1")

    @patch.object(nodes, "ollama_json", return_value={"missing_information": []})
    def test_completeness_detects_steady_transient_contradiction(
        self,
        _ollama_json,
    ):
        result = nodes.check_problem_completeness(
            {
                "raw_user_input": (
                    "Solve a steady heat equation. The formulation is "
                    "\\partial u / \\partial t = alpha * Delta u - f."
                ),
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "unknown_initial_condition",
                "time_info": "unknown_time",
            }
        )

        self.assertTrue(
            any("steady/stationary" in item for item in result["missing_information"])
        )

    @patch.object(
        nodes,
        "ollama_json",
        return_value={"selected_formulation": "unknown_formulation"},
    )
    def test_formulation_falls_back_for_supported_forward_pde(
        self,
        _ollama_json,
    ):
        result = nodes.select_formulation(
            {
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "missing_information": [],
            }
        )

        self.assertEqual(result["selected_formulation"], "fem_problem_setup")


class NumericalRecipeNodeTests(unittest.TestCase):
    def test_heat_recipe_requires_initial_condition(self):
        result = nodes.prepare_numerical_recipe(
            {
                "raw_user_input": (
                    "Solve the heat equation on the unit square with zero "
                    "Dirichlet boundary conditions."
                ),
                "problem_class": "forward_problem",
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "unit_square",
                "coefficient_info": "constant_coefficient_given",
                "source_info": "0.0",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "unknown_initial_condition",
                "time_info": "unknown_time",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(result["numerical_recipe_status"], "invalid")
        self.assertTrue(result["numerical_recipe_errors"])

    def test_heat_recipe_is_ready_for_supported_problem(self):
        result = nodes.prepare_numerical_recipe(
            {
                "raw_user_input": (
                    "Solve the heat equation on the unit square with zero "
                    "Dirichlet boundary conditions. Initial condition is "
                    "sin(pi*x[0])*sin(pi*x[1]), T=1, dt=0.01."
                ),
                "problem_class": "forward_problem",
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "0.0",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "sin(pi*x[0])*sin(pi*x[1])",
                "time_info": "T=1, dt=0.01",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(result["numerical_recipe_status"], "ready")
        self.assertEqual(
            result["numerical_recipe"]["problem_type"],
            "heat_equation",
        )


if __name__ == "__main__":
    unittest.main()
