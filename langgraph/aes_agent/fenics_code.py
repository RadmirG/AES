from __future__ import annotations

import ast
import json
import os
import re
from typing import Any, Dict, List, Protocol

from aes_agent.helpers import ollama_json, safe_list_of_str, safe_str
from aes_agent.prompts import generate_fenics_dolfinx_code_prompt
from aes_agent.state import AgentState


FENICS_CODE_TOOL_NAME = "fenics_code_solve"
FENICS_CODE_PROVIDER = "local:fenics_code"
FENICS_CODE_WORKFLOW = "llm_generated_dolfinx_script_v1"
DEFAULT_SCRIPT_NAME = "solve.py"

ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "dolfinx",
    "ufl",
    "mpi4py",
    "petsc4py",
    "numpy",
    "matplotlib",
    "math",
    "json",
    "pathlib",
}

BANNED_IMPORT_ROOTS = {
    "builtins",
    "ctypes",
    "http",
    "multiprocessing",
    "os",
    "pickle",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "threading",
    "urllib",
}

BANNED_CALL_NAMES = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "vars",
}

BANNED_ATTRIBUTE_NAMES = {
    "chmod",
    "chown",
    "kill",
    "popen",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "rmtree",
    "system",
    "unlink",
}

SUSPICIOUS_STRING_MARKERS = (
    "://",
    "/etc/",
    "/root/",
    "/var/run/docker.sock",
    "c:\\",
    "..",
    "~",
)

EXECUTION_TOOL_CANDIDATES = (
    "run_python_script",
    "execute_python_script",
    "run_script",
)


class MCPCodeExecutionClient(Protocol):
    def list_tools(self) -> List[Dict[str, Any]]:
        ...

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        ...


def build_fenics_code_recipe(state: AgentState) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "provider": FENICS_CODE_PROVIDER,
        "workflow": FENICS_CODE_WORKFLOW,
        "problem_type": state.get("pde_info", ""),
        "solution_mode": state.get("solution_mode", "generate_fenics_code"),
        "execution_requested": state.get("solution_mode") in {
            "execute_generated_fenics_code",
            "execute_user_fenics_code",
        },
        "target": {
            "language": "python",
            "framework": "dolfinx",
            "entrypoint": DEFAULT_SCRIPT_NAME,
            "code_origin": (
                "user"
                if state.get("solution_mode") == "execute_user_fenics_code"
                else "llm"
            ),
        },
        "problem": {
            "class": state.get("problem_class", ""),
            "pde": state.get("pde_info", ""),
            "domain": state.get("domain_info", ""),
            "coefficients": state.get("coefficient_info", ""),
            "source": state.get("source_info", ""),
            "boundary_conditions": state.get("bc_info", ""),
            "initial_condition": state.get("initial_condition_info", ""),
            "time": state.get("time_info", ""),
            "raw_user_input": state.get("raw_user_input", ""),
        },
        "outputs": [
            DEFAULT_SCRIPT_NAME,
            "diagnostics.json",
            "solution.xdmf",
            "solution.png",
        ],
        "assumptions": [
            "Generate a complete DOLFINx Python script before attempting execution.",
            "Execute generated code only inside a FEniCS/DOLFINx provider sandbox.",
        ],
    }


def execute_fenics_code_solve(
    state: AgentState,
    *,
    client: MCPCodeExecutionClient | None = None,
    execute: bool | None = None,
) -> Dict[str, Any]:
    recipe = state.get("numerical_recipe") or build_fenics_code_recipe(state)
    if state.get("solution_mode") == "execute_user_fenics_code":
        generation = build_user_code_candidate(state)
    else:
        generation = generate_dolfinx_script(state, recipe)
    code = generation["python_code"]
    safety = validate_python_code_safety(code)

    if safety["status"] != "safe":
        return _build_output(
            recipe=recipe,
            generation=generation,
            safety=safety,
            execution_mode="failed",
            status="failed",
            errors=safety["errors"],
            warnings=safety["warnings"],
        )

    execution_requested = bool(recipe.get("execution_requested"))
    should_execute = (
        _should_execute_live()
        if execute is None
        else bool(execute)
    ) and execution_requested

    if not should_execute:
        warnings = list(generation["warnings"])
        if execution_requested:
            error = (
                "Execution was requested, but DOLFINX_CODE_EXECUTE is not enabled; "
                "AES generated/stored the checked solve.py without running it."
            )
            warnings.append(error)
            return _build_output(
                recipe=recipe,
                generation=generation,
                safety=safety,
                execution_mode="blocked",
                status="blocked",
                errors=[error],
                warnings=warnings,
            )
        return _build_output(
            recipe=recipe,
            generation=generation,
            safety=safety,
            execution_mode="generated",
            status="generated",
            errors=[],
            warnings=warnings,
        )

    if client is None:
        client = _default_code_execution_client()

    if client is None:
        return _build_output(
            recipe=recipe,
            generation=generation,
            safety=safety,
            execution_mode="blocked",
            status="failed",
            errors=[
                "Generated-code execution was requested, but no MCP script-runner "
                "endpoint is configured. Set DOLFINX_CODE_MCP_URL and provide a "
                "provider tool such as run_python_script."
            ],
            warnings=generation["warnings"],
        )

    execution = _execute_code_via_mcp(client, code)
    errors = execution.get("errors", [])
    status = "completed" if not errors else "failed"
    execution_mode = "executed" if not errors else "failed"
    return _build_output(
        recipe=recipe,
        generation=generation,
        safety=safety,
        execution_mode=execution_mode,
        status=status,
        errors=errors,
        warnings=generation["warnings"] + execution.get("warnings", []),
        execution=execution,
    )


