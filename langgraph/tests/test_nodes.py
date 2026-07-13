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


class RequestIntentNodeTests(unittest.TestCase):
    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("obvious command must not call the LLM"),
    )
    def test_docker_command_is_operational_intent(self, _ollama_json):
        result = nodes.detect_request_intent(
            {
                "raw_user_input": (
                    "docker compose -f deploy/compose.prod.yaml "
                    "--profile models --profile fenics up -d --build "
                    "--force-recreate langgraph"
                )
            }
        )

        self.assertEqual(result["request_intent"], "operational_command")
        self.assertIn("command", result["intent_reason"])

    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("obvious PDE request must not call the LLM"),
    )
    def test_heat_equation_is_engineering_intent(self, _ollama_json):
        result = nodes.detect_request_intent(
            {
                "raw_user_input": (
                    "Solve the transient heat equation on the unit square with "
                    "u=0 on the boundary, f=1, T=1, and dt=0.01."
                )
            }
        )

        self.assertEqual(result["request_intent"], "engineering_pde_request")

    def test_non_engineering_response_does_not_select_tools(self):
        result = nodes.handle_non_engineering_request(
            {
                "raw_user_input": "docker compose up -d",
                "request_intent": "operational_command",
                "intent_reason": "The message is a Docker command.",
            }
        )

        self.assertEqual(result["agent_status"], "not_applicable")
        self.assertIn("not a numerical engineering problem", result["generated_artifact"])


