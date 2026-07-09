from typing import Literal

from aes_agent.state import AgentState


def route_after_intent(
    state: AgentState,
) -> Literal["continue", "stop"]:
    if state.get("request_intent") == "engineering_pde_request":
        return "continue"
    return "stop"


def route_after_completeness(
    state: AgentState,
) -> Literal["clarify", "formulate"]:
    if state.get("missing_information"):
        return "clarify"
    return "formulate"


def route_after_validation(
    state: AgentState,
) -> Literal["clarify", "tools"]:
    if state.get("validation_status") == "valid":
        return "tools"
    return "clarify"


def route_after_numerical_recipe(
    state: AgentState,
) -> Literal["clarify", "tools"]:
    if state.get("numerical_recipe_status") == "ready":
        return "tools"
    return "clarify"
