from typing import Any, Dict, List, TypedDict


class AgentState(TypedDict):
    raw_user_input: str
    problem_class: str
    domain_info: str
    pde_info: str
    coefficient_info: str
    bc_info: str
    missing_information: List[str]
    clarification_questions: List[str]
    selected_formulation: str
    validation_status: str
    validation_errors: List[str]
    selected_tools: List[str]
    tool_execution_status: str
    tool_results: List[Dict[str, Any]]
    tool_errors: List[str]
    generated_artifact: str
    agent_status: str
    next_action: str
