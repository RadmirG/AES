import unittest

from aes_agent.tools import (
    TOOL_REGISTRY,
    ToolDefinition,
    execute_tool,
    export_problem_spec,
    list_available_tools,
    register_tool,
    tool_catalog,
)


class ToolRegistryTests(unittest.TestCase):
    def test_catalog_matches_registered_tool_names(self):
        catalog_names = [tool["name"] for tool in tool_catalog()]

        self.assertEqual(catalog_names, list_available_tools())

    def test_problem_spec_exporter_returns_canonical_structure(self):
        result = export_problem_spec(
            {
                "problem_class": "forward_problem",
                "pde_info": "stationary_diffusion_equation",
                "domain_info": "rectangular_domain",
                "coefficient_info": "constant_coefficient_given",
                "bc_info": "dirichlet_boundary_condition",
                "selected_formulation": "weak_formulation_candidate",
                "validation_status": "valid",
            }
        )

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(
            result["problem"]["pde"],
            "stationary_diffusion_equation",
        )
        self.assertEqual(
            result["formulation"],
            "weak_formulation_candidate",
        )

    def test_execute_tool_returns_structured_failure_for_unknown_tool(self):
        result = execute_tool("unknown_tool", {})

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["provider"], "")
        self.assertEqual(result["output"], {})
        self.assertIn("Unknown tool", result["error"])

    def test_register_tool_adds_provider_aware_tool(self):
        definition = ToolDefinition(
            name="test_tool",
            description="Test-only tool.",
            provider="test",
            handler=lambda _state: {"value": 1},
        )
        try:
            register_tool(definition)

            result = execute_tool("test_tool", {})
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["provider"], "test")
            self.assertEqual(result["output"], {"value": 1})
        finally:
            TOOL_REGISTRY.pop("test_tool", None)


if __name__ == "__main__":
    unittest.main()
