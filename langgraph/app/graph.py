from typing import TypedDict, List
from langgraph.graph import StateGraph, END


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


def ingest_problem(state: AgentState) -> dict:
    """
    First node:
    - normalize and store the raw input
    """
    raw_text = state.get("raw_user_input", "").strip()

    return {
        "raw_user_input": raw_text
    }


def classify_problem(state: AgentState) -> dict:
    """
    Very first heuristic classifier.
    Later this node can be replaced by an Ollama-powered reasoning step.
    """
    text = state.get("raw_user_input", "").lower()

    problem_class = "unknown_problem"
    pde_info = "unknown_pde"

    # Heuristic problem-class detection
    if "inverse" in text:
        problem_class = "inverse_problem"
    elif "optimiz" in text:
        problem_class = "optimization_problem"
    elif "heat" in text or "diffusion" in text or "laplace" in text or "div" in text:
        problem_class = "forward_problem"

    # Heuristic PDE-type detection
    if "u_t" in text or "time-dependent" in text or "parabolic" in text:
        pde_info = "time_dependent_heat_equation"
    elif "heat" in text or "diffusion" in text or "laplace" in text or "-div" in text or "stationary" in text:
        pde_info = "stationary_diffusion_equation"

    return {
        "problem_class": problem_class,
        "pde_info": pde_info
    }


def extract_mathematical_structure(state: AgentState) -> dict:
    """
    Extracts very simple structured information from the text.
    This is intentionally heuristic in round 1.
    """
    text = state.get("raw_user_input", "").lower()

    domain_info = "unknown_domain"
    coefficient_info = "unknown_coefficient"
    bc_info = "unknown_boundary_condition"

    # Domain heuristics
    if "cube" in text:
        domain_info = "cube_domain"
    elif "rectangular" in text or "rectangle" in text or "box" in text:
        domain_info = "rectangular_domain"
    elif "omega" in text or "Ω" in state.get("raw_user_input", ""):
        domain_info = "domain_symbolically_specified"

    # Coefficient heuristics
    if "a(x" in text or "a(" in text or "coefficient" in text:
        coefficient_info = "spatially_dependent_coefficient_given"
    elif "constant diffusivity" in text or "constant coefficient" in text:
        coefficient_info = "constant_coefficient_given"

    # Boundary condition heuristics
    if "dirichlet" in text or "u(x) = g" in text or "u=g" in text:
        bc_info = "dirichlet_boundary_condition"
    elif "neumann" in text:
        bc_info = "neumann_boundary_condition"
    elif "robin" in text:
        bc_info = "robin_boundary_condition"

    return {
        "domain_info": domain_info,
        "coefficient_info": coefficient_info,
        "bc_info": bc_info
    }


def check_problem_completeness(state: AgentState) -> dict:
    """
    Checks whether essential problem information appears to be present.
    Also flags simple inconsistencies.
    """
    missing_information: List[str] = []

    raw_text = state.get("raw_user_input", "").lower()
    domain_info = state.get("domain_info", "")
    pde_info = state.get("pde_info", "")
    coefficient_info = state.get("coefficient_info", "")
    bc_info = state.get("bc_info", "")

    # Minimal completeness checks
    if domain_info == "unknown_domain":
        missing_information.append("Domain geometry is not clearly specified.")

    if coefficient_info == "unknown_coefficient":
        missing_information.append("Coefficient information is missing or unclear.")

    if bc_info == "unknown_boundary_condition":
        missing_information.append("Boundary condition type is missing or unclear.")

    if pde_info == "unknown_pde":
        missing_information.append("PDE type could not be classified.")

    # Simple inconsistency check:
    # stationary PDE but source seems time-dependent
    if pde_info == "stationary_diffusion_equation":
        if "f(x,y,z,t)" in raw_text or "f(x, y, z, t)" in raw_text or "time-dependent source" in raw_text:
            missing_information.append(
                "Potential inconsistency detected: the PDE appears stationary, but the source term seems time-dependent."
            )

    return {
        "missing_information": missing_information
    }


# -------------------------------------------------------------------
# Build the graph
# -------------------------------------------------------------------

builder = StateGraph(AgentState)

builder.add_node("ingest_problem", ingest_problem)
builder.add_node("classify_problem", classify_problem)
builder.add_node("extract_mathematical_structure", extract_mathematical_structure)
builder.add_node("check_problem_completeness", check_problem_completeness)

builder.set_entry_point("ingest_problem")

builder.add_edge("ingest_problem", "classify_problem")
builder.add_edge("classify_problem", "extract_mathematical_structure")
builder.add_edge("extract_mathematical_structure", "check_problem_completeness")
builder.add_edge("check_problem_completeness", END)

graph = builder.compile()
