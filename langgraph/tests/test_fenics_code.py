import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("requests", types.ModuleType("requests"))

from aes_agent.fenics_code import (
    _fallback_dolfinx_script,
    build_user_code_candidate,
    execute_fenics_code_solve,
    validate_python_code_safety,
)


SAFE_CODE = """from dolfinx import fem
import ufl
import json

print(json.dumps({"ok": True}))
"""


class _FakeCodeRunnerClient:
    def list_tools(self):
        return [{"name": "run_python_script"}]

    def call_tool(self, name, arguments=None):
        return {
            "status": "completed",
            "message": "ok",
            "stdout": '{"problem": "test"}\n',
            "stderr": "",
            "diagnostics": {
                "return_code": 0,
                "artifact_count": 2,
                "elapsed_seconds": 1.25,
                "script": {
                    "problem": "transient_heat_equation",
                    "num_steps": 100,
                    "dt": 0.01,
                    "final_time": 1.0,
                    "num_dofs": 1089,
                    "solution_min": 0.0,
                    "solution_max": 0.12,
                    "solution_mean": 0.04,
                },
            },
            "artifacts": [
                {
                    "name": "solve.py",
                    "kind": "source_code",
                    "status": "available",
                    "uri": "mcp://fenics-code-runner/workspace/code-runs/test/solve.py",
                    "storage": "provider_workspace",
                    "media_type": "text/x-python",
                    "producer": {
                        "provider": "mcp:fenics-code-runner",
                        "tool_name": name,
                    },
                    "metadata": {},
                },
                {
                    "name": "solution.xdmf",
                    "kind": "solution",
                    "status": "available",
                    "uri": "mcp://fenics-code-runner/workspace/code-runs/test/solution.xdmf",
                    "storage": "provider_workspace",
                    "media_type": "application/x-xdmf",
                    "producer": {
                        "provider": "mcp:fenics-code-runner",
                        "tool_name": name,
                    },
                    "metadata": {},
                },
            ],
            "errors": [],
            "warnings": [],
        }


class _FailThenSucceedCodeRunnerClient:
    def __init__(self):
        self.calls = 0

    def list_tools(self):
        return [{"name": "run_python_script"}]

    def call_tool(self, name, arguments=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "status": "failed",
                "stdout": "",
                "stderr": "NameError: name 'bad_symbol' is not defined",
                "errors": ["NameError: name 'bad_symbol' is not defined"],
                "diagnostics": {
                    "return_code": 1,
                    "artifact_count": 1,
                    "elapsed_seconds": 0.2,
                },
            }
        return _FakeCodeRunnerClient().call_tool(name, arguments)


