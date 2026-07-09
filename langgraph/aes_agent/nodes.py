from __future__ import annotations

import re
from typing import Any, Dict

from aes_agent.helpers import ollama_json, safe_list_of_str, safe_str
from aes_agent.fenics_mcp import build_fenics_recipe
from aes_agent.prompts import (
    check_problem_completeness_prompt,
    classify_problem_prompt,
    extract_mathematical_structure_prompt,
    generate_clarification_prompt,
    select_formulation_prompt,
    select_tools_prompt,
    validate_formulation_prompt,
)
from aes_agent.state import AgentState
from aes_agent.tools import (
    execute_tool,
    list_available_tools,
    tool_catalog,
)


def ingest_problem(state: AgentState) -> Dict[str, Any]:
    """
    Normalize and store the raw user input.
    """
    raw_text = state.get("raw_user_input", "").strip()
    return {
        "raw_user_input": raw_text
    }


def classify_problem(state: AgentState) -> Dict[str, Any]:
    user_text = state.get("raw_user_input", "")
    fallback = _classify_problem_from_text(user_text)
    if not _is_unknown(fallback["problem_class"]) and not _is_unknown(fallback["pde_info"]):
        return fallback

    prompt = classify_problem_prompt(user_text)
    result = ollama_json(prompt)
    problem_class = safe_str(result.get("problem_class"), "unknown_problem")
    pde_info = safe_str(result.get("pde_info"), "unknown_pde")

    return {
        "problem_class": (
            fallback["problem_class"]
            if _is_unknown(problem_class)
            else problem_class
        ),
        "pde_info": fallback["pde_info"] if _is_unknown(pde_info) else pde_info,
    }


def extract_mathematical_structure(state: AgentState) -> Dict[str, Any]:
    user_text = state.get("raw_user_input", "")
    problem_class = state.get("problem_class", "")
    pde_info = state.get("pde_info", "")
    fallback = _extract_structure_from_text(user_text, pde_info)
    if _has_supported_structure(fallback, pde_info):
        return fallback

    prompt = extract_mathematical_structure_prompt(
        user_text=user_text,
        problem_class=problem_class,
        pde_info=pde_info,
    )
    result = ollama_json(prompt)

    return {
        "domain_info": _fallback_if_unknown(
            safe_str(result.get("domain_info"), "unknown_domain"),
            fallback["domain_info"],
        ),
        "coefficient_info": _fallback_if_unknown(
            safe_str(result.get("coefficient_info"), "unknown_coefficient"),
            fallback["coefficient_info"],
        ),
        "source_info": _fallback_if_unknown(
            safe_str(result.get("source_info"), "unknown_source"),
            fallback["source_info"],
        ),
        "bc_info": _fallback_if_unknown(
            safe_str(result.get("bc_info"), "unknown_boundary_condition"),
            fallback["bc_info"],
        ),
        "initial_condition_info": _fallback_if_unknown(
            safe_str(
            result.get("initial_condition_info"),
            "unknown_initial_condition",
            ),
            fallback["initial_condition_info"],
        ),
        "time_info": _fallback_if_unknown(
            safe_str(result.get("time_info"), "unknown_time"),
            fallback["time_info"],
        ),
    }


def check_problem_completeness(state: AgentState) -> Dict[str, Any]:
    user_text = state.get("raw_user_input", "")
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
    }

    prompt = check_problem_completeness_prompt(
        user_text=user_text,
        snapshot=snapshot,
    )
    deterministic_missing = _deterministic_missing_information(user_text, snapshot)
    if not deterministic_missing and _is_supported_forward_pde_state(snapshot):
        return {"missing_information": []}

    result = ollama_json(prompt)
    missing_information = safe_list_of_str(result.get("missing_information"))
    missing_information.extend(deterministic_missing)

    return {
        "missing_information": _dedupe(missing_information)
    }


