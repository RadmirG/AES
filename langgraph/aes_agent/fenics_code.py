from __future__ import annotations

import ast
import json
import os
import re
from typing import Any, Dict, List, Protocol

from aes_agent.helpers import ollama_json, safe_list_of_str, safe_str
from aes_agent.prompts import (
    generate_fenics_dolfinx_code_prompt,
    repair_fenics_dolfinx_code_prompt,
)
from aes_agent.python_checker import (
    check_python_syntax,
    python_code_from_model_result,
    strip_invalid_python_control_chars,
)
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
    is_user_code = state.get("solution_mode") == "execute_user_fenics_code"
    if is_user_code:
        generation = build_user_code_candidate(state)
    else:
        generation = generate_dolfinx_script(state, recipe)

    max_repair_attempts = 0 if is_user_code else _repair_attempt_limit()
    repair_attempts: List[Dict[str, Any]] = []

    execution_requested = bool(recipe.get("execution_requested"))
    should_execute = (
        _should_execute_live()
        if execute is None
        else bool(execute)
    ) and execution_requested

    while True:
        code = generation["python_code"]
        safety = validate_python_code_safety(code)

        if safety["status"] != "safe":
            if _can_repair(repair_attempts, max_repair_attempts):
                generation = _repair_generation(
                    state=state,
                    recipe=recipe,
                    generation=generation,
                    failure_context={
                        "failure_type": "static_validation",
                        "errors": safety["errors"],
                        "warnings": safety["warnings"],
                    },
                    repair_attempts=repair_attempts,
                )
                continue

            if (
                not is_user_code
                and not generation.get("used_fallback_after_repair")
                and _can_use_deterministic_fallback(state)
            ):
                generation = _fallback_generation_after_failed_repairs(
                    state,
                    generation,
                    repair_attempts,
                )
                continue

            return _build_output(
                recipe=recipe,
                generation=generation,
                safety=safety,
                execution_mode="failed",
                status="failed",
                errors=safety["errors"],
                warnings=generation["warnings"] + safety["warnings"],
            )

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
        if not errors:
            return _build_output(
                recipe=recipe,
                generation=generation,
                safety=safety,
                execution_mode="executed",
                status="completed",
                errors=[],
                warnings=generation["warnings"] + execution.get("warnings", []),
                execution=execution,
            )

        if _can_repair(repair_attempts, max_repair_attempts) and _is_repairable_execution_error(execution):
            generation = _repair_generation(
                state=state,
                recipe=recipe,
                generation=generation,
                failure_context=_runtime_failure_context(errors, execution),
                repair_attempts=repair_attempts,
            )
            continue

        return _build_output(
            recipe=recipe,
            generation=generation,
            safety=safety,
            execution_mode="failed",
            status="failed",
            errors=errors,
            warnings=generation["warnings"] + execution.get("warnings", []),
            execution=execution,
        )


def generate_dolfinx_script(
    state: AgentState,
    recipe: Dict[str, Any],
) -> Dict[str, Any]:
    snapshot = _state_snapshot(state, recipe)
    model_result = ollama_json(generate_fenics_dolfinx_code_prompt(snapshot))
    code = python_code_from_model_result(model_result)
    summary = safe_str(model_result.get("summary"), "")
    expected_artifacts = safe_list_of_str(model_result.get("expected_artifacts"))
    warnings: List[str] = []

    if not code:
        generation = _fallback_generation(state)
        code = generation["python_code"]
        summary = generation["summary"]
        expected_artifacts = generation["expected_artifacts"]
        warnings.extend(
            [
                "LLM code generation returned no usable python_code; AES used "
                "its deterministic fallback DOLFINx template.",
                *generation["warnings"],
            ]
        )

    if not expected_artifacts:
        expected_artifacts = ["solve.py", "solution.xdmf", "diagnostics.json"]

    return {
        "summary": summary or "Generated a DOLFINx Python solver script.",
        "python_code": code,
        "expected_artifacts": _dedupe(["solve.py", *expected_artifacts]),
        "warnings": warnings,
        "repair_attempts": [],
    }


