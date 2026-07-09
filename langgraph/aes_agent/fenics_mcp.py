from __future__ import annotations

import logging
import json
import os
import re
from typing import Any, Dict, List, Protocol

from aes_agent.state import AgentState


FENICS_TOOL_NAME = "fenics_forward_solve"
FENICS_PROVIDER = "mcp:dolfinx"
DEFAULT_DOLFINX_MCP_URL = ""
logger = logging.getLogger("aes_agent.fenics_mcp")

FENICS_ARTIFACT_TOOLS = {
    "export_solution": {
        "kind": "solution",
        "default_media_type": "application/x-xdmf",
    },
    "plot_solution": {
        "kind": "plot",
        "default_media_type": "image/png",
    },
    "generate_report": {
        "kind": "report",
        "default_media_type": "text/html",
    },
}

MCP_ERROR_MARKERS = (
    "DOLFINX_API_ERROR",
    "FILE_IO_ERROR",
    "FUNCTION_NOT_FOUND",
    "NO_ACTIVE_MESH",
    "VALIDATION_ERROR",
    "Permission denied",
    "Traceback",
)

ALLOWED_DOLFINX_TOOLS = {
    "reset_session",
    "create_unit_square",
    "create_mesh",
    "get_mesh_info",
    "create_function_space",
    "set_material_properties",
    "define_variational_form",
    "apply_boundary_condition",
    "create_function",
    "solve",
    "solve_time_dependent",
    "get_solver_diagnostics",
    "export_solution",
    "plot_solution",
    "generate_report",
    "list_workspace_files",
    "bundle_workspace_files",
}


class MCPToolClient(Protocol):
    def list_tools(self) -> List[Dict[str, Any]]:
        ...

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        ...


def build_fenics_recipe(state: AgentState) -> Dict[str, Any]:
    """
    Convert a validated AES state into a constrained DOLFINx/FEniCS recipe.

    This first version intentionally supports a narrow, safe subset:
    - forward Poisson/stationary diffusion on a unit square or rectangle,
    - forward heat equation on a unit square or rectangle,
    - scalar Lagrange P1 spaces,
    - Dirichlet boundary conditions.
    """

    errors: List[str] = []
    assumptions: List[str] = []
    problem_type = _detect_problem_type(state)

    if problem_type == "unsupported":
        errors.append(
            "The first FEniCS MCP workflow supports only forward Poisson, "
            "stationary diffusion, or heat-equation problems."
        )

    domain = _build_domain_spec(state, errors, assumptions)
    boundary_conditions = _build_boundary_conditions(state, errors, assumptions)
    coefficient = _extract_coefficient(state, assumptions)
    source = _extract_source(state, problem_type, errors, assumptions)
    time_spec = _build_time_spec(state, problem_type, errors, assumptions)
    initial_condition = _extract_initial_condition(
        state,
        problem_type,
        errors,
    )

    if errors:
        return {
            "status": "invalid",
            "recipe": {},
            "errors": errors,
        }

    workflow_name = (
        "heat_equation_unit_domain_backward_euler_v1"
        if problem_type == "heat_equation"
        else "poisson_unit_domain_v1"
    )

    recipe = {
        "schema_version": "1.0",
        "provider": FENICS_PROVIDER,
        "workflow": workflow_name,
        "problem_type": problem_type,
        "domain": domain,
        "function_space": {
            "name": "V",
            "family": "Lagrange",
            "degree": 1,
        },
        "equation": {
            "diffusion_coefficient": coefficient,
            "source": source,
        },
        "boundary_conditions": boundary_conditions,
        "solver": _build_solver_spec(problem_type),
        "outputs": ["solution_xdmf", "plot_png", "diagnostics", "report"],
        "assumptions": assumptions,
    }

    if problem_type == "heat_equation":
        recipe["initial_condition"] = initial_condition
        recipe["time"] = time_spec

    return {
        "status": "ready",
        "recipe": recipe,
        "errors": [],
    }


