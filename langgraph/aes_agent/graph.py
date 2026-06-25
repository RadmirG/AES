from langgraph.graph import END, StateGraph

from aes_agent.nodes import (
    check_problem_completeness,
    classify_problem,
    extract_mathematical_structure,
    execute_tools,
    generate_clarification,
    generate_artifact,
    ingest_problem,
    select_formulation,
    select_tools,
    validate_formulation,
)
from aes_agent.routing import route_after_completeness, route_after_validation
from aes_agent.state import AgentState


builder = StateGraph(AgentState)

builder.add_node("ingest_problem", ingest_problem)
builder.add_node("classify_problem", classify_problem)
builder.add_node("extract_mathematical_structure", extract_mathematical_structure)
builder.add_node("check_problem_completeness", check_problem_completeness)
builder.add_node("generate_clarification", generate_clarification)
builder.add_node("select_formulation", select_formulation)
builder.add_node("validate_formulation", validate_formulation)
builder.add_node("select_tools", select_tools)
builder.add_node("execute_tools", execute_tools)
builder.add_node("generate_artifact", generate_artifact)

builder.set_entry_point("ingest_problem")

builder.add_edge("ingest_problem", "classify_problem")
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
        "tools": "select_tools",
        "clarify": "generate_clarification",
    },
)
builder.add_edge("select_tools", "execute_tools")
builder.add_edge("execute_tools", "generate_artifact")
builder.add_edge("generate_clarification", END)
builder.add_edge("generate_artifact", END)

graph = builder.compile()
