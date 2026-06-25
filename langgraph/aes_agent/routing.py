from typing import Literal

from aes_agent.state import AgentState


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
