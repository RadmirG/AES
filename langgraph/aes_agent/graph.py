from langgraph.graph import END, StateGraph

from aes_agent.nodes import (
    check_problem_completeness,
    classify_problem,
    detect_request_intent,
    extract_mathematical_structure,
    execute_tools,
    generate_clarification,
    generate_artifact,
    handle_non_engineering_request,
    ingest_problem,
    prepare_numerical_recipe,
    select_formulation,
    select_solution_mode,
    select_tools,
    validate_formulation,
)
from aes_agent.routing import (
    route_after_intent,
    route_after_completeness,
    route_after_numerical_recipe,
    route_after_validation,
)
from aes_agent.state import AgentState


builder = StateGraph(AgentState)

builder.add_node("ingest_problem", ingest_problem)
builder.add_node("detect_request_intent", detect_request_intent)
builder.add_node("handle_non_engineering_request", handle_non_engineering_request)
builder.add_node("classify_problem", classify_problem)
builder.add_node("extract_mathematical_structure", extract_mathematical_structure)
builder.add_node("check_problem_completeness", check_problem_completeness)
builder.add_node("generate_clarification", generate_clarification)
builder.add_node("select_formulation", select_formulation)
builder.add_node("validate_formulation", validate_formulation)
builder.add_node("select_solution_mode", select_solution_mode)
builder.add_node("prepare_numerical_recipe", prepare_numerical_recipe)
builder.add_node("select_tools", select_tools)
builder.add_node("execute_tools", execute_tools)
builder.add_node("generate_artifact", generate_artifact)

builder.set_entry_point("ingest_problem")

builder.add_edge("ingest_problem", "detect_request_intent")
builder.add_conditional_edges(
    "detect_request_intent",
    route_after_intent,
    {
        "continue": "classify_problem",
        "stop": "handle_non_engineering_request",
    },
)
builder.add_edge("classify_problem", "extract_mathematical_structure")
builder.add_edge("extract_mathematical_structure", "check_problem_completeness")
builder.add_conditional_edges(
    "check_problem_completeness",
    route_after_completeness,
    {
        "clarify": "generate_clarification",
        "formulate": "select_formulation",
    },
)
builder.add_edge("select_formulation", "validate_formulation")
builder.add_conditional_edges(
    "validate_formulation",
    route_after_validation,
    {
        "tools": "select_solution_mode",
        "clarify": "generate_clarification",
    },
)
builder.add_edge("select_solution_mode", "prepare_numerical_recipe")
builder.add_conditional_edges(
    "prepare_numerical_recipe",
    route_after_numerical_recipe,
    {
        "tools": "select_tools",
        "clarify": "generate_clarification",
    },
)
builder.add_edge("select_tools", "execute_tools")
builder.add_edge("execute_tools", "generate_artifact")
builder.add_edge("handle_non_engineering_request", END)
builder.add_edge("generate_clarification", END)
builder.add_edge("generate_artifact", END)

graph = builder.compile()