def generate_dolfinx_script(
    state: AgentState,
    recipe: Dict[str, Any],
) -> Dict[str, Any]:
    snapshot = {
        "raw_user_input": state.get("raw_user_input", ""),
        "problem_class": state.get("problem_class", ""),
        "pde_info": state.get("pde_info", ""),
        "domain_info": state.get("domain_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "selected_formulation": state.get("selected_formulation", ""),
        "numerical_recipe": recipe,
    }
    model_result = ollama_json(generate_fenics_dolfinx_code_prompt(snapshot))
    code = _extract_code(safe_str(model_result.get("python_code"), ""))
    summary = safe_str(model_result.get("summary"), "")
    expected_artifacts = safe_list_of_str(model_result.get("expected_artifacts"))
    warnings: List[str] = []

    if not code:
        code = _fallback_dolfinx_script(state)
        summary = (
            "Generated a conservative DOLFINx fallback script because the LLM "
            "did not return usable code."
        )
        expected_artifacts = ["solve.py", "solution.xdmf", "diagnostics.json"]
        warnings.append("LLM code generation returned no usable python_code.")

    if not expected_artifacts:
        expected_artifacts = ["solve.py", "solution.xdmf", "diagnostics.json"]

    return {
        "summary": summary or "Generated a DOLFINx Python solver script.",
        "python_code": code,
        "expected_artifacts": _dedupe(["solve.py", *expected_artifacts]),
        "warnings": warnings,
    }


def build_user_code_candidate(state: AgentState) -> Dict[str, Any]:
    code = _extract_user_python_code(state.get("raw_user_input", ""))
    return {
        "summary": "Using user-provided Python code as candidate solve.py.",
        "python_code": code,
        "expected_artifacts": ["solve.py", "diagnostics.json", "solution.xdmf", "solution.png"],
        "warnings": [] if code else ["No Python code block or FEniCS-like Python code was detected."],
    }


def validate_python_code_safety(code: str) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not code.strip():
        return {
            "status": "unsafe",
            "errors": ["Python code is empty."],
            "warnings": [],
        }

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {
            "status": "unsafe",
            "errors": [f"Generated Python code has a syntax error: {exc}"],
            "warnings": [],
        }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import_root(alias.name, errors)
        elif isinstance(node, ast.ImportFrom):
            _check_import_root(node.module or "", errors)
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name in BANNED_CALL_NAMES:
                errors.append(f"Blocked unsafe call: {call_name}.")
            attr_name = _attribute_name(node.func)
            if attr_name in BANNED_ATTRIBUTE_NAMES:
                errors.append(f"Blocked unsafe attribute call: {attr_name}.")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if any(marker in lowered for marker in SUSPICIOUS_STRING_MARKERS):
                warnings.append(
                    f"Suspicious path or URL-like string found: {_truncate(node.value)}"
                )

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    return {
        "status": "safe" if not errors else "unsafe",
        "errors": errors,
        "warnings": warnings,
    }


def _check_import_root(module: str, errors: List[str]) -> None:
    root = module.split(".", 1)[0]
    if not root:
        return
    if root in BANNED_IMPORT_ROOTS:
        errors.append(f"Blocked unsafe import: {root}.")
    elif root not in ALLOWED_IMPORT_ROOTS:
        errors.append(f"Import is not on the FEniCS code allowlist: {root}.")


def _call_name(func: ast.AST) -> str:
    return func.id if isinstance(func, ast.Name) else ""


def _attribute_name(func: ast.AST) -> str:
    return func.attr if isinstance(func, ast.Attribute) else ""


def _extract_code(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:python)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_user_python_code(value: str) -> str:
    stripped = value.strip()
    fenced = re.search(
        r"```(?:python|py)?\s*(.*?)```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        return fenced.group(1).strip()
    return stripped


def _fallback_dolfinx_script(state: AgentState) -> str:
    text = " ".join(
        str(state.get(field, ""))
        for field in (
            "raw_user_input",
            "pde_info",
            "initial_condition_info",
            "time_info",
        )
    ).lower()
    if "time_dependent_heat" in text or "transient" in text or "du/dt" in text:
        return _fallback_heat_script(state)
    return _fallback_poisson_script(state)


def _fallback_heat_script(state: AgentState) -> str:
    alpha = _number_or_default(state.get("coefficient_info", ""), "1.0")
    source = _number_or_default(state.get("source_info", ""), "1.0")
    initial = _dolfinx_expression_or_default(
        state.get("initial_condition_info", ""),
        "np.sin(np.pi * x[0]) * np.sin(np.pi * x[1])",
    )
    t_end = _extract_float(str(state.get("time_info", "")), r"\bT\s*=\s*([0-9]*\.?[0-9]+)", "1.0")
    dt = _extract_float(str(state.get("time_info", "")), r"\bdt\s*=\s*([0-9]*\.?[0-9]+)", "0.01")
    return f'''from mpi4py import MPI
from petsc4py import PETSc
from dolfinx import fem, io, mesh
from dolfinx.fem.petsc import LinearProblem
from pathlib import Path
import json
import numpy as np
import ufl


alpha_value = {alpha}
source_value = {source}
T = {t_end}
dt = {dt}
num_steps = int(round(T / dt))

msh = mesh.create_unit_square(MPI.COMM_WORLD, 32, 32, cell_type=mesh.CellType.triangle)
V = fem.functionspace(msh, ("Lagrange", 1))

u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
u_n = fem.Function(V)
u_n.name = "u_n"
u_n.interpolate(lambda x: {initial})

boundary_facets = mesh.locate_entities_boundary(
    msh,
    msh.topology.dim - 1,
    lambda x: np.full(x.shape[1], True, dtype=bool),
)
boundary_dofs = fem.locate_dofs_topological(V, msh.topology.dim - 1, boundary_facets)
bc = fem.dirichletbc(PETSc.ScalarType(0.0), boundary_dofs, V)

alpha = fem.Constant(msh, PETSc.ScalarType(alpha_value))
f = fem.Constant(msh, PETSc.ScalarType(source_value))
a = (u * v + dt * alpha * ufl.dot(ufl.grad(u), ufl.grad(v))) * ufl.dx
L = (u_n + dt * f) * v * ufl.dx

u_sol = fem.Function(V)
u_sol.name = "u"
problem = LinearProblem(
    a,
    L,
    bcs=[bc],
    u=u_sol,
    petsc_options={{"ksp_type": "cg", "pc_type": "hypre"}},
)

for step in range(num_steps):
    problem.solve()
    u_n.x.array[:] = u_sol.x.array

with io.XDMFFile(msh.comm, "solution.xdmf", "w") as xdmf:
    xdmf.write_mesh(msh)
    xdmf.write_function(u_sol, T)

diagnostics = {{
    "problem": "transient_heat_equation",
    "num_steps": num_steps,
    "dt": dt,
    "final_time": T,
    "num_dofs": V.dofmap.index_map.size_global * V.dofmap.index_map_bs,
}}
Path("diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
print(json.dumps(diagnostics, indent=2))
'''


def _fallback_poisson_script(state: AgentState) -> str:
    coefficient = _number_or_default(state.get("coefficient_info", ""), "1.0")
    source = _number_or_default(state.get("source_info", ""), "1.0")
    bc_value = _boundary_value_or_default(state.get("raw_user_input", ""), "0.0")
    return f'''from mpi4py import MPI
from petsc4py import PETSc
from dolfinx import fem, io, mesh
from dolfinx.fem.petsc import LinearProblem
from pathlib import Path
import json
import numpy as np
import ufl


coefficient_value = {coefficient}
source_value = {source}
boundary_value = {bc_value}

msh = mesh.create_unit_square(MPI.COMM_WORLD, 32, 32, cell_type=mesh.CellType.triangle)
V = fem.functionspace(msh, ("Lagrange", 1))

u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)

boundary_facets = mesh.locate_entities_boundary(
    msh,
    msh.topology.dim - 1,
    lambda x: np.full(x.shape[1], True, dtype=bool),
)
boundary_dofs = fem.locate_dofs_topological(V, msh.topology.dim - 1, boundary_facets)
bc = fem.dirichletbc(PETSc.ScalarType(boundary_value), boundary_dofs, V)

k = fem.Constant(msh, PETSc.ScalarType(coefficient_value))
f = fem.Constant(msh, PETSc.ScalarType(source_value))
a = k * ufl.dot(ufl.grad(u), ufl.grad(v)) * ufl.dx
L = f * v * ufl.dx

u_sol = fem.Function(V)
u_sol.name = "u"
problem = LinearProblem(
    a,
    L,
    bcs=[bc],
    u=u_sol,
    petsc_options={{"ksp_type": "cg", "pc_type": "hypre"}},
)
problem.solve()

with io.XDMFFile(msh.comm, "solution.xdmf", "w") as xdmf:
    xdmf.write_mesh(msh)
    xdmf.write_function(u_sol)

diagnostics = {{
    "problem": "stationary_diffusion_equation",
    "num_dofs": V.dofmap.index_map.size_global * V.dofmap.index_map_bs,
}}
Path("diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
print(json.dumps(diagnostics, indent=2))
'''


def _number_or_default(value: Any, default: str) -> str:
    match = re.search(r"[-+]?[0-9]*\.?[0-9]+", str(value))
    return match.group(0) if match else default


def _boundary_value_or_default(text: str, default: str) -> str:
    match = re.search(r"\bg\s*=\s*([-+]?[0-9]*\.?[0-9]+)", str(text), flags=re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"\bu\s*=\s*([-+]?[0-9]*\.?[0-9]+)", str(text), flags=re.IGNORECASE)
    return match.group(1) if match else default


def _dolfinx_expression_or_default(value: Any, default: str) -> str:
    expression = str(value).strip()
    if not expression or "unknown" in expression.lower():
        return default
    expression = expression.replace("^", "**")
    expression = re.sub(r"\bsin\(", "np.sin(", expression)
    expression = re.sub(r"\bcos\(", "np.cos(", expression)
    expression = re.sub(r"\bpi\b", "np.pi", expression)
    expression = expression.replace("x[0]", "__AES_X0__")
    expression = expression.replace("x[1]", "__AES_X1__")
    expression = re.sub(r"\bx\b", "x[0]", expression)
    expression = re.sub(r"\by\b", "x[1]", expression)
    expression = expression.replace("__AES_X0__", "x[0]")
    expression = expression.replace("__AES_X1__", "x[1]")
    return expression


def _extract_float(text: str, pattern: str, default: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1) if match else default


def _should_execute_live() -> bool:
    value = os.getenv("DOLFINX_CODE_EXECUTE", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _default_code_execution_client() -> MCPCodeExecutionClient | None:
    url = (
        os.getenv("DOLFINX_CODE_MCP_URL", "").strip()
        or os.getenv("DOLFINX_MCP_URL", "").strip()
    )
    if not url:
        return None

    from aes_agent.mcp_client import StreamableHTTPMCPClient

    timeout = int(
        os.getenv(
            "DOLFINX_CODE_MCP_TIMEOUT",
            os.getenv("DOLFINX_CODE_TIMEOUT", os.getenv("DOLFINX_MCP_TIMEOUT", "120")),
        )
    )
    protocol_version = os.getenv("DOLFINX_MCP_PROTOCOL", "2025-06-18")
    return StreamableHTTPMCPClient(
        url,
        timeout=timeout,
        protocol_version=protocol_version,
    )


def _execute_code_via_mcp(
    client: MCPCodeExecutionClient,
    code: str,
) -> Dict[str, Any]:
    available_tools = {
        tool.get("name")
        for tool in client.list_tools()
        if isinstance(tool, dict)
    }
    preferred_tool = os.getenv("DOLFINX_CODE_MCP_TOOL", "").strip()
    candidates = (preferred_tool, *EXECUTION_TOOL_CANDIDATES) if preferred_tool else EXECUTION_TOOL_CANDIDATES
    tool_name = next((name for name in candidates if name in available_tools), "")
    if not tool_name:
        return {
            "errors": [
                "The configured FEniCS MCP provider does not expose a script "
                "execution tool. Expected one of: "
                + ", ".join(EXECUTION_TOOL_CANDIDATES)
            ],
            "warnings": [],
            "result": {},
        }

    result = client.call_tool(
        tool_name,
        {
            "filename": DEFAULT_SCRIPT_NAME,
            "code": code,
            "timeout_seconds": int(os.getenv("DOLFINX_CODE_TIMEOUT", "300")),
        },
    )
    errors = _mcp_errors_from_result(result)
    return {
        "tool_name": tool_name,
        "result": result,
        "errors": errors,
        "warnings": [],
    }


def _mcp_errors_from_result(result: Dict[str, Any]) -> List[str]:
    if not isinstance(result, dict):
        return ["MCP script execution returned a non-object result."]
    raw_errors = result.get("errors")
    if isinstance(raw_errors, list) and raw_errors:
        return [str(error) for error in raw_errors if str(error).strip()]
    if raw_errors:
        return [str(raw_errors)]
    if result.get("isError") is True or result.get("is_error") is True:
        return [str(result.get("message") or result.get("error") or result)]
    if result.get("error"):
        return [str(result["error"])]
    status = str(result.get("status", "")).lower()
    if status in {"error", "failed", "failure"}:
        return [str(result.get("message") or result)]
    return []


def _build_output(
    *,
    recipe: Dict[str, Any],
    generation: Dict[str, Any],
    safety: Dict[str, Any],
    execution_mode: str,
    status: str,
    errors: List[str],
    warnings: List[str],
    execution: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    execution = execution or {}
    execution_result = (
        execution.get("result", {})
        if isinstance(execution.get("result", {}), dict)
        else {}
    )
    execution_artifacts = execution_result.get("artifacts")
    artifacts = _artifact_refs(
        generation["expected_artifacts"],
        status="available" if status in {"generated", "completed"} else "blocked",
    )
    if isinstance(execution_artifacts, list) and execution_artifacts:
        artifacts = [
            artifact
            for artifact in execution_artifacts
            if isinstance(artifact, dict)
        ]
    return {
        "schema_version": "1.0",
        "provider": FENICS_CODE_PROVIDER,
        "execution_mode": execution_mode,
        "recipe": recipe,
        "generated_file_names": [DEFAULT_SCRIPT_NAME],
        "generated_files": [
            {
                "name": DEFAULT_SCRIPT_NAME,
                "kind": "source_code",
                "media_type": "text/x-python",
                "content": generation["python_code"],
            }
        ] if status in {"generated", "completed", "blocked"} else [],
        "code_summary": generation["summary"],
        "safety_status": safety["status"],
        "safety_warnings": safety["warnings"],
        "execution": execution,
        "fenics_result": {
            "schema_version": "1.0",
            "provider": FENICS_CODE_PROVIDER,
            "status": status,
            "execution_mode": execution_mode,
            "workflow": recipe.get("workflow", FENICS_CODE_WORKFLOW),
            "problem_type": recipe.get("problem_type", ""),
            "artifacts": artifacts,
            "requested_artifacts": [],
            "diagnostics": execution.get("diagnostics", {}) or execution_result.get("diagnostics", {}),
            "errors": errors,
            "warnings": warnings + safety["warnings"],
        },
        "errors": errors,
        "warnings": warnings + safety["warnings"],
    }


def _artifact_refs(names: List[str], *, status: str) -> List[Dict[str, Any]]:
    refs = []
    for name in names:
        kind, media_type = _artifact_kind(name)
        artifact_status = (
            "available"
            if status == "blocked" and name == DEFAULT_SCRIPT_NAME
            else status
        )
        refs.append(
            {
                "name": name,
                "kind": kind,
                "status": artifact_status,
                "uri": f"inline://fenics-code/{name}" if name == DEFAULT_SCRIPT_NAME else f"mcp://dolfinx/workspace/{name}",
                "storage": "inline" if name == DEFAULT_SCRIPT_NAME else "provider_workspace",
                "media_type": media_type,
                "producer": {
                    "provider": FENICS_CODE_PROVIDER,
                    "tool_name": FENICS_CODE_TOOL_NAME,
                },
                "metadata": {},
            }
        )
    return refs


def _artifact_kind(name: str) -> tuple[str, str]:
    lowered = name.lower()
    if lowered.endswith(".py"):
        return "source_code", "text/x-python"
    if lowered.endswith(".json"):
        return "diagnostics", "application/json"
    if lowered.endswith(".png"):
        return "plot", "image/png"
    if lowered.endswith(".xdmf"):
        return "solution", "application/x-xdmf"
    return "artifact", "application/octet-stream"


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def _truncate(value: str, limit: int = 80) -> str:
    cleaned = " ".join(str(value).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."
