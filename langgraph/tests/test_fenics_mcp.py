import unittest

from aes_agent.fenics_mcp import (
    ALLOWED_DOLFINX_TOOLS,
    build_fenics_recipe,
    execute_fenics_forward_solve,
    plan_dolfinx_mcp_calls,
)


class FakeMCPClient:
    def __init__(self):
        self.calls = []
        self.endpoint = "http://fake-dolfinx/mcp"

    def list_tools(self):
        return [{"name": tool_name} for tool_name in ALLOWED_DOLFINX_TOOLS]

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return {"ok": True, "tool": name}


class EmptyResultMCPClient(FakeMCPClient):
    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return {}


class ToolErrorMCPClient(FakeMCPClient):
    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if name == "apply_boundary_condition":
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "DOLFINX_API_ERROR: Either 'boundary' "
                            "(geometric) or 'boundary_tag' must be specified."
                        ),
                    }
                ],
            }
        return {"ok": True, "tool": name}


class FenicsRecipeTests(unittest.TestCase):
    def test_steady_heat_recipe_uses_stationary_diffusion_workflow(self):
        recipe_result = build_fenics_recipe(
            {
                "raw_user_input": (
                    "Solve a steady heat equation on a unit square with "
                    "u=0 on the boundary and source f=1."
                ),
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "1.0",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(recipe_result["status"], "ready")
        self.assertEqual(
            recipe_result["recipe"]["problem_type"],
            "poisson_equation",
        )
        self.assertEqual(
            recipe_result["recipe"]["workflow"],
            "poisson_unit_domain_v1",
        )

    def test_recipe_splits_source_from_coefficient_sentence(self):
        recipe_result = build_fenics_recipe(
            {
                "raw_user_input": (
                    "Solve the stationary heat equation on the unit square "
                    "Omega=[0,1]^2. Use homogeneous Dirichlet boundary "
                    "conditions u=0 on the boundary. Use source f=1 and "
                    "diffusion coefficient alpha=1."
                ),
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(recipe_result["status"], "ready")
        self.assertEqual(
            recipe_result["recipe"]["equation"]["source"],
            "1",
        )
        self.assertEqual(
            recipe_result["recipe"]["equation"]["diffusion_coefficient"],
            "1",
        )

    def test_heat_recipe_cleans_alpha_source_and_initial_condition(self):
        recipe_result = build_fenics_recipe(
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
                "domain_info": "unit_square",
                "coefficient_info": "1",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "sin(pi*x)*sin(pi*y)",
                "time_info": "T=1, dt=0.01",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(recipe_result["status"], "ready")
        recipe = recipe_result["recipe"]
        self.assertEqual(recipe["equation"]["diffusion_coefficient"], "1")
        self.assertEqual(recipe["equation"]["source"], "1")
        self.assertEqual(recipe["initial_condition"], "sin(pi*x)*sin(pi*y)")

        calls = plan_dolfinx_mcp_calls(recipe)
        material_calls = [
            call for call in calls if call["tool_name"] == "set_material_properties"
        ]
        self.assertEqual(
            [call["arguments"] for call in material_calls],
            [
                {"name": "k", "value": "1"},
                {"name": "f", "value": "1"},
            ],
        )
        create_function_call = next(
            call for call in calls if call["tool_name"] == "create_function"
        )
        self.assertEqual(
            create_function_call["arguments"]["function_space"],
            "V",
        )

    def test_poisson_recipe_builds_allowed_mcp_plan(self):
        recipe_result = build_fenics_recipe(
            {
                "raw_user_input": (
                    "Solve Poisson on the unit square with f = "
                    "2*pi*pi*sin(pi*x[0])*sin(pi*x[1]) and u=0 on boundary."
                ),
                "problem_class": "forward_problem",
                "pde_info": "poisson_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "2*pi*pi*sin(pi*x[0])*sin(pi*x[1])",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        self.assertEqual(recipe_result["status"], "ready")
        calls = plan_dolfinx_mcp_calls(recipe_result["recipe"])
        tool_names = [call["tool_name"] for call in calls]

        self.assertIn("create_unit_square", tool_names)
        self.assertIn("solve", tool_names)
        self.assertNotIn("run_custom_code", tool_names)
        self.assertTrue(set(tool_names).issubset(ALLOWED_DOLFINX_TOOLS))
        boundary_calls = [
            call for call in calls if call["tool_name"] == "apply_boundary_condition"
        ]
        self.assertEqual(boundary_calls[0]["arguments"]["boundary"], "boundary")
        self.assertEqual(boundary_calls[0]["arguments"]["locator"], "boundary")
        self.assertEqual(boundary_calls[0]["arguments"]["function_space"], "V")

    def test_live_execution_uses_fake_mcp_client(self):
        recipe_result = build_fenics_recipe(
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
        client = FakeMCPClient()

        output = execute_fenics_forward_solve(
            {
                "numerical_recipe": recipe_result["recipe"],
                "numerical_recipe_errors": [],
            },
            client=client,
            execute=True,
        )

        self.assertEqual(output["execution_mode"], "executed")
        self.assertEqual(len(output["results"]), len(client.calls))
        self.assertEqual(output["mcp_endpoint"], "http://fake-dolfinx/mcp")
        self.assertEqual(output["executed_call_count"], len(client.calls))
        self.assertEqual(output["non_empty_result_count"], len(client.calls))
        self.assertEqual(output["warnings"], [])
        self.assertEqual(output["fenics_result"]["status"], "completed")
        self.assertEqual(
            output["fenics_result"]["mcp"]["executed_call_count"],
            len(client.calls),
        )
        self.assertEqual(
            [artifact["name"] for artifact in output["fenics_result"]["artifacts"]],
            ["heat_solution.xdmf", "heat_solution.png", "heat_report.html"],
        )
        self.assertIn(
            "solve_time_dependent",
            [tool_name for tool_name, _arguments in client.calls],
        )

    def test_live_execution_reports_unverified_empty_mcp_results(self):
        recipe_result = build_fenics_recipe(
            {
                "raw_user_input": (
                    "Solve Poisson on the unit square with f = 1 and "
                    "u=0 on boundary."
                ),
                "problem_class": "forward_problem",
                "pde_info": "poisson_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "1.0",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )
        client = EmptyResultMCPClient()

        output = execute_fenics_forward_solve(
            {
                "numerical_recipe": recipe_result["recipe"],
                "numerical_recipe_errors": [],
            },
            client=client,
            execute=True,
        )

        self.assertEqual(output["execution_mode"], "executed_unverified")
        self.assertEqual(output["fenics_result"]["status"], "unverified")
        self.assertEqual(output["executed_call_count"], len(client.calls))
        self.assertEqual(output["non_empty_result_count"], 0)
        self.assertTrue(output["empty_result_tools"])
        self.assertTrue(output["warnings"])

    def test_live_execution_stops_on_mcp_tool_error(self):
        recipe_result = build_fenics_recipe(
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
        client = ToolErrorMCPClient()

        output = execute_fenics_forward_solve(
            {
                "numerical_recipe": recipe_result["recipe"],
                "numerical_recipe_errors": [],
            },
            client=client,
            execute=True,
        )

        called_tools = [tool_name for tool_name, _arguments in client.calls]
        self.assertEqual(output["execution_mode"], "failed")
        self.assertEqual(output["fenics_result"]["status"], "failed")
        self.assertEqual(output["failed_tool"], "apply_boundary_condition")
        self.assertTrue(output["errors"])
        self.assertIn("DOLFINX_API_ERROR", output["errors"][0])
        self.assertNotIn("solve_time_dependent", called_tools)

    def test_without_client_returns_planned_workflow(self):
        recipe_result = build_fenics_recipe(
            {
                "raw_user_input": (
                    "Solve Poisson on the unit square with f = 1 and "
                    "u=0 on boundary."
                ),
                "problem_class": "forward_problem",
                "pde_info": "poisson_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1.0",
                "source_info": "1.0",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "fem_problem_setup",
            }
        )

        output = execute_fenics_forward_solve(
            {
                "numerical_recipe": recipe_result["recipe"],
                "numerical_recipe_errors": [],
            },
            execute=False,
        )

        self.assertEqual(output["execution_mode"], "planned")
        self.assertTrue(output["mcp_calls"])


if __name__ == "__main__":
    unittest.main()
