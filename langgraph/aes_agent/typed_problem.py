from __future__ import annotations

from typing import Any

from aes_agent.compiler.capability import build_compilation_plan
from aes_agent.helpers import ollama_json
from aes_agent.prompts import interpret_typed_problem_prompt
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.specs.pde import PDEProblemSpec
from aes_agent.specs.validation import (
    cross_validate_pde_geometry,
    validate_geometry_spec,
    validate_pde_spec,
)


def interpret_problem_specs(state: dict[str, Any]) -> dict[str, Any]:
    pde, geometry = build_legacy_specs(state)
    source = "deterministic_compatibility"
    ambiguities: list[str] = []

    if pde is None or geometry is None:
        response = ollama_json(interpret_typed_problem_prompt(state))
        pde_value = response.get("pde_spec") if isinstance(response, dict) else None
        geometry_value = response.get("geometry_spec") if isinstance(response, dict) else None
        ambiguities = _strings(response.get("ambiguities")) if isinstance(response, dict) else []
        try:
            parsed_pde = PDEProblemSpec.model_validate(pde_value) if isinstance(pde_value, dict) else None
        except Exception:
            parsed_pde = None
        try:
            parsed_geometry = GeometrySpec.model_validate(geometry_value) if isinstance(geometry_value, dict) else None
        except Exception:
            parsed_geometry = None
        pde = pde or parsed_pde
        geometry = geometry or parsed_geometry
        source = "llm_structured_extraction"

    return {
        "pde_spec": pde.model_dump(mode="json") if pde else {},
        "geometry_spec": geometry.model_dump(mode="json") if geometry else {},
        "typed_spec_source": source,
        "typed_spec_ambiguities": ambiguities,
    }


def validate_problem_specs(state: dict[str, Any]) -> dict[str, Any]:
    pde_value = state.get("pde_spec")
    geometry_value = state.get("geometry_spec")
    pde, pde_report = (
        validate_pde_spec(pde_value)
        if isinstance(pde_value, dict) and pde_value
        else (None, None)
    )
    geometry, geometry_report = (
        validate_geometry_spec(geometry_value)
        if isinstance(geometry_value, dict) and geometry_value
        else (None, None)
    )

    pde_errors = (
        pde_report.errors
        if pde_report is not None
        else ["AES could not construct a typed PDEProblemSpec."]
    )
    geometry_errors = (
        geometry_report.errors
        if geometry_report is not None
        else ["AES could not construct a typed GeometrySpec."]
    )
    errors = [*pde_errors, *geometry_errors]
    warnings = [
        *(pde_report.warnings if pde_report else []),
        *(geometry_report.warnings if geometry_report else []),
    ]
    ambiguities = _strings(state.get("typed_spec_ambiguities"))
    errors.extend(f"Structured interpretation is ambiguous: {item}" for item in ambiguities)
    if pde is not None and geometry is not None:
        compatibility = cross_validate_pde_geometry(pde, geometry)
        errors.extend(compatibility.errors)
    compilation_plan = (
        build_compilation_plan(pde, geometry).model_dump(mode="json")
        if pde is not None and geometry is not None and not errors
        else {}
    )
    return {
        "pde_spec": pde.model_dump(mode="json") if pde else state.get("pde_spec", {}),
        "geometry_spec": (
            geometry.model_dump(mode="json") if geometry else state.get("geometry_spec", {})
        ),
        "typed_validation_status": "invalid" if errors else "valid",
        "typed_validation_errors": errors,
        "typed_validation_warnings": warnings,
        "compilation_plan": compilation_plan,
    }


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
