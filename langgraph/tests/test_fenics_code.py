import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("requests", types.ModuleType("requests"))

from aes_agent.fenics_code import (
    execute_fenics_code_solve,
    validate_python_code_safety,
)


SAFE_CODE = """from dolfinx import fem
import ufl
import json

print(json.dumps({"ok": True}))
"""


class FenicsCodeTests(unittest.TestCase):
    def test_static_safety_rejects_subprocess_import(self):
        result = validate_python_code_safety(
            "import subprocess\nsubprocess.run(['echo', 'bad'])\n"
        )

        self.assertEqual(result["status"], "unsafe")
        self.assertTrue(any("subprocess" in error for error in result["errors"]))

    @patch(
        "aes_agent.fenics_code.ollama_json",
        return_value={
            "summary": "Generated test code.",
            "python_code": SAFE_CODE,
            "expected_artifacts": ["solution.xdmf"],
        },
    )
    def test_code_solve_generates_checked_python_file(self, _ollama_json):
        output = execute_fenics_code_solve(
            {
                "raw_user_input": "As a solution I need a FEniCS executable python file.",
                "solution_mode": "generate_fenics_code",
                "numerical_recipe": {
                    "provider": "local:fenics_code",
                    "workflow": "llm_generated_dolfinx_script_v1",
                    "execution_requested": False,
                },
            }
        )

        self.assertEqual(output["execution_mode"], "generated")
        self.assertEqual(output["safety_status"], "safe")
        self.assertEqual(output["generated_file_names"], ["solve.py"])
        self.assertEqual(output["generated_files"][0]["name"], "solve.py")
        self.assertIn("solution.xdmf", [a["name"] for a in output["fenics_result"]["artifacts"]])

    @patch(
        "aes_agent.fenics_code.ollama_json",
        return_value={
            "summary": "Generated test code.",
            "python_code": SAFE_CODE,
            "expected_artifacts": ["solution.xdmf"],
        },
    )
    def test_execution_request_without_script_runner_is_blocked(self, _ollama_json):
        output = execute_fenics_code_solve(
            {
                "raw_user_input": "Execute this solve.",
                "solution_mode": "execute_generated_fenics_code",
                "numerical_recipe": {
                    "provider": "local:fenics_code",
                    "workflow": "llm_generated_dolfinx_script_v1",
                    "execution_requested": True,
                },
            },
            execute=True,
        )

        self.assertEqual(output["execution_mode"], "blocked")
        self.assertTrue(output["errors"])


if __name__ == "__main__":
    unittest.main()