def generate_clarification(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "raw_user_input": state.get("raw_user_input", ""),
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "missing_information": state.get("missing_information", []),
        "selected_formulation": state.get("selected_formulation", ""),
        "validation_errors": state.get("validation_errors", []),
        "numerical_recipe_errors": state.get("numerical_recipe_errors", []),
    }

    unresolved_issues = (
        state.get("missing_information", [])
        or state.get("validation_errors", [])
        or state.get("numerical_recipe_errors", [])
    )
    if unresolved_issues:
        return {
            "clarification_questions": [
                f"Please clarify: {issue}" for issue in unresolved_issues
            ],
            "generated_artifact": (
                "Additional information is required before the workflow can continue."
            ),
            "agent_status": "needs_clarification",
            "next_action": "request_clarification",
        }

    result = ollama_json(generate_clarification_prompt(snapshot))
    clarification_questions = safe_list_of_str(
        result.get("clarification_questions")
    )
    if not clarification_questions:
        clarification_questions = ["Please clarify the requested engineering problem."]

    return {
        "clarification_questions": clarification_questions,
        "generated_artifact": safe_str(
            result.get("generated_artifact"),
            "Additional information is required before the workflow can continue.",
        ),
        "agent_status": "needs_clarification",
        "next_action": "request_clarification",
    }


def select_formulation(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "missing_information": state.get("missing_information", []),
    }

    prompt = select_formulation_prompt(snapshot)
    if not snapshot["missing_information"] and _is_supported_forward_pde_state(state):
        selected_formulation = "fem_problem_setup"
    else:
        result = ollama_json(prompt)
        selected_formulation = safe_str(
            result.get("selected_formulation"),
            "unknown_formulation",
        )
        if _is_unknown(selected_formulation) and not snapshot["missing_information"]:
            if _is_supported_forward_pde_state(state):
                selected_formulation = "fem_problem_setup"

    return {
        "selected_formulation": selected_formulation
    }


def validate_formulation(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "selected_formulation": state.get("selected_formulation", ""),
    }

    deterministic_errors = _deterministic_validation_errors(state)
    if not deterministic_errors:
        return {
            "validation_status": "valid",
            "validation_errors": [],
        }

    result = ollama_json(validate_formulation_prompt(snapshot))
    validation_status = safe_str(
        result.get("validation_status"),
        "invalid",
    ).lower()
    validation_errors = safe_list_of_str(result.get("validation_errors"))

    if validation_status not in {"valid", "invalid"}:
        validation_status = "invalid"

    if validation_status == "invalid" and not deterministic_errors:
        validation_status = "valid"
        validation_errors = []

    if validation_status == "invalid" and not validation_errors:
        validation_errors = (
            deterministic_errors
            or ["The selected formulation could not be validated."]
        )
    if validation_status == "valid":
        validation_errors = []

    return {
        "validation_status": validation_status,
        "validation_errors": validation_errors,
    }


def prepare_numerical_recipe(state: AgentState) -> Dict[str, Any]:
    recipe_result = build_fenics_recipe(state)

    return {
        "numerical_recipe_status": recipe_result["status"],
        "numerical_recipe": recipe_result["recipe"],
        "numerical_recipe_errors": recipe_result["errors"],
    }


def select_tools(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "missing_information": state.get("missing_information", []),
        "selected_formulation": state.get("selected_formulation", ""),
        "numerical_recipe_status": state.get("numerical_recipe_status", ""),
        "numerical_recipe": state.get("numerical_recipe", {}),
    }

    available_tools = list_available_tools()
    if (
        state.get("numerical_recipe_status") == "ready"
        and "fenics_forward_solve" in available_tools
    ):
        return {
            "selected_tools": ["fenics_forward_solve"]
        }

    prompt = select_tools_prompt(snapshot, tool_catalog())
    result = ollama_json(prompt)
    requested_tools = safe_list_of_str(result.get("selected_tools"))
    selected_tools = [
        tool_name
        for tool_name in dict.fromkeys(requested_tools)
        if tool_name in available_tools
    ]
    if (
        state.get("numerical_recipe_status") == "ready"
        and "fenics_forward_solve" in available_tools
        and "fenics_forward_solve" not in selected_tools
    ):
        selected_tools.append("fenics_forward_solve")
    if not selected_tools:
        selected_tools = available_tools

    return {
        "selected_tools": selected_tools
    }