def plan_dolfinx_mcp_calls(recipe: Dict[str, Any]) -> List[Dict[str, Any]]:
    problem_type = recipe.get("problem_type", "")
    domain = recipe.get("domain", {})
    function_space = recipe.get("function_space", {})
    equation = recipe.get("equation", {})
    boundary_conditions = recipe.get("boundary_conditions", [])
    solver = recipe.get("solver", {})

    calls: List[Dict[str, Any]] = [
        {
            "tool_name": "reset_session",
            "arguments": {},
        },
        _mesh_call(domain),
        {
            "tool_name": "create_function_space",
            "arguments": {
                "name": function_space.get("name", "V"),
                "family": function_space.get("family", "Lagrange"),
                "degree": function_space.get("degree", 1),
            },
        },
        {
            "tool_name": "set_material_properties",
            "arguments": {
                "name": "k",
                "value": equation.get("diffusion_coefficient", "1.0"),
            },
        },
        {
            "tool_name": "set_material_properties",
            "arguments": {
                "name": "f",
                "value": equation.get("source", "0.0"),
            },
        },
    ]

    if problem_type == "heat_equation":
        calls.extend(_heat_solver_calls(recipe, boundary_conditions, solver))
    else:
        calls.extend(_poisson_solver_calls(recipe, boundary_conditions, solver))

    for call in calls:
        tool_name = call["tool_name"]
        if tool_name not in ALLOWED_DOLFINX_TOOLS:
            raise ValueError(f"Blocked non-allowlisted DOLFINx MCP tool: {tool_name}")

    return calls


def execute_fenics_forward_solve(
    state: AgentState,
    *,
    client: MCPToolClient | None = None,
    execute: bool | None = None,
) -> Dict[str, Any]:
    recipe = state.get("numerical_recipe") or {}
    recipe_errors = state.get("numerical_recipe_errors", [])
    if not recipe:
        recipe_result = build_fenics_recipe(state)
        recipe = recipe_result["recipe"]
        recipe_errors = recipe_result["errors"]

    if not recipe:
        mcp_calls: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        warnings: List[str] = []
        return {
            "schema_version": "1.0",
            "provider": FENICS_PROVIDER,
            "execution_mode": "blocked",
            "recipe": {},
            "mcp_calls": mcp_calls,
            "results": results,
            "fenics_result": _build_fenics_result_contract(
                execution_mode="blocked",
                endpoint="",
                recipe={},
                calls=mcp_calls,
                results=results,
                errors=recipe_errors,
                warnings=warnings,
            ),
            "errors": recipe_errors,
        }

    calls = plan_dolfinx_mcp_calls(recipe)
    should_execute = _should_execute_live() if execute is None else execute
    if client is None and should_execute:
        client = _default_dolfinx_client()

    if client is None:
        results = []
        errors: List[str] = []
        warnings: List[str] = []
        return {
            "schema_version": "1.0",
            "provider": FENICS_PROVIDER,
            "execution_mode": "planned",
            "recipe": recipe,
            "mcp_calls": calls,
            "results": results,
            "fenics_result": _build_fenics_result_contract(
                execution_mode="planned",
                endpoint="",
                recipe=recipe,
                calls=calls,
                results=results,
                errors=errors,
                warnings=warnings,
            ),
            "errors": [],
            "message": (
                "DOLFINx MCP execution is not enabled. Set DOLFINX_MCP_URL "
                "and DOLFINX_MCP_EXECUTE=true to execute this workflow."
            ),
        }

    endpoint = _client_endpoint(client)
    logger.info(
        "Executing DOLFINx MCP workflow: endpoint=%s calls=%s workflow=%s",
        endpoint or "unknown",
        len(calls),
        recipe.get("workflow", ""),
    )
    available_tools = {
        tool.get("name")
        for tool in client.list_tools()
        if isinstance(tool, dict)
    }
    missing_tools = [
        call["tool_name"]
        for call in calls
        if call["tool_name"] not in available_tools
    ]
    if missing_tools:
        raise RuntimeError(
            "The DOLFINx MCP server is missing required tools: "
            + ", ".join(missing_tools)
        )

    results = []
    empty_result_tools = []
    errors = []
    warnings = []
    failed_tool = ""
    for index, call in enumerate(calls, start=1):
        tool_name = call["tool_name"]
        logger.info(
            "Calling DOLFINx MCP tool %s/%s: %s",
            index,
            len(calls),
            tool_name,
        )
        tool_result = client.call_tool(tool_name, call["arguments"])
        if not tool_result:
            empty_result_tools.append(tool_name)
        results.append(
            {
                "tool_name": tool_name,
                "result": tool_result,
            }
        )
        tool_error = _extract_mcp_tool_error(tool_name, tool_result)
        if tool_error:
            errors.append(tool_error)
            failed_tool = tool_name
            warnings.append(
                f"Stopped DOLFINx MCP workflow after `{tool_name}` returned an error."
            )
            logger.warning("DOLFINx MCP tool failed: %s", tool_error)
            break

    non_empty_result_count = len(results) - len(empty_result_tools)
    execution_mode = "executed"
    if errors:
        execution_mode = "failed"
    elif results and non_empty_result_count == 0:
        execution_mode = "executed_unverified"
        warnings.append(
            "All MCP tool calls returned empty result objects. AES reached the "
            "MCP client path, but the provider response does not prove that "
            "solver-side artifacts were produced."
        )

    return {
        "schema_version": "1.0",
        "provider": FENICS_PROVIDER,
        "execution_mode": execution_mode,
        "mcp_endpoint": endpoint,
        "recipe": recipe,
        "mcp_calls": calls,
        "results": results,
        "executed_call_count": len(results),
        "non_empty_result_count": non_empty_result_count,
        "empty_result_tools": empty_result_tools,
        "warnings": warnings,
        "failed_tool": failed_tool,
        "fenics_result": _build_fenics_result_contract(
            execution_mode=execution_mode,
            endpoint=endpoint,
            recipe=recipe,
            calls=calls,
            results=results,
            errors=errors,
            warnings=warnings,
        ),
        "errors": errors,
    }


