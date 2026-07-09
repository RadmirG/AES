from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, TypedDict

from aes_agent.artifact_store import persist_artifacts
from aes_agent.fenics_mcp import execute_fenics_forward_solve
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
    input_schema: Dict[str, Any] = field(default_factory=dict)


def export_problem_spec(state: AgentState) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "problem": {
            "class": state.get("problem_class", ""),
            "pde": state.get("pde_info", ""),
            "domain": state.get("domain_info", ""),
            "coefficients": state.get("coefficient_info", ""),
            "source": state.get("source_info", ""),
            "boundary_conditions": state.get("bc_info", ""),
            "initial_condition": state.get("initial_condition_info", ""),
            "time": state.get("time_info", ""),
        },
        "formulation": state.get("selected_formulation", ""),
        "validation_status": state.get("validation_status", ""),
        "numerical_recipe_status": state.get("numerical_recipe_status", ""),
        "numerical_recipe": state.get("numerical_recipe", {}),
    }


def build_workflow_plan(state: AgentState) -> Dict[str, Any]:
    formulation = state.get("selected_formulation", "")
    return {
        "plan_version": "1.0",
        "formulation": formulation,
        "numerical_recipe": state.get("numerical_recipe", {}),
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


def run_fenics_forward_solve(state: AgentState) -> Dict[str, Any]:
    return execute_fenics_forward_solve(state)


def store_artifacts(state: AgentState) -> Dict[str, Any]:
    return persist_artifacts(state)


FENICS_FORWARD_SOLVE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "Uses state.numerical_recipe prepared by AES. The LLM should not "
        "invent raw FEniCS code or call low-level DOLFINx tools directly."
    ),
    "required_state": [
        "numerical_recipe_status",
        "numerical_recipe",
    ],
}


ARTIFACT_STORE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "Consumes previous tool results from AgentState and persists an AES-owned "
        "artifact manifest under AES_ARTIFACT_ROOT."
    ),
    "required_state": [
        "tool_results",
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
    "fenics_forward_solve": ToolDefinition(
        name="fenics_forward_solve",
        description=(
            "Prepare or execute a constrained forward finite-element solve "
            "through a DOLFINx/FEniCS MCP server. First supported workflows: "
            "Poisson/stationary diffusion and heat equation on simple 2D domains."
        ),
        provider="mcp:dolfinx",
        handler=run_fenics_forward_solve,
        input_schema=FENICS_FORWARD_SOLVE_SCHEMA,
    ),
    "artifact_store": ToolDefinition(
        name="artifact_store",
        description=(
            "Persist AES-owned artifact manifests and summaries from previous "
            "tool outputs. Providers return results; AES decides final storage."
        ),
        provider="local:artifact_store",
        handler=store_artifacts,
        input_schema=ARTIFACT_STORE_SCHEMA,
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


def tool_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "provider": definition.provider,
            "input_schema": definition.input_schema,
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

    output_errors = _tool_output_errors(output)
    if output_errors:
        return {
            "tool_name": tool_name,
            "provider": definition.provider,
            "status": "failed",
            "output": output,
            "error": "; ".join(output_errors),
        }

    return {
        "tool_name": tool_name,
        "provider": definition.provider,
        "status": "completed",
        "output": output,
        "error": "",
    }


def _tool_output_errors(output: Dict[str, Any]) -> List[str]:
    if not isinstance(output, dict):
        return []

    raw_errors = output.get("errors") or []
    if isinstance(raw_errors, list):
        errors = [str(error) for error in raw_errors if str(error).strip()]
    else:
        errors = [str(raw_errors)] if str(raw_errors).strip() else []

    if output.get("execution_mode") == "failed" and not errors:
        errors.append("Tool execution failed.")

    return errors