def execute_tools(state: AgentState) -> Dict[str, Any]:
    tool_results = [
        execute_tool(tool_name, state)
        for tool_name in state.get("selected_tools", [])
    ]
    tool_errors = [
        f"{result['tool_name']}: {result['error']}"
        for result in tool_results
        if result["status"] == "failed"
    ]

    if not tool_results:
        tool_execution_status = "skipped"
    elif tool_errors:
        tool_execution_status = "failed"
    else:
        tool_execution_status = "completed"

    return {
        "tool_execution_status": tool_execution_status,
        "tool_results": tool_results,
        "tool_errors": tool_errors,
    }


def generate_artifact(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "raw_user_input": state.get("raw_user_input", ""),
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "missing_information": state.get("missing_information", []),
        "selected_formulation": state.get("selected_formulation", ""),
        "validation_status": state.get("validation_status", ""),
        "validation_errors": state.get("validation_errors", []),
        "numerical_recipe_status": state.get("numerical_recipe_status", ""),
        "numerical_recipe": state.get("numerical_recipe", {}),
        "numerical_recipe_errors": state.get("numerical_recipe_errors", []),
        "selected_tools": state.get("selected_tools", []),
        "tool_execution_status": state.get("tool_execution_status", ""),
        "tool_results": state.get("tool_results", []),
        "tool_errors": state.get("tool_errors", []),
    }

    if state.get("tool_execution_status") == "failed":
        agent_status = "tool_error"
        next_action = "review_tool_errors"
    else:
        agent_status = "ok"
        next_action = "review_tool_results"

    return {
        "generated_artifact": _build_generated_artifact(
            snapshot,
            agent_status,
            next_action,
        ),
        "agent_status": agent_status,
        "next_action": next_action,
    }


def _build_generated_artifact(
    snapshot: dict[str, Any],
    agent_status: str,
    next_action: str,
) -> str:
    lines = [
        "AES workflow result",
        "",
        f"Status: {agent_status}",
        f"Next action: {next_action}",
        "",
        "Problem interpretation:",
        f"- Class: {_artifact_value(snapshot.get('problem_class'))}",
        f"- PDE: {_artifact_value(snapshot.get('pde_info'))}",
        f"- Domain: {_artifact_value(snapshot.get('domain_info'))}",
        f"- Coefficients: {_artifact_value(snapshot.get('coefficient_info'))}",
        f"- Source: {_artifact_value(snapshot.get('source_info'))}",
        f"- Boundary conditions: {_artifact_value(snapshot.get('bc_info'))}",
        f"- Initial condition: {_artifact_value(snapshot.get('initial_condition_info'))}",
        f"- Time: {_artifact_value(snapshot.get('time_info'))}",
        "",
        "Formulation and validation:",
        f"- Selected formulation: {_artifact_value(snapshot.get('selected_formulation'))}",
        f"- Validation status: {_artifact_value(snapshot.get('validation_status'))}",
        f"- Numerical recipe status: {_artifact_value(snapshot.get('numerical_recipe_status'))}",
    ]

    _append_issue_section(lines, "Missing information", snapshot.get("missing_information"))
    _append_issue_section(lines, "Validation errors", snapshot.get("validation_errors"))
    _append_issue_section(
        lines,
        "Numerical recipe errors",
        snapshot.get("numerical_recipe_errors"),
    )

    recipe = snapshot.get("numerical_recipe") or {}
    if isinstance(recipe, dict) and recipe:
        _append_recipe_section(lines, recipe)

    selected_tools = snapshot.get("selected_tools") or []
    if selected_tools:
        lines.extend(
            [
                "",
                f"Selected tools: {_artifact_list(selected_tools)}",
            ]
        )

    tool_results = snapshot.get("tool_results") or []
    lines.extend(
        [
            "",
            f"Tool execution status: {_artifact_value(snapshot.get('tool_execution_status'))}",
        ]
    )
    if tool_results:
        _append_tool_result_section(lines, tool_results)

    _append_issue_section(lines, "Tool errors", snapshot.get("tool_errors"))

    return "\n".join(lines).strip()


