from langgraph.graph import END, StateGraph

from app.nodes import (
    check_problem_completeness,
    classify_problem,
    extract_mathematical_structure,
    generate_artifact,
    ingest_problem,
    select_formulation,
    select_tools,
)
from app.state import AgentState


builder = StateGraph(AgentState)

builder.add_node("ingest_problem", ingest_problem)
builder.add_node("classify_problem", classify_problem)
builder.add_node("extract_mathematical_structure", extract_mathematical_structure)
builder.add_node("check_problem_completeness", check_problem_completeness)
builder.add_node("select_formulation", select_formulation)
builder.add_node("select_tools", select_tools)
builder.add_node("generate_artifact", generate_artifact)

builder.set_entry_point("ingest_problem")

builder.add_edge("ingest_problem", "classify_problem")
builder.add_edge("classify_problem", "extract_mathematical_structure")
builder.add_edge("extract_mathematical_structure", "check_problem_completeness")
builder.add_edge("check_problem_completeness", "select_formulation")
builder.add_edge("select_formulation", "select_tools")
builder.add_edge("select_tools", "generate_artifact")
builder.add_edge("generate_artifact", END)

graph = builder.compile()