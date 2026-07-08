import unittest

from aes_agent.routing import (
    route_after_completeness,
    route_after_numerical_recipe,
    route_after_validation,
)


class RoutingTests(unittest.TestCase):
    def test_missing_information_routes_to_clarification(self):
        state = {"missing_information": ["Boundary conditions are missing."]}

        self.assertEqual(route_after_completeness(state), "clarify")

    def test_complete_problem_routes_to_formulation(self):
        state = {"missing_information": []}

        self.assertEqual(route_after_completeness(state), "formulate")

    def test_valid_formulation_routes_to_tools(self):
        state = {"validation_status": "valid"}

        self.assertEqual(route_after_validation(state), "tools")

    def test_invalid_or_unknown_validation_routes_to_clarification(self):
        self.assertEqual(
            route_after_validation({"validation_status": "invalid"}),
            "clarify",
        )
        self.assertEqual(route_after_validation({}), "clarify")

    def test_ready_numerical_recipe_routes_to_tools(self):
        self.assertEqual(
            route_after_numerical_recipe({"numerical_recipe_status": "ready"}),
            "tools",
        )

    def test_invalid_numerical_recipe_routes_to_clarification(self):
        self.assertEqual(
            route_after_numerical_recipe({"numerical_recipe_status": "invalid"}),
            "clarify",
        )
        self.assertEqual(route_after_numerical_recipe({}), "clarify")


if __name__ == "__main__":
    unittest.main()