def build_user_code_candidate(state: AgentState) -> Dict[str, Any]:
    code = _extract_user_python_code(state.get("raw_user_input", ""))
    return {
        "summary": "Using user-provided Python code as candidate solve.py.",
        "python_code": code,
        "expected_artifacts": ["solve.py", "diagnostics.json", "solution.xdmf", "solution.png"],
        "warnings": [] if code else ["No Python code block or FEniCS-like Python code was detected."],
        "repair_attempts": [],
    }


def validate_python_code_safety(code: str) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    syntax = check_python_syntax(code)
    if syntax["status"] != "valid":
        return {
            "status": "unsafe",
            "errors": syntax["errors"],
            "warnings": syntax["warnings"],
        }

    tree = syntax["tree"]
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


def _extract_user_python_code(value: str) -> str:
    stripped = value.strip()
    fenced = re.search(
        r"```(?:python|py)?\s*(.*?)```",
        stripped,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced:
        return strip_invalid_python_control_chars(fenced.group(1)).strip()
    return strip_invalid_python_control_chars(stripped)


def _strip_invalid_python_control_chars(value: str) -> str:
    return strip_invalid_python_control_chars(value)


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


def _fallback_generation(state: AgentState) -> Dict[str, Any]:
    return {
        "summary": (
            "Generated a conservative DOLFINx fallback script because the LLM "
            "did not return usable code."
        ),
        "python_code": _fallback_dolfinx_script(state),
        "expected_artifacts": ["solve.py", "solution.xdmf", "diagnostics.json"],
        "warnings": [
            "AES used its deterministic fallback DOLFINx template only after "
            "LLM code generation returned no usable python_code."
        ],
        "repair_attempts": [],
    }


def _repair_generation(
    *,
    state: AgentState,
    recipe: Dict[str, Any],
    generation: Dict[str, Any],
    failure_context: Dict[str, Any],
    repair_attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    attempt_number = len(repair_attempts) + 1
    context = {
        **failure_context,
        "attempt": attempt_number,
        "max_attempts": _repair_attempt_limit(),
    }
    current_code = str(generation.get("python_code", ""))
    model_result = ollama_json(
        repair_fenics_dolfinx_code_prompt(
            _state_snapshot(state, recipe),
            current_code,
            context,
        )
    )
    repaired_code = python_code_from_model_result(model_result)
    repair_record = {
        "attempt": attempt_number,
        "failure_type": str(failure_context.get("failure_type", "")),
        "errors": safe_list_of_str(failure_context.get("errors")),
        "status": "repaired" if repaired_code else "no_usable_code",
    }
    repair_attempts.append(repair_record)

    warnings = [
        *safe_list_of_str(generation.get("warnings")),
        (
            f"Repair attempt {attempt_number} requested after "
            f"{repair_record['failure_type']}."
        ),
    ]
    if not repaired_code:
        warnings.append(
            f"Repair attempt {attempt_number} returned no usable python_code; "
            "AES kept the previous generated code."
        )
        return {
            **generation,
            "warnings": _dedupe(warnings),
            "repair_attempts": list(repair_attempts),
        }

    expected_artifacts = safe_list_of_str(model_result.get("expected_artifacts"))
    if not expected_artifacts:
        expected_artifacts = safe_list_of_str(generation.get("expected_artifacts"))
    if not expected_artifacts:
        expected_artifacts = ["solve.py", "solution.xdmf", "diagnostics.json"]

    return {
        "summary": safe_str(
            model_result.get("summary"),
            f"Repaired generated DOLFINx script on attempt {attempt_number}.",
        ),
        "python_code": repaired_code,
        "expected_artifacts": _dedupe(["solve.py", *expected_artifacts]),
        "warnings": _dedupe(warnings),
        "repair_attempts": list(repair_attempts),
    }


def _fallback_generation_after_failed_repairs(
    state: AgentState,
    generation: Dict[str, Any],
    repair_attempts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    fallback = _fallback_generation(state)
    warnings = [
        *safe_list_of_str(generation.get("warnings")),
        (
            "LLM-generated code failed static validation and bounded repair "
            "attempts did not return usable Python; AES used its deterministic "
            "fallback DOLFINx template for this supported simple PDE."
        ),
        *fallback["warnings"],
    ]
    return {
        **fallback,
        "warnings": _dedupe(warnings),
        "repair_attempts": list(repair_attempts),
        "used_fallback_after_repair": True,
    }


def _can_use_deterministic_fallback(state: AgentState) -> bool:
    text = " ".join(
        str(state.get(field, ""))
        for field in (
            "raw_user_input",
            "pde_info",
            "domain_info",
            "bc_info",
            "time_info",
        )
    ).lower()
    return any(
        marker in text
        for marker in (
            "time_dependent_heat",
            "transient heat",
            "du/dt",
            "stationary_diffusion",
            "poisson",
            "-div",
            "heat equation",
        )
    )


def _can_repair(
    repair_attempts: List[Dict[str, Any]],
    max_repair_attempts: int,
) -> bool:
    return len(repair_attempts) < max(0, max_repair_attempts)


def _is_repairable_execution_error(execution: Dict[str, Any]) -> bool:
    if not execution.get("tool_name"):
        return False
    result = execution.get("result", {})
    return isinstance(result, dict)


def _runtime_failure_context(
    errors: List[str],
    execution: Dict[str, Any],
) -> Dict[str, Any]:
    result = execution.get("result", {})
    result = result if isinstance(result, dict) else {}
    return {
        "failure_type": "runtime_execution",
        "errors": errors,
        "tool_name": execution.get("tool_name", ""),
        "stdout": _truncate(str(result.get("stdout") or ""), limit=1200),
        "stderr": _truncate(str(result.get("stderr") or ""), limit=2400),
        "diagnostics": result.get("diagnostics", {}),
        "return_code": result.get("return_code", ""),
    }


def _state_snapshot(state: AgentState, recipe: Dict[str, Any]) -> Dict[str, Any]:
    return {
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
    petsc_options_prefix="aes_heat_",
    petsc_options={{"ksp_type": "cg", "pc_type": "hypre"}},
)

time_series = []
dof_coordinates = V.tabulate_dof_coordinates()[:, :2]
field_samples = []
sample_interval = max(1, num_steps // 10)
sample_steps = sorted(
    set(
        [0, 1, num_steps]
        + [max(1, int(round(num_steps * fraction))) for fraction in (0.1, 0.2, 0.4, 0.6, 0.8)]
    )
)


def solution_stats(function, step, time_value):
    values = function.x.array
    return {{
        "step": int(step),
        "time": float(time_value),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }}


def field_sample(function, step, time_value):
    return {{
        "step": int(step),
        "time": float(time_value),
        "values": function.x.array.astype(float).tolist(),
    }}


if 0 in sample_steps:
    time_series.append(solution_stats(u_n, 0, 0.0))
    field_samples.append(field_sample(u_n, 0, 0.0))


for step in range(1, num_steps + 1):
    problem.solve()
    u_n.x.array[:] = u_sol.x.array
    if step == 1 or step % sample_interval == 0 or step == num_steps:
        time_series.append(solution_stats(u_sol, step, step * dt))
    if step in sample_steps:
        field_samples.append(field_sample(u_sol, step, step * dt))

with io.XDMFFile(msh.comm, "solution.xdmf", "w") as xdmf:
    xdmf.write_mesh(msh)
    xdmf.write_function(u_sol, T)

final_stats = solution_stats(u_sol, num_steps, T)
diagnostics = {{
    "problem": "transient_heat_equation",
    "num_steps": num_steps,
    "dt": dt,
    "final_time": T,
    "num_dofs": V.dofmap.index_map.size_global * V.dofmap.index_map_bs,
    "solution_min": final_stats["min"],
    "solution_max": final_stats["max"],
    "solution_mean": final_stats["mean"],
    "time_series": time_series,
    "field_samples": {{
        "type": "dof_point_cloud_time_series",
        "field": "u",
        "domain": "unit_square",
        "space": "P1",
        "coordinates": dof_coordinates.astype(float).tolist(),
        "samples": field_samples,
        "value_range": {{
            "min": float(min(np.min(np.array(sample["values"])) for sample in field_samples)),
            "max": float(max(np.max(np.array(sample["values"])) for sample in field_samples)),
        }},
    }},
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
    petsc_options_prefix="aes_poisson_",
    petsc_options={{"ksp_type": "cg", "pc_type": "hypre"}},
)
problem.solve()

with io.XDMFFile(msh.comm, "solution.xdmf", "w") as xdmf:
    xdmf.write_mesh(msh)
    xdmf.write_function(u_sol)

values = u_sol.x.array
diagnostics = {{
    "problem": "stationary_diffusion_equation",
    "num_dofs": V.dofmap.index_map.size_global * V.dofmap.index_map_bs,
    "solution_min": float(np.min(values)),
    "solution_max": float(np.max(values)),
    "solution_mean": float(np.mean(values)),
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


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _repair_attempt_limit() -> int:
    raw_value = os.getenv("DOLFINX_CODE_REPAIR_ATTEMPTS", "2").strip()
    try:
        return max(0, int(raw_value))
    except ValueError:
        return 2


def _should_execute_live() -> bool:
    return _env_flag("DOLFINX_CODE_EXECUTE")


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
    return_code = _result_return_code(result)
    if return_code not in {None, 0}:
        message = (
            str(result.get("stderr") or result.get("message") or "").strip()
            or f"Script execution failed with return code {return_code}."
        )
        return [message]
    return []


def _result_return_code(result: Dict[str, Any]) -> int | None:
    raw_code = result.get("return_code")
    diagnostics = result.get("diagnostics")
    if raw_code is None and isinstance(diagnostics, dict):
        raw_code = diagnostics.get("return_code")
    if raw_code is None:
        return None
    try:
        return int(raw_code)
    except (TypeError, ValueError):
        return None


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
    generated_files = _materialized_generated_files(
        code=generation["python_code"],
        safety_status=safety["status"],
        execution_result=execution_result,
    )
    repair_attempts = [
        attempt
        for attempt in generation.get("repair_attempts", [])
        if isinstance(attempt, dict)
    ]
    return {
        "schema_version": "1.0",
        "provider": FENICS_CODE_PROVIDER,
        "execution_mode": execution_mode,
        "recipe": recipe,
        "generated_file_names": [file["name"] for file in generated_files],
        "generated_files": generated_files,
        "code_summary": generation["summary"],
        "safety_status": safety["status"],
        "safety_warnings": safety["warnings"],
        "repair_attempt_count": len(repair_attempts),
        "repair_attempts": repair_attempts,
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


def _materialized_generated_files(
    *,
    code: str,
    safety_status: str,
    execution_result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if safety_status != "safe":
        return []

    files: List[Dict[str, Any]] = [
        {
            "name": DEFAULT_SCRIPT_NAME,
            "kind": "source_code",
            "media_type": "text/x-python",
            "content": code,
        }
    ]

    diagnostics = execution_result.get("diagnostics")
    if isinstance(diagnostics, dict) and diagnostics:
        files.append(
            {
                "name": "diagnostics.json",
                "kind": "diagnostics",
                "media_type": "application/json",
                "content": json.dumps(diagnostics, indent=2, sort_keys=True),
            }
        )

    stdout = str(execution_result.get("stdout") or "").strip()
    if stdout:
        files.append(
            {
                "name": "stdout.txt",
                "kind": "execution_log",
                "media_type": "text/plain",
                "content": stdout + "\n",
            }
        )

    stderr = str(execution_result.get("stderr") or "").strip()
    if stderr:
        files.append(
            {
                "name": "stderr.txt",
                "kind": "execution_log",
                "media_type": "text/plain",
                "content": stderr + "\n",
            }
        )

    return files


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
