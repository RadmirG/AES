from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, TypedDict

from aes_agent.state import AgentState


class ToolResult(TypedDict):
    tool_name: str
    provider: str
    status: str
    output: Dict[str, Any]
    error: str


ToolHandler = Callable[[AgentState], Dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    provider: str
    handler: ToolHandler


def export_problem_spec(state: AgentState) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "problem": {
            "class": state.get("problem_class", ""),
            "pde": state.get("pde_info", ""),
            "domain": state.get("domain_info", ""),
            "coefficients": state.get("coefficient_info", ""),
            "boundary_conditions": state.get("bc_info", ""),
        },
        "formulation": state.get("selected_formulation", ""),
        "validation_status": state.get("validation_status", ""),
    }


def build_workflow_plan(state: AgentState) -> Dict[str, Any]:
    formulation = state.get("selected_formulation", "")
    return {
        "plan_version": "1.0",
        "formulation": formulation,
        "steps": [
            {
                "id": "prepare_formulation",
                "action": "prepare_mathematical_formulation",
                "input": formulation,
            },
            {
                "id": "prepare_discretization",
                "action": "prepare_domain_discretization",
                "input": state.get("domain_info", ""),
            },
            {
                "id": "configure_solver",
                "action": "configure_numerical_solver",
                "input": state.get("pde_info", ""),
            },
            {
                "id": "validate_solution",
                "action": "validate_numerical_result",
                "input": state.get("bc_info", ""),
            },
        ],
    }


TOOL_REGISTRY: Dict[str, ToolDefinition] = {
    "problem_spec_exporter": ToolDefinition(
        name="problem_spec_exporter",
        description=(
            "Export the validated problem state as a canonical structured "
            "engineering specification."
        ),
        provider="local",
        handler=export_problem_spec,
    ),
    "workflow_plan_builder": ToolDefinition(
        name="workflow_plan_builder",
        description=(
            "Build an ordered numerical workflow plan from the validated "
            "problem and selected formulation."
        ),
        provider="local",
        handler=build_workflow_plan,
    ),
}


def register_tool(
    definition: ToolDefinition,
    *,
    replace: bool = False,
) -> None:
    if definition.name in TOOL_REGISTRY and not replace:
        raise ValueError(f"Tool already registered: {definition.name}")
    TOOL_REGISTRY[definition.name] = definition


def list_available_tools() -> List[str]:
    return list(TOOL_REGISTRY)


def tool_catalog() -> List[Dict[str, str]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "provider": definition.provider,
        }
        for definition in TOOL_REGISTRY.values()
    ]


def execute_tool(tool_name: str, state: AgentState) -> ToolResult:
    definition = TOOL_REGISTRY.get(tool_name)
    if definition is None:
        return {
            "tool_name": tool_name,
            "provider": "",
            "status": "failed",
            "output": {},
            "error": f"Unknown tool: {tool_name}",
        }

    try:
        output = definition.handler(state)
    except Exception as exc:
        return {
            "tool_name": tool_name,
            "provider": definition.provider,
            "status": "failed",
            "output": {},
            "error": str(exc),
        }

    return {
        "tool_name": tool_name,
        "provider": definition.provider,
        "status": "completed",
        "output": output,
        "error": "",
    }
