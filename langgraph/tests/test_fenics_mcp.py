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

    def list_tools(self):
        return [{"name": tool_name} for tool_name in ALLOWED_DOLFINX_TOOLS]

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
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
        self.assertIn(
            "solve_time_dependent",
            [tool_name for tool_name, _arguments in client.calls],
        )

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