class FenicsCodeTests(unittest.TestCase):
    def test_static_safety_rejects_subprocess_import(self):
        result = validate_python_code_safety(
            "import subprocess\nsubprocess.run(['echo', 'bad'])\n"
        )

        self.assertEqual(result["status"], "unsafe")
        self.assertTrue(any("subprocess" in error for error in result["errors"]))

    def test_user_code_candidate_extracts_fenced_python(self):
        result = build_user_code_candidate(
            {
                "raw_user_input": (
                    "Please run this:\n"
                    "```python\n"
                    "from dolfinx import fem\n"
                    "print('ok')\n"
                    "```"
                )
            }
        )

        self.assertTrue(result["python_code"].startswith("from dolfinx"))
        self.assertEqual(result["warnings"], [])

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

    @patch(
        "aes_agent.fenics_code.ollama_json",
        return_value={
            "summary": "Generated test code.",
            "python_code": SAFE_CODE,
            "expected_artifacts": ["solution.xdmf"],
        },
    )
    def test_execution_request_with_script_runner_executes(self, _ollama_json):
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
            client=_FakeCodeRunnerClient(),
            execute=True,
        )

        self.assertEqual(output["execution_mode"], "executed")
        self.assertEqual(output["errors"], [])
        self.assertEqual(output["fenics_result"]["status"], "completed")
        self.assertEqual(
            output["fenics_result"]["diagnostics"]["return_code"],
            0,
        )
        self.assertIn(
            "diagnostics.json",
            [file["name"] for file in output["generated_files"]],
        )
        self.assertIn(
            "stdout.txt",
            [file["name"] for file in output["generated_files"]],
        )
        artifact_names = [
            artifact["name"]
            for artifact in output["fenics_result"]["artifacts"]
        ]
        self.assertEqual(artifact_names, ["solve.py", "solution.xdmf"])

    def test_fallback_heat_script_sets_petsc_options_prefix(self):
        script = _fallback_dolfinx_script(
            {
                "raw_user_input": "Solve transient heat equation with du/dt.",
                "pde_info": "time_dependent_heat_equation",
                "coefficient_info": "1",
                "source_info": "1",
                "initial_condition_info": "sin(pi*x)*sin(pi*y)",
                "time_info": "T=1, dt=0.01",
            }
        )

        self.assertIn('petsc_options_prefix="aes_heat_"', script)

    def test_fallback_poisson_script_sets_petsc_options_prefix(self):
        script = _fallback_dolfinx_script(
            {
                "raw_user_input": "Solve stationary diffusion equation.",
                "pde_info": "stationary_diffusion_equation",
                "coefficient_info": "1",
                "source_info": "1",
            }
        )

        self.assertIn('petsc_options_prefix="aes_poisson_"', script)

    @patch(
        "aes_agent.fenics_code.ollama_json",
        side_effect=[
            {
                "summary": "Generated broken code.",
                "python_code": "from dolfinx import fem\nbad = \b\n",
                "expected_artifacts": ["solution.xdmf"],
            },
            {
                "summary": "Repaired syntax.",
                "python_code": SAFE_CODE,
                "expected_artifacts": ["solution.xdmf"],
            },
        ],
    )
    def test_static_syntax_error_triggers_repair(self, ollama_json):
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

        self.assertEqual(ollama_json.call_count, 2)
        self.assertEqual(output["execution_mode"], "generated")
        self.assertEqual(output["safety_status"], "safe")
        self.assertEqual(output["repair_attempt_count"], 1)
        self.assertEqual(output["repair_attempts"][0]["failure_type"], "static_validation")
        self.assertIn("from dolfinx", output["generated_files"][0]["content"])

    @patch(
        "aes_agent.fenics_code.ollama_json",
        side_effect=[
            {
                "summary": "Generated runtime-broken code.",
                "python_code": SAFE_CODE,
                "expected_artifacts": ["solution.xdmf"],
            },
            {
                "summary": "Repaired runtime error.",
                "python_code": SAFE_CODE,
                "expected_artifacts": ["solution.xdmf"],
            },
        ],
    )
    def test_runtime_execution_error_triggers_repair(self, ollama_json):
        client = _FailThenSucceedCodeRunnerClient()
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
            client=client,
            execute=True,
        )

        self.assertEqual(ollama_json.call_count, 2)
        self.assertEqual(client.calls, 2)
        self.assertEqual(output["execution_mode"], "executed")
        self.assertEqual(output["errors"], [])
        self.assertEqual(output["repair_attempt_count"], 1)
        self.assertEqual(output["repair_attempts"][0]["failure_type"], "runtime_execution")

    @patch(
        "aes_agent.fenics_code.ollama_json",
        return_value={
            "summary": "Generated test code.",
            "python_code": SAFE_CODE,
            "expected_artifacts": ["solution.xdmf"],
        },
    )
    def test_execution_request_with_execution_disabled_is_blocked_but_keeps_code(
        self,
        _ollama_json,
    ):
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
            execute=False,
        )

        self.assertEqual(output["execution_mode"], "blocked")
        self.assertTrue(output["errors"])
        self.assertEqual(output["generated_files"][0]["name"], "solve.py")
        artifact_statuses = {
            artifact["name"]: artifact["status"]
            for artifact in output["fenics_result"]["artifacts"]
        }
        self.assertEqual(artifact_statuses["solve.py"], "available")
        self.assertEqual(artifact_statuses["solution.xdmf"], "blocked")

    def test_user_code_path_uses_user_code_without_llm(self):
        output = execute_fenics_code_solve(
            {
                "raw_user_input": (
                    "```python\n"
                    "from dolfinx import fem\n"
                    "import ufl\n"
                    "print('ok')\n"
                    "```"
                ),
                "solution_mode": "execute_user_fenics_code",
                "numerical_recipe": {
                    "provider": "local:fenics_code",
                    "workflow": "llm_generated_dolfinx_script_v1",
                    "execution_requested": True,
                },
            },
            execute=False,
        )

        self.assertEqual(output["execution_mode"], "blocked")
        self.assertEqual(output["safety_status"], "safe")
        self.assertIn("from dolfinx", output["generated_files"][0]["content"])

    def test_unsafe_user_code_is_rejected_before_artifact_materialization(self):
        output = execute_fenics_code_solve(
            {
                "raw_user_input": (
                    "```python\n"
                    "import subprocess\n"
                    "subprocess.run(['echo', 'bad'])\n"
                    "```"
                ),
                "solution_mode": "execute_user_fenics_code",
                "numerical_recipe": {
                    "provider": "local:fenics_code",
                    "workflow": "llm_generated_dolfinx_script_v1",
                    "execution_requested": True,
                },
            },
            execute=True,
        )

        self.assertEqual(output["execution_mode"], "failed")
        self.assertEqual(output["safety_status"], "unsafe")
        self.assertEqual(output["generated_files"], [])


if __name__ == "__main__":
    unittest.main()