def _append_recipe_section(lines: list[str], recipe: dict[str, Any]) -> None:
    domain = recipe.get("domain") if isinstance(recipe.get("domain"), dict) else {}
    equation = recipe.get("equation") if isinstance(recipe.get("equation"), dict) else {}
    solver = recipe.get("solver") if isinstance(recipe.get("solver"), dict) else {}

    lines.extend(
        [
            "",
            "Numerical recipe:",
            f"- Provider: {_artifact_value(recipe.get('provider'))}",
            f"- Workflow: {_artifact_value(recipe.get('workflow'))}",
            f"- Problem type: {_artifact_value(recipe.get('problem_type'))}",
            f"- Domain type: {_artifact_value(domain.get('type'))}",
            f"- Mesh resolution: {_mesh_resolution(domain)}",
            f"- Diffusion coefficient: {_artifact_value(equation.get('diffusion_coefficient'))}",
            f"- Source: {_artifact_value(equation.get('source'))}",
            f"- Solver: {_artifact_value(solver.get('type') or solver.get('solver_type'))}",
        ]
    )

    assumptions = recipe.get("assumptions") or []
    if assumptions:
        lines.append(f"- Assumptions: {_artifact_list(assumptions)}")


def _append_tool_result_section(
    lines: list[str],
    tool_results: list[dict[str, Any]],
) -> None:
    lines.append("Tool results:")
    for result in tool_results:
        if not isinstance(result, dict):
            continue

        tool_name = _artifact_value(result.get("tool_name"))
        status = _artifact_value(result.get("status"))
        provider = _artifact_value(result.get("provider"))
        lines.append(f"- {tool_name}: {status} ({provider})")

        error = result.get("error")
        if error:
            lines.append(f"  Error: {_artifact_value(error)}")

        output = result.get("output") or {}
        if not isinstance(output, dict):
            continue

        execution_mode = output.get("execution_mode")
        if execution_mode:
            lines.append(f"  Execution mode: {_artifact_value(execution_mode)}")

        message = output.get("message")
        if message:
            lines.append(f"  Message: {_artifact_value(message, limit=320)}")

        calls = output.get("mcp_calls") or []
        call_names = [
            _artifact_value(call.get("tool_name"), limit=60)
            for call in calls
            if isinstance(call, dict) and call.get("tool_name")
        ]
        if call_names:
            lines.append(f"  MCP calls: {_artifact_list(call_names, limit=400)}")

        results = output.get("results") or []
        if results:
            lines.append(f"  MCP result count: {len(results)}")


def _append_issue_section(
    lines: list[str],
    title: str,
    issues: Any,
) -> None:
    values = issues if isinstance(issues, list) else []
    if not values:
        return

    lines.extend(["", f"{title}:"])
    for issue in values[:10]:
        lines.append(f"- {_artifact_value(issue, limit=320)}")
    if len(values) > 10:
        lines.append(f"- ... {len(values) - 10} more")


def _mesh_resolution(domain: dict[str, Any]) -> str:
    nx = domain.get("nx")
    ny = domain.get("ny")
    if nx is not None and ny is not None:
        return f"{nx} x {ny}"

    resolution = domain.get("resolution")
    if isinstance(resolution, list) and resolution:
        return " x ".join(str(value) for value in resolution)

    return "not specified"


def _artifact_list(values: Any, *, limit: int = 240) -> str:
    if not isinstance(values, list):
        return "none"

    rendered = [
        _artifact_value(value, limit=80)
        for value in values[:12]
        if _artifact_value(value, limit=80) != "none"
    ]
    if len(values) > 12:
        rendered.append(f"... {len(values) - 12} more")

    text = ", ".join(rendered) if rendered else "none"
    return _artifact_value(text, limit=limit)


