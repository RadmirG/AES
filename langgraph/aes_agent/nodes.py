from __future__ import annotations

import os
import re
from typing import Any, Dict

from aes_agent.fenics_code import build_fenics_code_recipe
from aes_agent.fenics_mcp import build_fenics_recipe
from aes_agent.helpers import ollama_json, safe_list_of_str, safe_str
from aes_agent.prompts import (
    check_problem_completeness_prompt,
    classify_problem_prompt,
    detect_request_intent_prompt,
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


def detect_request_intent(state: AgentState) -> Dict[str, Any]:
    user_text = state.get("raw_user_input", "")
    deterministic = _detect_request_intent_from_text(user_text)
    if deterministic["request_intent"] != "unknown_request":
        return deterministic

    result = ollama_json(detect_request_intent_prompt(user_text))
    request_intent = safe_str(
        result.get("request_intent"),
        "unsupported_request",
    )
    if request_intent not in {
        "engineering_pde_request",
        "operational_command",
        "general_question",
        "unsupported_request",
        "empty_request",
    }:
        request_intent = "unsupported_request"

    return {
        "request_intent": request_intent,
        "intent_reason": safe_str(
            result.get("intent_reason"),
            "The latest message is not a supported AES solver request.",
        ),
    }


def handle_non_engineering_request(state: AgentState) -> Dict[str, Any]:
    intent = state.get("request_intent", "unsupported_request")
    reason = state.get(
        "intent_reason",
        "The latest message is not a supported AES solver request.",
    )
    user_text = state.get("raw_user_input", "")

    if intent == "operational_command":
        message = (
            "This looks like an operational/deployment command, not a numerical "
            "engineering problem for AES to solve."
        )
        next_action = "ask_deployment_helper_or_send_pde_problem"
    elif intent == "general_question":
        message = (
            "This looks like a general conceptual question, not a concrete PDE "
            "solve request for the AES numerical workflow."
        )
        next_action = "ask_general_helper_or_send_pde_problem"
    elif intent == "empty_request":
        message = "No usable user request was provided."
        next_action = "send_engineering_problem"
    else:
        message = (
            "The latest message is outside the currently supported AES solver "
            "workflow."
        )
        next_action = "send_supported_pde_problem"

    generated_artifact = "\n".join(
        [
            "AES request gate",
            "",
            "Status: not_applicable",
            f"Intent: {intent}",
            f"Reason: {reason}",
            "",
            message,
            "",
            "AES will continue only for explicit engineering/PDE solve requests, "
            "for example: solve a stationary heat equation on a unit square with "
            "specified source, coefficient, and boundary conditions.",
        ]
    )

    if user_text:
        generated_artifact += (
            "\n\nLatest user message classified by AES:\n"
            f"{_artifact_value(user_text, limit=420)}"
        )

    return {
        "generated_artifact": generated_artifact,
        "agent_status": "not_applicable",
        "next_action": next_action,
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
    if state.get("solution_mode") == "needs_output_intent":
        questions = [
            (
                "What output do you want from AES: a formulation summary, a "
                "generated DOLFINx/FEniCS Python file, or execution with "
                "stored result artifacts?"
            )
        ]
        return {
            "clarification_questions": questions,
            "generated_artifact": _render_clarification_artifact(
                "The PDE problem is specified, but the requested output is not.",
                questions,
            ),
            "agent_status": "needs_clarification",
            "next_action": "select_requested_output",
        }

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
        questions = [
            f"Please clarify: {issue}" for issue in unresolved_issues
        ]
        return {
            "clarification_questions": questions,
            "generated_artifact": _render_clarification_artifact(
                "Additional information is required before the workflow can continue.",
                questions,
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
            _render_clarification_artifact(
                "Additional information is required before the workflow can continue.",
                clarification_questions,
            ),
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


def select_solution_mode(state: AgentState) -> Dict[str, Any]:
    configured = _configured_solution_mode()
    if configured:
        return {"solution_mode": configured}

    user_text = state.get("raw_user_input", "")

    if _looks_like_user_python_code(user_text):
        return {"solution_mode": "execute_user_fenics_code"}

    code_markers = [
        "python file",
        "python script",
        "fenics file",
        "fenics executable",
        "executable python",
        "source code",
        "code only",
        "as code",
        "solve.py",
    ]
    formulation_markers = [
        "formulation summary",
        "formulate",
        "derive the weak form",
        "derive weak form",
        "weak form only",
        "mathematical formulation",
        "fem formulation",
        "explain the formulation",
    ]
    execution_markers = [
        "solve",
        "execute",
        "run it",
        "run the",
        "compute",
        "compute result",
        "generate result",
        "plot",
        "xdmf",
        "simulation result",
    ]

    if _has_any(user_text, code_markers):
        mode = "generate_fenics_code"
    elif _has_any(user_text, formulation_markers):
        mode = "formulation_summary"
    elif _has_any(user_text, execution_markers):
        mode = "execute_generated_fenics_code"
    else:
        mode = "needs_output_intent"

    return {"solution_mode": mode}


def generate_formulation_summary(state: AgentState) -> Dict[str, Any]:
    lines = [
        "AES formulation summary",
        "",
        "Problem interpretation:",
        f"- Class: {_artifact_value(state.get('problem_class'))}",
        f"- PDE: {_artifact_value(state.get('pde_info'))}",
        f"- Domain: {_artifact_value(state.get('domain_info'))}",
        f"- Coefficients: {_artifact_value(state.get('coefficient_info'))}",
        f"- Source: {_artifact_value(state.get('source_info'))}",
        f"- Boundary conditions: {_artifact_value(state.get('bc_info'))}",
        f"- Initial condition: {_artifact_value(state.get('initial_condition_info'))}",
        f"- Time: {_artifact_value(state.get('time_info'))}",
        "",
        "Next available AES actions:",
        "- Generate a DOLFINx/FEniCS `solve.py` file.",
        "- Execute a generated or user-provided FEniCS script inside the provider container.",
        "- Use the deterministic MCP recipe path for known simple smoke-test workflows.",
    ]
    return {
        "solution_mode": "formulation_summary",
        "generated_artifact": "\n".join(lines),
        "agent_status": "ok",
        "next_action": "review_formulation_summary",
    }


def prepare_numerical_recipe(state: AgentState) -> Dict[str, Any]:
    if state.get("solution_mode") in {
        "generate_fenics_code",
        "execute_generated_fenics_code",
        "execute_user_fenics_code",
    }:
        return {
            "numerical_recipe_status": "ready",
            "numerical_recipe": build_fenics_code_recipe(state),
            "numerical_recipe_errors": [],
        }

    if state.get("solution_mode") == "needs_output_intent":
        return {
            "numerical_recipe_status": "needs_output_intent",
            "numerical_recipe": {},
            "numerical_recipe_errors": [
                "The requested output is not specified."
            ],
        }

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
        "solution_mode": state.get("solution_mode", ""),
        "numerical_recipe_status": state.get("numerical_recipe_status", ""),
        "numerical_recipe": state.get("numerical_recipe", {}),
    }

    available_tools = list_available_tools()
    if (
        state.get("numerical_recipe_status") == "ready"
        and (
            state.get("solution_mode") in {
                "generate_fenics_code",
                "execute_generated_fenics_code",
                "execute_user_fenics_code",
            }
            or (state.get("numerical_recipe") or {}).get("provider") == "local:fenics_code"
        )
        and "fenics_code_solve" in available_tools
    ):
        selected_tools = ["fenics_code_solve"]
        if "artifact_store" in available_tools:
            selected_tools.append("artifact_store")
        return {
            "selected_tools": selected_tools
        }

    if (
        state.get("numerical_recipe_status") == "ready"
        and "fenics_forward_solve" in available_tools
    ):
        selected_tools = ["fenics_forward_solve"]
        if "artifact_store" in available_tools:
            selected_tools.append("artifact_store")
        return {
            "selected_tools": selected_tools
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
    if (
        "fenics_forward_solve" in selected_tools
        and "artifact_store" in available_tools
        and "artifact_store" not in selected_tools
    ):
        selected_tools.append("artifact_store")
    if not selected_tools:
        selected_tools = available_tools

    return {
        "selected_tools": selected_tools
    }


def select_artifact_store(state: AgentState) -> Dict[str, Any]:
    available_tools = list_available_tools()
    return {
        "selected_tools": ["artifact_store"] if "artifact_store" in available_tools else []
    }


def execute_tools(state: AgentState) -> Dict[str, Any]:
    tool_results = []
    working_state = dict(state)
    for tool_name in state.get("selected_tools", []):
        working_state["tool_results"] = tool_results
        result = execute_tool(tool_name, working_state)
        tool_results.append(result)
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
        "solution_mode": state.get("solution_mode", ""),
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
    elif state.get("agent_status") in {
        "needs_clarification",
        "not_applicable",
    }:
        agent_status = state.get("agent_status", "")
        next_action = state.get("next_action", "")
    else:
        agent_status = "ok"
        next_action = state.get("next_action") or "review_tool_results"

    if (
        state.get("generated_artifact")
        and (
            agent_status in {"needs_clarification", "not_applicable"}
            or state.get("solution_mode") == "formulation_summary"
        )
    ):
        generated_artifact = _append_terminal_artifact_summary(
            state.get("generated_artifact", ""),
            state.get("tool_results", []),
        )
    else:
        generated_artifact = _build_generated_artifact(
            snapshot,
            agent_status,
            next_action,
        )

    return {
        "generated_artifact": generated_artifact,
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
        f"- Solution mode: {_artifact_value(snapshot.get('solution_mode'))}",
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

        generated_file_names = output.get("generated_file_names") or []
        if generated_file_names:
            lines.append(
                f"  Generated files: {_artifact_list(generated_file_names, limit=320)}"
            )

        safety_status = output.get("safety_status")
        if safety_status:
            lines.append(f"  Safety status: {_artifact_value(safety_status)}")

        endpoint = output.get("mcp_endpoint")
        if endpoint:
            lines.append(f"  MCP endpoint: {_artifact_value(endpoint)}")

        message = output.get("message")
        if message:
            lines.append(f"  Message: {_artifact_value(message, limit=320)}")

        manifest = output.get("manifest")
        if isinstance(manifest, dict):
            artifact_count = len(manifest.get("artifacts") or [])
            lines.append(f"  Artifact run: {_artifact_value(manifest.get('run_id'))}")
            lines.append(f"  Artifact manifest status: {_artifact_value(manifest.get('status'))}")
            lines.append(f"  Artifact reference count: {_artifact_value(artifact_count)}")

        manifest_path = output.get("manifest_path")
        if manifest_path:
            lines.append(f"  Manifest path: {_artifact_value(manifest_path, limit=320)}")

        summary_path = output.get("summary_path")
        if summary_path:
            lines.append(f"  Summary path: {_artifact_value(summary_path, limit=320)}")

        executed_call_count = output.get("executed_call_count")
        if executed_call_count is not None:
            lines.append(f"  Executed MCP calls: {_artifact_value(executed_call_count)}")

        non_empty_result_count = output.get("non_empty_result_count")
        if non_empty_result_count is not None:
            lines.append(
                f"  Non-empty MCP results: {_artifact_value(non_empty_result_count)}"
            )

        warnings = output.get("warnings") or []
        if warnings:
            lines.append(f"  Warnings: {_artifact_list(warnings, limit=480)}")

        failed_tool = output.get("failed_tool")
        if failed_tool:
            lines.append(f"  Failed MCP tool: {_artifact_value(failed_tool)}")

        output_errors = output.get("errors") or []
        if output_errors:
            lines.append(f"  Output errors: {_artifact_list(output_errors, limit=480)}")

        results = output.get("results") or []
        result_names = [
            _artifact_value(item.get("tool_name"), limit=60)
            for item in results
            if isinstance(item, dict) and item.get("tool_name")
        ]
        if result_names:
            lines.append(f"  Executed MCP result tools: {_artifact_list(result_names, limit=400)}")

        calls = output.get("mcp_calls") or []
        call_names = [
            _artifact_value(call.get("tool_name"), limit=60)
            for call in calls
            if isinstance(call, dict) and call.get("tool_name")
        ]
        if call_names:
            lines.append(f"  MCP calls: {_artifact_list(call_names, limit=400)}")

        if results:
            lines.append(f"  MCP result count: {len(results)}")


def _append_terminal_artifact_summary(
    base_artifact: str,
    tool_results: list[dict[str, Any]],
) -> str:
    lines = [base_artifact.strip()]
    if tool_results:
        lines.extend(["", "Artifact storage:"])
        _append_tool_result_section(lines, tool_results)
    return "\n".join(lines).strip()


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


def _render_clarification_artifact(
    intro: str,
    questions: list[str],
) -> str:
    lines = [
        "AES clarification required",
        "",
        intro,
        "",
        "Clarification questions:",
    ]
    lines.extend(f"- {question}" for question in questions)
    return "\n".join(lines).strip()


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

    if isinstance(value, (dict, list, tuple, set, int, float, bool)):
        text = str(value)
    else:
        text = safe_str(value, "none")

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "none"
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return _escape_markdown_value(text)


def _escape_markdown_value(text: str) -> str:
    return text.replace("*", "\\*")


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


def _looks_like_user_python_code(user_text: str) -> bool:
    stripped = user_text.strip()
    lowered = stripped.lower()
    if not stripped:
        return False
    if "```python" in lowered:
        return True
    code_markers = [
        "from dolfinx",
        "import dolfinx",
        "import fenics",
        "from fenics",
        "import ufl",
        "from mpi4py",
        "from petsc4py",
        "def main(",
        "if __name__",
    ]
    return (
        "\n" in stripped
        and any(marker in lowered for marker in code_markers)
    )


def _configured_solution_mode() -> str:
    configured = os.getenv("AES_SOLUTION_MODE", "").strip()
    allowed = {
        "generate_fenics_code",
        "execute_generated_fenics_code",
        "execute_user_fenics_code",
        "formulation_summary",
        "needs_output_intent",
        "deterministic_mcp_recipe",
    }
    return configured if configured in allowed else ""


def _detect_request_intent_from_text(user_text: str) -> dict[str, str]:
    stripped = user_text.strip()
    if not stripped:
        return {
            "request_intent": "empty_request",
            "intent_reason": "The latest user message is empty.",
        }

    if _looks_like_operational_command(stripped):
        return {
            "request_intent": "operational_command",
            "intent_reason": (
                "The latest user message looks like a shell, Docker, SSH, "
                "HTTP, or deployment command."
            ),
        }

    lowered = _lower_text(stripped)
    pde_markers = [
        "heat equation",
        "poisson",
        "laplace",
        "diffusion",
        "pde",
        "partial differential",
        "boundary condition",
        "dirichlet",
        "neumann",
        "finite element",
        "weak form",
        "strong form",
        "delta(u)",
        "grad(u)",
        "unit square",
    ]
    solve_markers = [
        "solve",
        "compute",
        "simulate",
        "find ",
        "formulate",
        "model ",
    ]
    if _has_any(stripped, pde_markers) and (
        _has_any(stripped, solve_markers)
        or _has_time_derivative(stripped)
        or "source" in lowered
    ):
        return {
            "request_intent": "engineering_pde_request",
            "intent_reason": (
                "The latest user message asks for an engineering or PDE "
                "solve/formulation workflow."
            ),
        }

    general_markers = [
        "what is",
        "explain",
        "how does",
        "why",
        "langgraph",
        "langchain",
        "mcp",
        "ollama",
        "open webui",
        "docker",
        "compose",
        "deployment",
        "architecture",
        "documentation",
    ]
    if _has_any(stripped, general_markers):
        return {
            "request_intent": "general_question",
            "intent_reason": (
                "The latest user message is a conceptual or operational "
                "question rather than a PDE solve request."
            ),
        }

    return {
        "request_intent": "unknown_request",
        "intent_reason": "The request intent is ambiguous and requires model routing.",
    }


def _looks_like_operational_command(user_text: str) -> bool:
    command_prefixes = (
        "docker ",
        "docker-compose ",
        "ssh ",
        "curl ",
        "git ",
        "cd ",
        "export ",
        "kubectl ",
        "python ",
        "python3 ",
        "py ",
        "pip ",
        "pytest ",
        "uvicorn ",
        "powershell ",
        "pwsh ",
        "bash ",
        "wsl ",
        "sudo ",
        "chmod ",
        "chown ",
        "ls ",
        "cat ",
        "grep ",
        "rg ",
        "tail ",
    )
    operational_fragments = (
        "docker compose",
        "docker logs",
        "docker exec",
        "compose.prod.yaml",
        "compose.dev.yaml",
        "--profile",
        "--force-recreate",
        "logs -f",
        "up -d",
        "ssh -l",
        "ssh -n",
        "ssh -t",
        "curl -x",
        "curl -s",
    )
    lines = [line.strip() for line in user_text.splitlines() if line.strip()]
    if not lines:
        return False

    command_like_lines = 0
    for line in lines:
        lowered = line.lower()
        if lowered.startswith(command_prefixes) or any(
            fragment in lowered for fragment in operational_fragments
        ):
            command_like_lines += 1

    if command_like_lines == len(lines):
        return True
    return command_like_lines > 0 and command_like_lines >= len(lines) / 2


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
        r"(?:diffusion\s+coefficient|coefficient|alpha|boundary|initial|time|source|f\s*=|k\s*=)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    return _normalize_math_expression(parts[0].strip())


def _normalize_math_expression(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\bsin\(pi([xy])\)", r"sin(pi*\1)", cleaned)
    cleaned = re.sub(
        r"\bsin\(pi\*x\)\s*sin\(pi\*y\)",
        "sin(pi*x)*sin(pi*y)",
        cleaned,
    )
    return cleaned


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
