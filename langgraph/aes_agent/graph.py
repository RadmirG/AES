from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from aes_agent.logging_config import log_content_preview
from aes_agent.nodes import (
    check_problem_completeness,
    classify_problem,
    detect_request_intent,
    extract_mathematical_structure,
    execute_tools,
    generate_clarification,
    generate_artifact,
    generate_formulation_summary,
    handle_non_engineering_request,
    ingest_problem,
    prepare_numerical_recipe,
    select_artifact_store,
    select_formulation,
    select_solution_mode,
    select_tools,
    validate_formulation,
)
from aes_agent.routing import (
    route_after_intent,
    route_after_completeness,
    route_after_numerical_recipe,
    route_after_solution_mode,
    route_after_validation,
)
from aes_agent.state import AgentState


logger = logging.getLogger("aes_agent.graph")


def _logged_node(
    name: str,
    fn: Callable[[AgentState], Dict[str, Any]],
) -> Callable[[AgentState], Dict[str, Any]]:
    def wrapper(state: AgentState) -> Dict[str, Any]:
        logger.info("Graph node started: node=%s", name)
        log_content_preview(logger, f"Graph node input: node={name}", _state_log_view(state))
        started_at = time.perf_counter()
        try:
            output = fn(state)
        except Exception:
            logger.exception("Graph node failed: node=%s", name)
            raise
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "Graph node finished: node=%s output_keys=%s elapsed_ms=%.1f",
            name,
            sorted(output.keys()),
            elapsed_ms,
        )
        log_content_preview(logger, f"Graph node output: node={name}", output)
        return output

    wrapper.__name__ = name
    return wrapper


def _logged_route(
    name: str,
    fn: Callable[[AgentState], str],
) -> Callable[[AgentState], str]:
    def wrapper(state: AgentState) -> str:
        decision = fn(state)
        logger.info("Graph route selected: route=%s decision=%s", name, decision)
        log_content_preview(logger, f"Graph route state: route={name}", _state_log_view(state))
        return decision

    wrapper.__name__ = name
    return wrapper


def _state_log_view(state: AgentState) -> Dict[str, Any]:
    return {
        "request_intent": state.get("request_intent", ""),
        "problem_class": state.get("problem_class", ""),
        "pde_info": state.get("pde_info", ""),
        "domain_info": state.get("domain_info", ""),
        "coefficient_info": state.get("coefficient_info", ""),
        "source_info": state.get("source_info", ""),
        "bc_info": state.get("bc_info", ""),
        "initial_condition_info": state.get("initial_condition_info", ""),
        "time_info": state.get("time_info", ""),
        "missing_information": state.get("missing_information", []),
        "solution_mode": state.get("solution_mode", ""),
        "selected_formulation": state.get("selected_formulation", ""),
        "validation_status": state.get("validation_status", ""),
        "numerical_recipe_status": state.get("numerical_recipe_status", ""),
        "selected_tools": state.get("selected_tools", []),
        "tool_execution_status": state.get("tool_execution_status", ""),
        "tool_errors": state.get("tool_errors", []),
        "agent_status": state.get("agent_status", ""),
        "next_action": state.get("next_action", ""),
    }


builder = StateGraph(AgentState)

builder.add_node("ingest_problem", _logged_node("ingest_problem", ingest_problem))
builder.add_node("detect_request_intent", _logged_node("detect_request_intent", detect_request_intent))
builder.add_node("handle_non_engineering_request", _logged_node("handle_non_engineering_request", handle_non_engineering_request))
builder.add_node("classify_problem", _logged_node("classify_problem", classify_problem))
builder.add_node("extract_mathematical_structure", _logged_node("extract_mathematical_structure", extract_mathematical_structure))
builder.add_node("check_problem_completeness", _logged_node("check_problem_completeness", check_problem_completeness))
builder.add_node("generate_clarification", _logged_node("generate_clarification", generate_clarification))
builder.add_node("generate_formulation_summary", _logged_node("generate_formulation_summary", generate_formulation_summary))
builder.add_node("select_formulation", _logged_node("select_formulation", select_formulation))
builder.add_node("validate_formulation", _logged_node("validate_formulation", validate_formulation))
builder.add_node("select_solution_mode", _logged_node("select_solution_mode", select_solution_mode))
builder.add_node("prepare_numerical_recipe", _logged_node("prepare_numerical_recipe", prepare_numerical_recipe))
builder.add_node("select_tools", _logged_node("select_tools", select_tools))
builder.add_node("select_artifact_store", _logged_node("select_artifact_store", select_artifact_store))
builder.add_node("execute_tools", _logged_node("execute_tools", execute_tools))
builder.add_node("generate_artifact", _logged_node("generate_artifact", generate_artifact))

builder.set_entry_point("ingest_problem")

builder.add_edge("ingest_problem", "detect_request_intent")
builder.add_conditional_edges(
    "detect_request_intent",
    _logged_route("route_after_intent", route_after_intent),
    {
        "continue": "classify_problem",
        "stop": "handle_non_engineering_request",
    },
)
builder.add_edge("classify_problem", "extract_mathematical_structure")
builder.add_edge("extract_mathematical_structure", "check_problem_completeness")
builder.add_conditional_edges(
    "check_problem_completeness",
    _logged_route("route_after_completeness", route_after_completeness),
    {
        "clarify": "generate_clarification",
        "formulate": "select_formulation",
    },
)
builder.add_edge("select_formulation", "validate_formulation")
builder.add_conditional_edges(
    "validate_formulation",
    _logged_route("route_after_validation", route_after_validation),
    {
        "tools": "select_solution_mode",
        "clarify": "generate_clarification",
    },
)
builder.add_conditional_edges(
    "select_solution_mode",
    _logged_route("route_after_solution_mode", route_after_solution_mode),
    {
        "ask_output": "generate_clarification",
        "formulation_summary": "generate_formulation_summary",
        "prepare": "prepare_numerical_recipe",
    },
)
builder.add_conditional_edges(
    "prepare_numerical_recipe",
    _logged_route("route_after_numerical_recipe", route_after_numerical_recipe),
    {
        "tools": "select_tools",
        "clarify": "generate_clarification",
    },
)
builder.add_edge("select_tools", "execute_tools")
builder.add_edge("execute_tools", "generate_artifact")
builder.add_edge("handle_non_engineering_request", "select_artifact_store")
builder.add_edge("generate_clarification", "select_artifact_store")
builder.add_edge("generate_formulation_summary", "select_artifact_store")
builder.add_edge("select_artifact_store", "execute_tools")
builder.add_edge("generate_artifact", END)

graph = builder.compile()