def _artifact_value(value: Any, *, limit: int = 160) -> str:
    if value is None:
        return "none"

    if isinstance(value, (dict, list, tuple, set)):
        text = str(value)
    else:
        text = safe_str(value, "none")

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "none"
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _is_unknown(value: str) -> bool:
    lowered = str(value).strip().lower()
    return not lowered or lowered.startswith("unknown") or lowered in {
        "clarification_required",
        "none",
        "n/a",
    }


def _fallback_if_unknown(value: str, fallback: str) -> str:
    return fallback if _is_unknown(value) and fallback else value


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _lower_text(value: str) -> str:
    return value.replace("\\", "").lower()


def _has_any(text: str, needles: list[str]) -> bool:
    lowered = _lower_text(text)
    return any(needle in lowered for needle in needles)


def _has_time_derivative(text: str) -> bool:
    lowered = _lower_text(text)
    return any(
        token in lowered
        for token in [
            "partial u}{partial t",
            "partial u / partial t",
            "partial u/partial t",
            "∂u/∂t",
            "du/dt",
            "u_t",
            "time-dependent",
            "time dependent",
            "transient",
        ]
    )


def _has_stationary_marker(text: str) -> bool:
    return _has_any(
        text,
        ["steady", "stationary", "steady-state", "steady state"],
    )


def _classify_problem_from_text(user_text: str) -> dict[str, str]:
    problem_class = (
        "forward_problem"
        if _has_any(user_text, ["solve", "compute", "simulate", "find "])
        else "unknown_problem"
    )

    lowered = _lower_text(user_text)
    if (
        "poisson" in lowered
        or "stationary_diffusion" in lowered
        or (_has_stationary_marker(user_text) and "heat" in lowered)
    ):
        pde_info = "stationary_diffusion_equation"
    elif "heat" in lowered and _has_time_derivative(user_text):
        pde_info = "time_dependent_heat_equation"
    elif "heat" in lowered:
        pde_info = "time_dependent_heat_equation"
    else:
        pde_info = "unknown_pde"

    return {
        "problem_class": problem_class,
        "pde_info": pde_info,
    }


def _extract_structure_from_text(user_text: str, pde_info: str) -> dict[str, str]:
    lowered = _lower_text(user_text)
    source = _extract_expression_from_text(
        user_text,
        [
            r"\bf\s*(?:=|is)\s*([^,.;\n]+)",
            r"source\s+f\s*=\s*([^,.;\n]+)",
            r"source term\s*(?:=|is)\s*([^,.;\n]+)",
            r"source\s*(?:=|is)\s*([^,.;\n]+)",
            r"right-hand side\s*(?:=|is)\s*([^,.;\n]+)",
        ],
    )
    coefficient = _extract_expression_from_text(
        user_text,
        [
            r"\balpha\s*(?:=|is)\s*([^,.;\n]+)",
            r"\bk\s*(?:=|is)\s*([^,.;\n]+)",
            r"diffusion coefficient\s*(?:=|is)\s*([^,.;\n]+)",
            r"coefficient\s*(?:=|is)\s*([^,.;\n]+)",
        ],
    )
    initial_condition = _extract_expression_from_text(
        user_text,
        [
            r"u\s*\([^)]*,\s*0\s*\)\s*=\s*([^,.;\n]+)",
            r"initial condition\s*(?:=|is)\s*([^,.;\n]+)",
            r"\bu_?0\s*(?:=|is)\s*([^,.;\n]+)",
        ],
    )
    time_values = []
    for pattern in [r"\bT\s*=\s*([0-9]*\.?[0-9]+)", r"\bdt\s*=\s*([0-9]*\.?[0-9]+)"]:
        match = re.search(pattern, user_text, flags=re.IGNORECASE)
        if match:
            time_values.append(match.group(0))

    return {
        "domain_info": (
            "unit_square"
            if "unit square" in lowered or "[0,1]x[0,1]" in lowered
            else "rectangular_domain"
            if "rectangle" in lowered or "rectangular" in lowered
            else "unknown_domain"
        ),
        "coefficient_info": coefficient or "constant_coefficient_given",
        "source_info": source or "unknown_source",
        "bc_info": (
            "dirichlet_boundary_condition"
            if "dirichlet" in lowered or "u=0" in user_text.replace(" ", "")
            else "unknown_boundary_condition"
        ),
        "initial_condition_info": initial_condition or "unknown_initial_condition",
        "time_info": ", ".join(time_values) if time_values else "unknown_time",
    }


