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


if __name__ == "__main__":
    unittest.main()
