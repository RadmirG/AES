from __future__ import annotations

from typing import Any, Dict

from aes_agent.helpers import ollama_json, safe_list_of_str, safe_str
from aes_agent.prompts import (
    check_problem_completeness_prompt,
    classify_problem_prompt,
    extract_mathematical_structure_prompt,
    generate_artifact_prompt,
    select_formulation_prompt,
    select_tools_prompt,
)
from aes_agent.state import AgentState


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
        "bc_info": safe_str(result.get("bc_info"), "unknown_boundary_condition"),
    }


def check_problem_completeness(state: AgentState) -> Dict[str, Any]:
    user_text = state.get("raw_user_input", "")
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "bc_info": state.get("bc_info", ""),
    }

    prompt = check_problem_completeness_prompt(
        user_text=user_text,
        snapshot=snapshot,
    )
    result = ollama_json(prompt)

    return {
        "missing_information": safe_list_of_str(result.get("missing_information"))
    }


def select_formulation(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "bc_info": state.get("bc_info", ""),
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


def select_tools(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "bc_info": state.get("bc_info", ""),
        "missing_information": state.get("missing_information", []),
        "selected_formulation": state.get("selected_formulation", ""),
    }

    prompt = select_tools_prompt(snapshot)
    result = ollama_json(prompt)

    return {
        "selected_tools": safe_list_of_str(result.get("selected_tools"))
    }

def generate_artifact(state: AgentState) -> Dict[str, Any]:
    snapshot = {
        "raw_user_input": state.get("raw_user_input", ""),
        "problem_class": state.get("problem_class", ""),
        "domain_info": state.get("domain_info", ""),
        "pde_info": state.get("pde_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "bc_info": state.get("bc_info", ""),
        "missing_information": state.get("missing_information", []),
        "selected_formulation": state.get("selected_formulation", ""),
        "selected_tools": state.get("selected_tools", []),
    }

    prompt = generate_artifact_prompt(snapshot)
    result = ollama_json(prompt)

    missing_information = state.get("missing_information", [])
    selected_formulation = state.get("selected_formulation", "")

    if missing_information or selected_formulation == "clarification_required":
        agent_status = "needs_clarification"
        next_action = "request_clarification"
    else:
        agent_status = "ok"
        next_action = "proceed_to_formulation"

    return {
        "generated_artifact": safe_str(result.get("generated_artifact"), ""),
        "agent_status": agent_status,
        "next_action": next_action,
    }