def _default_dolfinx_client() -> MCPToolClient:
    from aes_agent.mcp_client import StreamableHTTPMCPClient

    url = os.getenv("DOLFINX_MCP_URL", DEFAULT_DOLFINX_MCP_URL).strip()
    if not url:
        raise RuntimeError("DOLFINX_MCP_URL is required for live FEniCS execution.")

    timeout = int(os.getenv("DOLFINX_MCP_TIMEOUT", "120"))
    protocol_version = os.getenv("DOLFINX_MCP_PROTOCOL", "2025-06-18")
    return StreamableHTTPMCPClient(
        url,
        timeout=timeout,
        protocol_version=protocol_version,
    )


def _should_execute_live() -> bool:
    value = os.getenv("DOLFINX_MCP_EXECUTE", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _client_endpoint(client: MCPToolClient) -> str:
    endpoint = getattr(client, "endpoint", "")
    return endpoint if isinstance(endpoint, str) else ""


def _build_fenics_result_contract(
    *,
    execution_mode: str,
    endpoint: str,
    recipe: Dict[str, Any],
    calls: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "provider": FENICS_PROVIDER,
        "status": _fenics_status_from_execution_mode(execution_mode),
        "execution_mode": execution_mode,
        "workflow": recipe.get("workflow", ""),
        "problem_type": recipe.get("problem_type", ""),
        "mcp_endpoint": endpoint,
        "mcp": {
            "planned_call_count": len(calls),
            "executed_call_count": len(results),
            "planned_tools": [
                call.get("tool_name", "")
                for call in calls
                if isinstance(call, dict)
            ],
            "executed_tools": [
                result.get("tool_name", "")
                for result in results
                if isinstance(result, dict)
            ],
        },
        "requested_artifacts": _requested_artifacts_from_calls(calls),
        "artifacts": _available_artifacts_from_results(calls, results),
        "diagnostics": _diagnostics_from_results(results),
        "errors": errors,
        "warnings": warnings,
    }


def _fenics_status_from_execution_mode(execution_mode: str) -> str:
    if execution_mode == "executed":
        return "completed"
    if execution_mode == "executed_unverified":
        return "unverified"
    if execution_mode == "planned":
        return "planned"
    if execution_mode in {"blocked", "failed"}:
        return "failed"
    return "unknown"


def _requested_artifacts_from_calls(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    artifacts = []
    for call in calls:
        artifact = _artifact_ref_from_call(call, status="requested")
        if artifact:
            artifacts.append(artifact)
    return artifacts


def _available_artifacts_from_results(
    calls: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    artifacts = []
    for index, result_entry in enumerate(results):
        if not isinstance(result_entry, dict):
            continue
        call = calls[index] if index < len(calls) else {}
        tool_name = result_entry.get("tool_name", "")
        result = result_entry.get("result") or {}
        if not isinstance(result, dict):
            continue
        if _extract_mcp_tool_error(str(tool_name), result):
            continue
        artifact = _artifact_ref_from_call(call, status="available")
        if artifact:
            artifact["source_result_index"] = index
            artifacts.append(artifact)
    return artifacts


def _artifact_ref_from_call(
    call: Dict[str, Any],
    *,
    status: str,
) -> Dict[str, Any]:
    if not isinstance(call, dict):
        return {}

    tool_name = call.get("tool_name", "")
    spec = FENICS_ARTIFACT_TOOLS.get(str(tool_name))
    if not spec:
        return {}

    arguments = call.get("arguments") or {}
    if not isinstance(arguments, dict):
        return {}

    filename = str(arguments.get("filename", "")).strip()
    if not filename:
        return {}

    return {
        "name": filename,
        "kind": spec["kind"],
        "status": status,
        "uri": f"mcp://dolfinx/workspace/{filename}",
        "storage": "provider_workspace",
        "media_type": _artifact_media_type(filename, spec["default_media_type"]),
        "producer": {
            "provider": FENICS_PROVIDER,
            "tool_name": str(tool_name),
        },
        "metadata": {
            "format": str(arguments.get("format", "")),
        },
    }


def _artifact_media_type(filename: str, default: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".html") or lowered.endswith(".htm"):
        return "text/html"
    if lowered.endswith(".xdmf"):
        return "application/x-xdmf"
    if lowered.endswith(".json"):
        return "application/json"
    return default


def _diagnostics_from_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    for result_entry in results:
        if not isinstance(result_entry, dict):
            continue
        if result_entry.get("tool_name") != "get_solver_diagnostics":
            continue
        result = result_entry.get("result") or {}
        if isinstance(result, dict) and not _extract_mcp_tool_error(
            "get_solver_diagnostics",
            result,
        ):
            return result
    return {}


def _detect_problem_type(state: AgentState) -> str:
    text = _all_state_text(state)
    is_stationary_heat = (
        "heat" in text
        and any(marker in text for marker in ["steady", "stationary", "steady-state", "steady state"])
    )
    if "poisson" in text or "stationary_diffusion" in text or is_stationary_heat:
        return "poisson_equation"
    if "heat" in text or "time_dependent_heat" in text:
        return "heat_equation"
    return "unsupported"


def _build_domain_spec(
    state: AgentState,
    errors: List[str],
    assumptions: List[str],
) -> Dict[str, Any]:
    text = _all_state_text(state)

    if "unit_square" in text or "unit square" in text or "[0,1]x[0,1]" in text:
        return {
            "name": "mesh",
            "type": "unit_square",
            "nx": 32,
            "ny": 32,
            "cell_type": "triangle",
        }

    if "rectangle" in text or "rectangular" in text:
        assumptions.append(
            "Using a unit rectangle [0,1] x [0,1] because explicit rectangle "
            "bounds were not extracted."
        )
        return {
            "name": "mesh",
            "type": "rectangle",
            "x0": 0.0,
            "x1": 1.0,
            "y0": 0.0,
            "y1": 1.0,
            "nx": 32,
            "ny": 32,
            "cell_type": "triangle",
        }

    errors.append(
        "A supported 2D domain is required for the first FEniCS workflow "
        "(unit square or rectangle)."
    )
    return {}


def _build_boundary_conditions(
    state: AgentState,
    errors: List[str],
    assumptions: List[str],
) -> List[Dict[str, Any]]:
    text = _all_state_text(state)
    raw_text = state.get("raw_user_input", "")
    bc_info = state.get("bc_info", "")

    if "dirichlet" not in text and "u=0" not in text.replace(" ", ""):
        errors.append(
            "The first FEniCS workflow currently supports Dirichlet boundary "
            "conditions only."
        )
        return []

    value = _extract_boundary_value(raw_text)
    if value is None and "zero dirichlet" in text:
        value = "0.0"

    if value is None and "dirichlet" in bc_info.lower():
        value = "0.0"
        assumptions.append(
            "Using homogeneous Dirichlet value 0.0 because no explicit "
            "boundary value was extracted."
        )

    if value is None:
        errors.append("A Dirichlet boundary value is required for FEniCS setup.")
        return []

    return [
        {
            "name": "bc_boundary",
            "type": "dirichlet",
            "where": "boundary",
            "value": value,
        }
    ]


def _extract_coefficient(
    state: AgentState,
    assumptions: List[str],
) -> str:
    raw_text = state.get("raw_user_input", "")
    coefficient_info = state.get("coefficient_info", "")

    expression = _expression_from_info(coefficient_info)
    if expression:
        return expression

    expression = _extract_expression(
        raw_text,
        [
            r"\bk\s*(?:=|is)\s*([^,.;\n]+)",
            r"diffusion coefficient\s*(?:=|is)\s*([^,.;\n]+)",
            r"coefficient\s*(?:=|is)\s*([^,.;\n]+)",
        ],
    )
    if expression:
        return expression

    assumptions.append("Using diffusion coefficient 1.0.")
    return "1.0"


def _extract_source(
    state: AgentState,
    problem_type: str,
    errors: List[str],
    assumptions: List[str],
) -> str:
    raw_text = state.get("raw_user_input", "")
    source_info = state.get("source_info", "")

    expression = _expression_from_info(source_info)
    if expression:
        return expression

    expression = _extract_expression(
        raw_text,
        [
            r"\bf\s*(?:=|is)\s*([^,.;\n]+)",
            r"source term\s*(?:=|is)\s*([^,.;\n]+)",
            r"source\s*(?:=|is)\s*([^,.;\n]+)",
            r"right-hand side\s*(?:=|is)\s*([^,.;\n]+)",
        ],
    )
    if expression:
        return expression

    if problem_type == "heat_equation":
        assumptions.append("Using zero source term for heat equation.")
        return "0.0"

    errors.append("A source/right-hand-side expression is required for Poisson.")
    return ""


def _extract_initial_condition(
    state: AgentState,
    problem_type: str,
    errors: List[str],
) -> str:
    if problem_type != "heat_equation":
        return ""

    raw_text = state.get("raw_user_input", "")
    initial_condition_info = state.get("initial_condition_info", "")

    expression = _expression_from_info(initial_condition_info)
    if expression:
        return expression

    expression = _extract_expression(
        raw_text,
        [
            r"u\s*\([^)]*,\s*0\s*\)\s*=\s*([^,.;\n]+)",
            r"initial condition\s*(?:=|is)\s*([^,.;\n]+)",
            r"\bu_?0\s*(?:=|is)\s*([^,.;\n]+)",
        ],
    )
    if expression:
        return expression

    errors.append("An initial condition is required for the heat-equation workflow.")
    return ""


def _build_time_spec(
    state: AgentState,
    problem_type: str,
    errors: List[str],
    assumptions: List[str],
) -> Dict[str, Any]:
    if problem_type != "heat_equation":
        return {}

    text = f"{state.get('raw_user_input', '')} {state.get('time_info', '')}"
    t_end = _extract_number(
        text,
        [
            r"\bt_end\s*=\s*([0-9]*\.?[0-9]+)",
            r"\bT\s*=\s*([0-9]*\.?[0-9]+)",
            r"until\s+t\s*=\s*([0-9]*\.?[0-9]+)",
        ],
    )
    dt = _extract_number(
        text,
        [
            r"\bdt\s*=\s*([0-9]*\.?[0-9]+)",
            r"time step\s*(?:=|is)\s*([0-9]*\.?[0-9]+)",
        ],
    )

    if t_end is None:
        t_end = 1.0
        assumptions.append("Using final time T=1.0.")
    if dt is None:
        dt = 0.01
        assumptions.append("Using time step dt=0.01.")
    if dt <= 0 or t_end <= 0:
        errors.append("Heat-equation time settings require positive T and dt.")

    return {
        "t0": 0.0,
        "t_end": t_end,
        "dt": dt,
        "scheme": "backward_euler",
    }


def _build_solver_spec(problem_type: str) -> Dict[str, Any]:
    if problem_type == "heat_equation":
        return {
            "type": "time_dependent",
            "linear_solver": "cg",
            "preconditioner": "hypre_amg",
        }
    return {
        "type": "linear",
        "solver_type": "cg",
        "preconditioner": "hypre_amg",
    }


def _mesh_call(domain: Dict[str, Any]) -> Dict[str, Any]:
    if domain.get("type") == "unit_square":
        return {
            "tool_name": "create_unit_square",
            "arguments": {
                "name": domain.get("name", "mesh"),
                "nx": domain.get("nx", 32),
                "ny": domain.get("ny", 32),
                "cell_type": domain.get("cell_type", "triangle"),
            },
        }

    return {
        "tool_name": "create_mesh",
        "arguments": {
            "name": domain.get("name", "mesh"),
            "domain_type": "rectangle",
            "bounds": [
                domain.get("x0", 0.0),
                domain.get("x1", 1.0),
                domain.get("y0", 0.0),
                domain.get("y1", 1.0),
            ],
            "resolution": [domain.get("nx", 32), domain.get("ny", 32)],
            "cell_type": domain.get("cell_type", "triangle"),
        },
    }


def _poisson_solver_calls(
    recipe: Dict[str, Any],
    boundary_conditions: List[Dict[str, Any]],
    solver: Dict[str, Any],
) -> List[Dict[str, Any]]:
    calls = [
        {
            "tool_name": "define_variational_form",
            "arguments": {
                "name": "poisson_form",
                "function_space": "V",
                "space_name": "V",
                "bilinear": "k * dot(grad(u), grad(v)) * dx",
                "linear": "f * v * dx",
                "bilinear_form": "k * dot(grad(u), grad(v)) * dx",
                "linear_form": "f * v * dx",
            },
        },
    ]
    calls.extend(_boundary_condition_calls(boundary_conditions))
    calls.extend(
        [
            {
                "tool_name": "solve",
                "arguments": {
                    "form_name": "poisson_form",
                    "solution_name": "u",
                    "solver_type": solver.get("solver_type", "cg"),
                    "preconditioner": solver.get("preconditioner", "hypre_amg"),
                },
            },
            *_postprocess_calls("u", "poisson"),
        ]
    )
    return calls


def _heat_solver_calls(
    recipe: Dict[str, Any],
    boundary_conditions: List[Dict[str, Any]],
    solver: Dict[str, Any],
) -> List[Dict[str, Any]]:
    time_spec = recipe.get("time", {})
    calls = [
        {
            "tool_name": "create_function",
            "arguments": {
                "name": "u_n",
                "function_space": "V",
                "space_name": "V",
                "expression": _to_dolfinx_expression(
                    recipe.get("initial_condition", "0.0"),
                ),
            },
        },
        {
            "tool_name": "define_variational_form",
            "arguments": {
                "name": "heat_form",
                "function_space": "V",
                "space_name": "V",
                "bilinear": "u * v * dx + dt * k * dot(grad(u), grad(v)) * dx",
                "linear": "(u_n + dt * f) * v * dx",
                "bilinear_form": "u * v * dx + dt * k * dot(grad(u), grad(v)) * dx",
                "linear_form": "(u_n + dt * f) * v * dx",
                "parameters": {
                    "dt": time_spec.get("dt", 0.01),
                },
            },
        },
    ]
    calls.extend(_boundary_condition_calls(boundary_conditions))
    calls.extend(
        [
            {
                "tool_name": "solve_time_dependent",
                "arguments": {
                    "form_name": "heat_form",
                    "solution_name": "u",
                    "previous_solution_name": "u_n",
                    "t0": time_spec.get("t0", 0.0),
                    "t_end": time_spec.get("t_end", 1.0),
                    "dt": time_spec.get("dt", 0.01),
                    "scheme": time_spec.get("scheme", "backward_euler"),
                    "linear_solver": solver.get("linear_solver", "cg"),
                    "preconditioner": solver.get("preconditioner", "hypre_amg"),
                },
            },
            *_postprocess_calls("u", "heat"),
        ]
    )
    return calls


def _boundary_condition_calls(
    boundary_conditions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        {
            "tool_name": "apply_boundary_condition",
            "arguments": {
                "name": bc.get("name", "bc_boundary"),
                "function_space": "V",
                "space_name": "V",
                "type": bc.get("type", "dirichlet"),
                "value": bc.get("value", "0.0"),
                "boundary": bc.get("where", "boundary"),
                "locator": bc.get("where", "boundary"),
            },
        }
        for bc in boundary_conditions
    ]


def _extract_mcp_tool_error(tool_name: str, result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return f"{tool_name}: MCP tool returned a non-object result."

    explicit_error = result.get("error")
    if explicit_error:
        return f"{tool_name}: {_stringify_mcp_value(explicit_error)}"

    status = str(result.get("status", "")).strip().lower()
    if status in {"error", "failed", "failure"}:
        detail = _mcp_result_text(result) or status
        return f"{tool_name}: {detail}"

    content_text = _mcp_result_text(result)
    if result.get("isError") is True or result.get("is_error") is True:
        detail = content_text or "MCP tool returned isError=true."
        return f"{tool_name}: {detail}"

    if content_text and any(marker in content_text for marker in MCP_ERROR_MARKERS):
        return f"{tool_name}: {content_text}"

    return ""


def _mcp_result_text(result: Dict[str, Any]) -> str:
    parts: List[str] = []

    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                for key in ("text", "message", "detail", "data"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
                        break
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())

    for key in ("message", "detail", "details", "stderr"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    return _truncate_mcp_text(" ".join(parts), limit=900)


def _stringify_mcp_value(value: Any) -> str:
    if isinstance(value, str):
        return _truncate_mcp_text(value, limit=900)
    try:
        return _truncate_mcp_text(json.dumps(value, sort_keys=True), limit=900)
    except TypeError:
        return _truncate_mcp_text(str(value), limit=900)


def _truncate_mcp_text(value: str, *, limit: int) -> str:
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _postprocess_calls(solution_name: str, prefix: str) -> List[Dict[str, Any]]:
    return [
        {
            "tool_name": "get_solver_diagnostics",
            "arguments": {},
        },
        {
            "tool_name": "export_solution",
            "arguments": {
                "function_name": solution_name,
                "filename": f"{prefix}_solution.xdmf",
                "format": "xdmf",
            },
        },
        {
            "tool_name": "plot_solution",
            "arguments": {
                "function_name": solution_name,
                "filename": f"{prefix}_solution.png",
            },
        },
        {
            "tool_name": "generate_report",
            "arguments": {
                "title": f"{prefix.title()} forward solve",
                "filename": f"{prefix}_report.html",
            },
        },
        {
            "tool_name": "list_workspace_files",
            "arguments": {
                "pattern": "*",
            },
        },
    ]


def _all_state_text(state: AgentState) -> str:
    fields = [
        "raw_user_input",
        "problem_class",
        "domain_info",
        "pde_info",
        "coefficient_info",
        "source_info",
        "bc_info",
        "initial_condition_info",
        "time_info",
        "selected_formulation",
    ]
    return " ".join(str(state.get(field, "")) for field in fields).lower()


def _expression_from_info(value: str) -> str:
    if not isinstance(value, str):
        return ""
    lowered = value.strip().lower()
    if not lowered or "unknown" in lowered:
        return ""
    if lowered.endswith("_given") or lowered.endswith("_condition"):
        return ""
    return _clean_expression(value)


def _extract_expression(text: str, patterns: List[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_expression(match.group(1))
    return ""


def _extract_boundary_value(text: str) -> str | None:
    compact = text.replace(" ", "")
    if "u=0" in compact:
        return "0.0"
    if "zero dirichlet" in text.lower():
        return "0.0"

    match = re.search(
        r"\bu\s*=\s*([^,.;\n]+?)\s+on\s+(?:the\s+)?boundary",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_expression(match.group(1))
    return None


def _extract_number(text: str, patterns: List[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _clean_expression(value: str) -> str:
    cleaned = value.strip().strip("`$ ")
    parts = re.split(
        r"\s+(?:and|with)\s+"
        r"(?:diffusion\s+coefficient|coefficient|alpha|boundary|initial|time|source|f\s*=|k\s*=)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    cleaned = parts[0].strip()
    cleaned = cleaned.replace("^", "**")
    return _normalize_math_expression(cleaned)


def _normalize_math_expression(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\bsin\(pi([xy])\)", r"sin(pi*\1)", cleaned)
    cleaned = re.sub(
        r"\bsin\(pi\*x\)\s*sin\(pi\*y\)",
        "sin(pi*x)*sin(pi*y)",
        cleaned,
    )
    return cleaned


def _to_dolfinx_expression(value: Any) -> str:
    expression = _normalize_math_expression(str(value))

    converted = expression
    protected_tokens = {
        "__AES_X0__": "x[0]",
        "__AES_X1__": "x[1]",
        "__AES_X2__": "x[2]",
    }
    for token, coordinate in protected_tokens.items():
        converted = re.sub(
            re.escape(coordinate),
            token,
            converted,
            flags=re.IGNORECASE,
        )

    converted = re.sub(r"\bx\b", "x[0]", converted)
    converted = re.sub(r"\by\b", "x[1]", converted)
    converted = re.sub(r"\bz\b", "x[2]", converted)

    for token, coordinate in protected_tokens.items():
        converted = converted.replace(token, coordinate)

    return converted
