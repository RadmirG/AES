from __future__ import annotations

from typing import Any, Dict

from aes_agent.helpers import ollama_json, safe_list_of_str, safe_str
from aes_agent.fenics_mcp import build_fenics_recipe
from aes_agent.prompts import (
    check_problem_completeness_prompt,
    classify_problem_prompt,
    extract_mathematical_structure_prompt,
    generate_clarification_prompt,
    generate_artifact_prompt,
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
    prompt = classify_problem_prompt(user_text)
    result = ollama_json(prompt)

    return {
        "problem_class": safe_str(result.get("problem_class"), "unknown_problem"),
        "pde_info": safe_str(result.get("pde_info"), "unknown_pde"),
    }


def extract_mathematical_structure(state: AgentState) -> Dict[str, Any]:
    user_text = state.get("raw_user_input", "")
    problem_class = state.get("problem_class", "")
    pde_info = state.get("pde_info", "")

    prompt = extract_mathematical_structure_prompt(
        user_text=user_text,
        problem_class=problem_class,
        pde_info=pde_info,
    )
    result = ollama_json(prompt)

    return {
        "domain_info": safe_str(result.get("domain_info"), "unknown_domain"),
        "coefficient_info": safe_str(result.get("coefficient_info"), "unknown_coefficient"),
        "source_info": safe_str(result.get("source_info"), "unknown_source"),
        "bc_info": safe_str(result.get("bc_info"), "unknown_boundary_condition"),
        "initial_condition_info": safe_str(
            result.get("initial_condition_info"),
            "unknown_initial_condition",
        ),
        "time_info": safe_str(result.get("time_info"), "unknown_time"),
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
    result = ollama_json(prompt)

    return {
        "missing_information": safe_list_of_str(result.get("missing_information"))
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

    result = ollama_json(generate_clarification_prompt(snapshot))
    clarification_questions = safe_list_of_str(
        result.get("clarification_questions")
    )
    unresolved_issues = (
        state.get("missing_information", [])
        or state.get("validation_errors", [])
        or state.get("numerical_recipe_errors", [])
    )
    if not clarification_questions:
        clarification_questions = [
            f"Please clarify: {issue}" for issue in unresolved_issues
        ]

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
    result = ollama_json(prompt)

    return {
        "selected_formulation": safe_str(
            result.get("selected_formulation"),
            "unknown_formulation",
        )
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

    result = ollama_json(validate_formulation_prompt(snapshot))
    validation_status = safe_str(
        result.get("validation_status"),
        "invalid",
    ).lower()
    validation_errors = safe_list_of_str(result.get("validation_errors"))

    if validation_status not in {"valid", "invalid"}:
        validation_status = "invalid"
    if validation_status == "invalid" and not validation_errors:
        validation_errors = ["The selected formulation could not be validated."]
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

    prompt = generate_artifact_prompt(snapshot)
    result = ollama_json(prompt)

    if state.get("tool_execution_status") == "failed":
        agent_status = "tool_error"
        next_action = "review_tool_errors"
    else:
        agent_status = "ok"
        next_action = "review_tool_results"

    return {
        "generated_artifact": safe_str(result.get("generated_artifact"), ""),
        "agent_status": agent_status,
        "next_action": next_action,
    }
