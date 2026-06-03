from typing import List, TypedDict


class AgentState(TypedDict):
    raw_user_input: str
    problem_class: str
    domain_info: str
    pde_info: str
    coefficient_info: str
    bc_info: str
    missing_information: List[str]
    selected_formulation: str
    selected_tools: List[str]
    generated_artifact: str