class ToolNodeTests(unittest.TestCase):
    def test_solution_mode_asks_for_output_for_pde_text_only(self):
        result = nodes.select_solution_mode(
            {
                "raw_user_input": (
                    "Consider the stationary heat equation -div(a grad u)=f "
                    "on a 2D rectangle in R^2 with Dirichlet boundary conditions."
                )
            }
        )

        self.assertEqual(result["solution_mode"], "needs_output_intent")

    def test_solution_mode_prefers_generated_code_for_python_file_request(self):
        result = nodes.select_solution_mode(
            {
                "raw_user_input": (
                    "Solve the transient heat equation. As a solution I need "
                    "a FEniCS executable python file."
                )
            }
        )

        self.assertEqual(result["solution_mode"], "generate_fenics_code")

    def test_solution_mode_selects_execution_for_result_request(self):
        result = nodes.select_solution_mode(
            {
                "raw_user_input": (
                    "Solve the heat equation and execute it to generate result "
                    "files and a plot."
                )
            }
        )

        self.assertEqual(result["solution_mode"], "execute_generated_fenics_code")

    def test_solution_mode_detects_user_provided_python_code(self):
        result = nodes.select_solution_mode(
            {
                "raw_user_input": (
                    "```python\n"
                    "from dolfinx import fem\n"
                    "import ufl\n"
                    "print('candidate solve')\n"
                    "```"
                )
            }
        )

        self.assertEqual(result["solution_mode"], "execute_user_fenics_code")

    def test_output_intent_clarification_question_is_deterministic(self):
        result = nodes.generate_clarification(
            {
                "solution_mode": "needs_output_intent",
            }
        )

        self.assertEqual(result["agent_status"], "needs_clarification")
        self.assertEqual(result["next_action"], "select_requested_output")
        self.assertIn("formulation summary", result["generated_artifact"])

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

        self.assertEqual(
            result["selected_tools"],
            [
                "fenics_forward_solve",
                "visualization_postprocess",
                "artifact_store",
            ],
        )

    @patch(
        "aes_agent.nodes.ollama_json",
        side_effect=AssertionError("ready generated-code recipe must not call Ollama for tool selection"),
    )
    def test_ready_code_recipe_selects_fenics_code_tool(self, _ollama_json):
        result = nodes.select_tools(
            {
                "solution_mode": "generate_fenics_code",
                "selected_formulation": "fem_problem_setup",
                "numerical_recipe_status": "ready",
                "numerical_recipe": {
                    "provider": "local:fenics_code",
                },
            }
        )

        self.assertEqual(
            result["selected_tools"],
            ["fenics_code_solve", "visualization_postprocess", "artifact_store"],
        )

    def test_terminal_paths_select_only_artifact_store(self):
        result = nodes.select_artifact_store({"agent_status": "needs_clarification"})

        self.assertEqual(result["selected_tools"], ["artifact_store"])

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

    def test_artifact_values_escape_markdown_asterisks(self):
        self.assertEqual(
            nodes._artifact_value("sin(pi*x)*sin(pi*y)"),
            "sin(pi\\*x)\\*sin(pi\\*y)",
        )

    def test_final_artifact_includes_fenics_code_execution_review(self):
        result = nodes.generate_artifact(
            {
                "problem_class": "forward_problem",
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "sin(pi*x)*sin(pi*y)",
                "time_info": "T=1, dt=0.01",
                "selected_formulation": "fem_problem_setup",
                "solution_mode": "execute_generated_fenics_code",
                "validation_status": "valid",
                "numerical_recipe_status": "ready",
                "numerical_recipe": {
                    "provider": "local:fenics_code",
                    "workflow": "llm_generated_dolfinx_script_v1",
                    "problem_type": "time_dependent_heat_equation",
                },
                "selected_tools": ["fenics_code_solve", "artifact_store"],
                "tool_execution_status": "completed",
                "tool_results": [
                    {
                        "tool_name": "fenics_code_solve",
                        "provider": "local:fenics_code",
                        "status": "completed",
                        "output": {
                            "execution_mode": "executed",
                            "generated_file_names": ["solve.py", "diagnostics.json"],
                            "safety_status": "safe",
                            "code_summary": "Generated fallback code.",
                            "execution": {
                                "result": {
                                    "stdout": "{}",
                                    "diagnostics": {
                                        "return_code": 0,
                                        "run_id": "provider-run",
                                        "elapsed_seconds": 1.25,
                                        "timeout_seconds": 300,
                                        "artifact_count": 3,
                                        "script": {
                                            "problem": "transient_heat_equation",
                                            "num_steps": 100,
                                            "dt": 0.01,
                                            "final_time": 1.0,
                                            "num_dofs": 1089,
                                            "solution_min": 0.0,
                                            "solution_max": 0.12,
                                            "solution_mean": 0.04,
                                            "time_series": [
                                                {"time": 0.01, "max": 0.01, "mean": 0.004},
                                                {"time": 1.0, "max": 0.12, "mean": 0.04},
                                            ],
                                        },
                                    },
                                }
                            },
                            "fenics_result": {
                                "status": "completed",
                                "diagnostics": {
                                    "return_code": 0,
                                    "run_id": "provider-run",
                                    "elapsed_seconds": 1.25,
                                    "timeout_seconds": 300,
                                    "artifact_count": 3,
                                    "script": {
                                        "problem": "transient_heat_equation",
                                        "num_steps": 100,
                                        "dt": 0.01,
                                        "final_time": 1.0,
                                        "num_dofs": 1089,
                                        "solution_min": 0.0,
                                        "solution_max": 0.12,
                                        "solution_mean": 0.04,
                                        "time_series": [
                                            {"time": 0.01, "max": 0.01, "mean": 0.004},
                                            {"time": 1.0, "max": 0.12, "mean": 0.04},
                                        ],
                                    },
                                },
                                "artifacts": [
                                    {
                                        "name": "solution.xdmf",
                                        "kind": "solution",
                                        "storage": "provider_workspace",
                                        "uri": "mcp://fenics-code-runner/workspace/code-runs/provider-run/solution.xdmf",
                                    }
                                ],
                            },
                        },
                        "error": "",
                    }
                ],
                "tool_errors": [],
            }
        )

        artifact = result["generated_artifact"]
        self.assertIn("Result review", artifact)
        self.assertIn("Runtime: 1.25 s", artifact)
        self.assertIn("DOFs=1089", artifact)
        self.assertIn("Final solution stats", artifact)
        self.assertIn("Time samples", artifact)
        self.assertIn("solution.xdmf", artifact)

    def test_final_artifact_includes_primary_result_links(self):
        result = nodes.generate_artifact(
            {
                "problem_class": "forward_problem",
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "unit_square",
                "selected_formulation": "fem_problem_setup",
                "solution_mode": "execute_generated_fenics_code",
                "validation_status": "valid",
                "numerical_recipe_status": "ready",
                "selected_tools": ["artifact_store"],
                "tool_execution_status": "completed",
                "tool_results": [
                    {
                        "tool_name": "artifact_store",
                        "provider": "local:artifact_store",
                        "status": "completed",
                        "output": {
                            "execution_mode": "stored",
                            "manifest": {
                                "run_id": "run-1",
                                "status": "completed",
                                "artifacts": [
                                    {
                                        "name": "viewer.html",
                                        "kind": "interactive_viewer",
                                        "storage": "aes_artifact_store",
                                        "uri": "aes://artifacts/run-1/viewer.html",
                                    },
                                    {
                                        "name": "preview.svg",
                                        "kind": "preview",
                                        "storage": "aes_artifact_store",
                                        "uri": "aes://artifacts/run-1/preview.svg",
                                    },
                                ],
                            },
                        },
                        "error": "",
                    }
                ],
                "tool_errors": [],
            }
        )

        artifact = result["generated_artifact"]
        self.assertIn("Result links:", artifact)
        self.assertIn("[Open interactive result viewer](/artifacts/run-1/viewer.html)", artifact)
        self.assertIn("[Open static preview](/artifacts/run-1/preview.svg)", artifact)


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

    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("execution follow-up must classify deterministically"),
    )
    def test_reconstructed_execution_followup_classifies_as_forward_problem(
        self,
        _ollama_json,
    ):
        result = nodes.classify_problem(
            {
                "raw_user_input": (
                    "Consider the stationary heat equation -div(a grad u)=f "
                    "on a 2D rectangle in R^2 with Dirichlet boundary conditions. "
                    "The source is f = 1. "
                    "Requested AES output: execute the generated DOLFINx/FEniCS "
                    "solve and store result artifacts."
                )
            }
        )

        self.assertEqual(result["problem_class"], "forward_problem")
        self.assertEqual(result["pde_info"], "stationary_diffusion_equation")

    @patch.object(
        nodes,
        "ollama_json",
        side_effect=AssertionError("complete PDE-only request must not call Ollama"),
    )
    def test_consider_stationary_rectangle_request_reaches_output_question(
        self,
        _ollama_json,
    ):
        state = {
            "raw_user_input": (
                "Consider the stationary heat equation -div(a grad u)=f on a "
                "2D rectangle in R^2 with follow dims [0, 1]x[0, 1], "
                "Dirichlet boundary conditions u=g on the boundary. "
                "The specific coefficient is a = 1. "
                "Cube has dims of 1 in all directions. "
                "The source is f = 1. "
                "g = 1 constant on each bound."
            )
        }

        state.update(nodes.classify_problem(state))
        state.update(nodes.extract_mathematical_structure(state))
        state.update(nodes.check_problem_completeness(state))
        state.update(nodes.select_formulation(state))
        state.update(nodes.validate_formulation(state))
        state.update(nodes.select_solution_mode(state))

        self.assertEqual(state["problem_class"], "forward_problem")
        self.assertEqual(state["pde_info"], "stationary_diffusion_equation")
        self.assertEqual(state["domain_info"], "rectangular_domain")
        self.assertEqual(state["coefficient_info"], "1")
        self.assertEqual(state["source_info"], "1")
        self.assertEqual(state["bc_info"], "dirichlet_boundary_condition")
        self.assertEqual(state["missing_information"], [])
        self.assertEqual(state["validation_status"], "valid")
        self.assertEqual(state["solution_mode"], "needs_output_intent")

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

    @patch.object(nodes, "ollama_json", return_value={})
    def test_transient_heat_extracts_separate_alpha_source_and_initial_condition(
        self,
        _ollama_json,
    ):
        result = nodes.extract_mathematical_structure(
            {
                "raw_user_input": (
                    "Solve the transient heat equation on the unit square "
                    "Omega=[0,1]^2. Use du/dt = alpha * Delta(u) + f "
                    "with alpha=1 and f=1. Use u=0 on the boundary. "
                    "Use initial condition u(x,y,0)=sin(pi*x)sin(piy). "
                    "Use final time T=1 and time step dt=0.01."
                ),
                "problem_class": "forward_problem",
                "pde_info": "time_dependent_heat_equation",
            }
        )

        self.assertEqual(result["domain_info"], "unit_square")
        self.assertEqual(result["coefficient_info"], "1")
        self.assertEqual(result["source_info"], "1")
        self.assertEqual(result["bc_info"], "dirichlet_boundary_condition")
        self.assertEqual(
            result["initial_condition_info"],
            "sin(pi*x)*sin(pi*y)",
        )
        self.assertEqual(result["time_info"], "T=1, dt=0.01")

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
    def test_generated_code_mode_prepares_code_recipe(self):
        result = nodes.prepare_numerical_recipe(
            {
                "raw_user_input": "Solve Poisson and give me a FEniCS Python file.",
                "solution_mode": "generate_fenics_code",
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "1.0",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(result["numerical_recipe_status"], "ready")
        self.assertEqual(result["numerical_recipe"]["provider"], "local:fenics_code")
        self.assertEqual(
            result["numerical_recipe"]["workflow"],
            "llm_generated_dolfinx_script_v1",
        )

    def test_user_code_mode_prepares_code_recipe(self):
        result = nodes.prepare_numerical_recipe(
            {
                "raw_user_input": "from dolfinx import fem\n",
                "solution_mode": "execute_user_fenics_code",
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "1.0",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(result["numerical_recipe_status"], "ready")
        self.assertEqual(
            result["numerical_recipe"]["target"]["code_origin"],
            "user",
        )

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
