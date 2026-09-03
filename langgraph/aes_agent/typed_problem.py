from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import Field

from aes_agent.compiler.capability import build_compilation_plan
from aes_agent.helpers import ollama_json
from aes_agent.prompts import interpret_typed_problem_prompt
from aes_agent.specs.base import StrictModel
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.specs.pde import PDEProblemSpec
from aes_agent.specs.validation import (
    cross_validate_pde_geometry,
    validate_geometry_spec,
    validate_pde_spec,
)


logger = logging.getLogger("aes_agent.typed_problem")


class TypedProblemInterpretation(StrictModel):
    pde_spec: PDEProblemSpec
    geometry_spec: GeometrySpec
    ambiguities: list[str] = Field(default_factory=list)


def interpret_problem_specs(state: dict[str, Any]) -> dict[str, Any]:
    """Interpret natural language with the LLM, then fail over deterministically.

    The compatibility parser is intentionally a fallback. It keeps a supported
    solve available when the model endpoint is unavailable or returns malformed
    JSON, but it must not silently bypass the documented LLM interpretation
    stage.
    """

    fallback_pde, fallback_geometry = build_legacy_specs(state)
    strategy = os.getenv("AES_TYPED_INTERPRETATION_MODE", "llm_first").strip().lower()
    if strategy == "deterministic_only":
        logger.info(
            "Typed problem interpretation completed: strategy=%s source=deterministic_configuration",
            strategy,
        )
        return _interpretation_result(
            fallback_pde,
            fallback_geometry,
            source="deterministic_configuration",
        )

    logger.info(
        "Typed problem interpretation started: strategy=llm_first input_chars=%s",
        len(str(state.get("raw_user_input", ""))),
    )
    response = ollama_json(
        interpret_typed_problem_prompt(state),
        schema=TypedProblemInterpretation.model_json_schema(),
    )
    pde, pde_error = _parse_pde(response.get("pde_spec") if isinstance(response, dict) else None)
    geometry, geometry_error = _parse_geometry(
        response.get("geometry_spec") if isinstance(response, dict) else None
    )
    ambiguities = _strings(response.get("ambiguities")) if isinstance(response, dict) else []

    if pde is not None and geometry is not None:
        logger.info(
            "Typed problem interpretation completed: source=llm_structured_extraction "
            "pde_family=%s geometry_source=%s ambiguities=%s",
            pde.equation.family,
            geometry.source.kind,
            len(ambiguities),
        )
        return _interpretation_result(
            pde,
            geometry,
            source="llm_structured_extraction",
            ambiguities=ambiguities,
        )

    failures = [item for item in (pde_error, geometry_error) if item]
    logger.warning(
        "Typed LLM interpretation was unusable; deterministic fallback requested: errors=%s",
        failures or ["model returned no structured object"],
    )
    if fallback_pde is not None and fallback_geometry is not None:
        return _interpretation_result(
            fallback_pde,
            fallback_geometry,
            source="deterministic_fallback",
            warnings=[
                "LLM structured interpretation was unusable; AES used the deterministic "
                "compatibility extractor.",
                *failures,
            ],
        )

    return _interpretation_result(
        pde,
        geometry,
        source="llm_structured_extraction_failed",
        ambiguities=ambiguities,
        warnings=failures or ["The model returned no usable typed specifications."],
    )


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
        *_strings(state.get("typed_interpretation_warnings")),
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


def _parse_pde(value: Any) -> tuple[PDEProblemSpec | None, str]:
    if not isinstance(value, dict):
        return None, "LLM response did not contain a pde_spec object."
    try:
        return PDEProblemSpec.model_validate(value), ""
    except Exception as exc:
        return None, f"LLM pde_spec failed schema validation: {_compact_error(exc)}"


def _parse_geometry(value: Any) -> tuple[GeometrySpec | None, str]:
    if not isinstance(value, dict):
        return None, "LLM response did not contain a geometry_spec object."
    try:
        return GeometrySpec.model_validate(value), ""
    except Exception as exc:
        return None, f"LLM geometry_spec failed schema validation: {_compact_error(exc)}"


def _interpretation_result(
    pde: PDEProblemSpec | None,
    geometry: GeometrySpec | None,
    *,
    source: str,
    ambiguities: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "pde_spec": pde.model_dump(mode="json") if pde else {},
        "geometry_spec": geometry.model_dump(mode="json") if geometry else {},
        "typed_spec_source": source,
        "typed_spec_ambiguities": ambiguities or [],
        "typed_interpretation_warnings": warnings or [],
    }


def _compact_error(exc: Exception, limit: int = 700) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else f"{text[:limit]}..."