def _extract_expression_from_text(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_extracted_expression(match.group(1))
    return ""


def _clean_extracted_expression(value: str) -> str:
    cleaned = value.strip().strip("`$ ")
    parts = re.split(
        r"\s+(?:and|with)\s+"
        r"(?:diffusion\s+coefficient|coefficient|alpha|boundary|initial|time|source)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    return parts[0].strip()


def _state_text(state: dict[str, Any]) -> str:
    return " ".join(str(value) for value in state.values())


def _is_stationary_problem(state: dict[str, Any]) -> bool:
    text = _state_text(state)
    pde_info = str(state.get("pde_info", "")).lower()
    return (
        "stationary_diffusion" in pde_info
        or "poisson" in pde_info
        or (_has_stationary_marker(text) and "heat" in _lower_text(text))
    )


def _is_time_dependent_problem(state: dict[str, Any]) -> bool:
    text = _state_text(state)
    pde_info = str(state.get("pde_info", "")).lower()
    return "time_dependent_heat" in pde_info or _has_time_derivative(text)


def _deterministic_missing_information(
    user_text: str,
    snapshot: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    combined = f"{user_text} {_state_text(snapshot)}"

    if _has_stationary_marker(combined) and _has_time_derivative(combined):
        missing.append(
            "The request mixes a steady/stationary problem with a "
            "time-dependent formulation. Specify whether AES should solve the "
            "stationary equation or the transient heat equation."
        )

    if _is_unknown(str(snapshot.get("domain_info", ""))):
        missing.append("A supported domain is required, for example a unit square.")

    if _is_unknown(str(snapshot.get("bc_info", ""))):
        missing.append("A boundary condition is required.")

    if _is_stationary_problem(snapshot) and _is_unknown(str(snapshot.get("source_info", ""))):
        missing.append("A source/right-hand-side expression is required.")

    if _is_time_dependent_problem(snapshot):
        if _is_unknown(str(snapshot.get("initial_condition_info", ""))):
            missing.append("An initial condition is required for a transient heat equation.")
        if _is_unknown(str(snapshot.get("time_info", ""))):
            missing.append("A final time and time step are required for a transient heat equation.")

    return missing


def _is_supported_forward_pde_state(state: dict[str, Any]) -> bool:
    if str(state.get("problem_class", "")).lower() != "forward_problem":
        return False
    if not (_is_stationary_problem(state) or _is_time_dependent_problem(state)):
        return False
    if _is_unknown(str(state.get("domain_info", ""))):
        return False
    if _is_unknown(str(state.get("bc_info", ""))):
        return False
    return True


def _has_supported_structure(structure: dict[str, str], pde_info: str) -> bool:
    state = {"pde_info": pde_info, **structure}
    if not (_is_stationary_problem(state) or _is_time_dependent_problem(state)):
        return False
    if _is_unknown(str(structure.get("domain_info", ""))):
        return False
    if _is_unknown(str(structure.get("bc_info", ""))):
        return False
    return True


def _deterministic_validation_errors(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    selected_formulation = str(state.get("selected_formulation", "")).lower()
    supported_formulations = {
        "weak_formulation_candidate",
        "strong_formulation_summary",
        "fem_problem_setup",
    }

    if selected_formulation not in supported_formulations:
        errors.append("The selected formulation is not a supported formulation label.")

    if not _is_supported_forward_pde_state(state):
        errors.append(
            "The extracted problem is not yet a supported, sufficiently specified "
            "forward PDE problem."
        )

    if _has_stationary_marker(_state_text(state)) and _has_time_derivative(_state_text(state)):
        errors.append(
            "The formulation is inconsistent: the request is marked steady but "
            "also contains a time derivative."
        )

    return errors
