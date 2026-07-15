from __future__ import annotations

from typing import Any, Dict, Iterable


PUBLIC_STATE_FIELDS = (
    "request_intent",
    "intent_reason",
    "problem_class",
    "domain_info",
    "pde_info",
    "coefficient_info",
    "source_info",
    "bc_info",
    "initial_condition_info",
    "time_info",
    "missing_information",
    "clarification_questions",
    "selected_formulation",
    "validation_status",
    "validation_errors",
    "solution_mode",
    "numerical_recipe_status",
    "numerical_recipe",
    "numerical_recipe_errors",
    "selected_tools",
    "tool_execution_status",
    "tool_errors",
    "generated_artifact",
    "agent_status",
    "next_action",
)

PUBLIC_TOOL_OUTPUT_FIELDS = (
    "schema_version",
    "provider",
    "execution_mode",
    "safety_status",
    "code_summary",
    "generated_file_names",
    "source_tool",
    "preview_name",
    "viewer_name",
    "message",
    "warnings",
    "errors",
    "manifest_path",
    "summary_path",
)

PUBLIC_MANIFEST_FIELDS = (
    "schema_version",
    "run_id",
    "created_at",
    "status",
    "problem",
    "agent",
    "sources",
    "workflow_message",
    "errors",
    "warnings",
)

PUBLIC_ARTIFACT_FIELDS = (
    "name",
    "kind",
    "media_type",
    "uri",
    "storage",
    "status",
    "metadata",
    "producer",
    "public_url",
)


def build_public_aes_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Project internal AgentState into the bounded browser/API contract."""
    public_result = {
        field: _bounded_json_value(result[field])
        for field in PUBLIC_STATE_FIELDS
        if field in result
    }
    public_result["tool_results"] = [
        _public_tool_result(tool_result)
        for tool_result in _dict_items(result.get("tool_results"))
    ]
    return public_result


def _public_tool_result(tool_result: Dict[str, Any]) -> Dict[str, Any]:
    public_result = {
        "tool_name": str(tool_result.get("tool_name", "")),
        "provider": str(tool_result.get("provider", "")),
        "status": str(tool_result.get("status", "")),
        "error": _bounded_text(tool_result.get("error", ""), limit=4000),
        "output": {},
    }
    output = tool_result.get("output")
    if not isinstance(output, dict):
        return public_result

    public_output = {
        field: _bounded_json_value(output[field])
        for field in PUBLIC_TOOL_OUTPUT_FIELDS
        if field in output
    }
    if tool_result.get("tool_name") == "artifact_store":
        public_output["manifest"] = _public_manifest(output.get("manifest"))
    public_result["output"] = public_output
    return public_result


def _public_manifest(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    manifest = {
        field: _bounded_json_value(value[field])
        for field in PUBLIC_MANIFEST_FIELDS
        if field in value
    }
    manifest["artifacts"] = [
        _public_artifact(artifact)
        for artifact in _dict_items(value.get("artifacts"))
    ]
    return manifest


def _public_artifact(value: Dict[str, Any]) -> Dict[str, Any]:
    # Inline content is deliberately not part of the public result. Clients
    # fetch materialized files through the authenticated /artifacts endpoint.
    return {
        field: _bounded_json_value(value[field])
        for field in PUBLIC_ARTIFACT_FIELDS
        if field in value
    }


def _dict_items(value: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return (item for item in value if isinstance(item, dict))


def _bounded_json_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 5,
    max_items: int = 100,
) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value, limit=12000)
    if depth >= max_depth:
        return "[omitted: nesting limit]"
    if isinstance(value, list):
        return [
            _bounded_json_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
            )
            for item in value[:max_items]
        ]
    if isinstance(value, dict):
        return {
            str(key): _bounded_json_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
            )
            for key, item in list(value.items())[:max_items]
        }
    return _bounded_text(value, limit=2000)


def _bounded_text(value: Any, *, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated]"
