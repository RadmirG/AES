from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import Field

from aes_agent.compiler.capability import build_compilation_plan
from aes_agent.helpers import ollama_json
from aes_agent.prompts import (
    interpret_pde_for_geometry_prompt,
    interpret_typed_problem_prompt,
)
from aes_agent.specs.base import StrictModel
from aes_agent.specs.geometry import GeometrySpec, RegionSelector, RegionSpec
from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.specs.pde import PDEProblemSpec
from aes_agent.specs.validation import (
    cross_validate_pde_geometry,
    validate_geometry_spec,
    validate_pde_spec,
)


logger = logging.getLogger("aes_agent.typed_problem")

_DEFAULT_MARKERS = ("default", "defaulted", "assumed")
_SUPPORTED_NUMERICAL_DEFAULTS = (
    "time stepping scheme",
    "time-stepping scheme",
    "time integration scheme",
    "temporal scheme",
    "backward_euler",
    "backward euler",
    "function space",
    "finite element family",
    "finite element degree",
    "mesh resolution",
    "mesh size",
    "linear solver",
    "preconditioner",
    "output format",
)


class TypedProblemInterpretation(StrictModel):
    pde_spec: PDEProblemSpec
    geometry_spec: GeometrySpec
    ambiguities: list[str] = Field(default_factory=list)


class TypedPDEInterpretation(StrictModel):
    pde_spec: PDEProblemSpec
    ambiguities: list[str] = Field(default_factory=list)


def interpret_problem_specs(state: dict[str, Any]) -> dict[str, Any]:
    """Interpret natural language with the LLM, then fail over deterministically.

    The compatibility parser is intentionally a fallback. It keeps a supported
    solve available when the model endpoint is unavailable or returns malformed
    JSON, but it must not silently bypass the documented LLM interpretation
    stage.
    """

    fallback_pde, fallback_geometry = build_legacy_specs(state)
    requested_value = state.get("requested_geometry_spec")
    requested_geometry: GeometrySpec | None = None
    requested_geometry_warnings: list[str] = []
    if isinstance(requested_value, dict) and requested_value:
        requested_geometry, requested_error = _parse_geometry(requested_value)
        if requested_geometry is None:
            logger.warning("Attached GeometrySpec was rejected: error=%s", requested_error)
            return _interpretation_result(
                fallback_pde,
                None,
                source="request_geometry_invalid",
                geometry_source="request_context_invalid",
                ambiguities=[f"Attached geometry is invalid: {requested_error}"],
            )
        requested_geometry, boundary_added = _ensure_boundary_region(requested_geometry)
        if boundary_added:
            requested_geometry_warnings.append(
                "AES added the semantic 'boundary' region for all exterior boundaries."
            )
        fallback_pde = _adapt_pde_to_geometry(fallback_pde, requested_geometry)
    strategy = os.getenv("AES_TYPED_INTERPRETATION_MODE", "llm_first").strip().lower()
    if strategy == "deterministic_only":
        logger.info(
            "Typed problem interpretation completed: strategy=%s source=deterministic_configuration",
            strategy,
        )
        return _interpretation_result(
            fallback_pde,
            requested_geometry or fallback_geometry,
            source="deterministic_configuration",
            geometry_source=("request_context" if requested_geometry else "deterministic_configuration"),
            warnings=requested_geometry_warnings,
        )

    logger.info(
        "Typed problem interpretation started: strategy=llm_first input_chars=%s",
        len(str(state.get("raw_user_input", ""))),
    )
    if requested_geometry is not None:
        response = ollama_json(
            interpret_pde_for_geometry_prompt(
                state,
                requested_geometry.model_dump(mode="json"),
            ),
            schema=TypedPDEInterpretation.model_json_schema(),
        )
    else:
        response = ollama_json(
            interpret_typed_problem_prompt(state),
            schema=TypedProblemInterpretation.model_json_schema(),
        )
    pde, pde_error = _parse_pde(response.get("pde_spec") if isinstance(response, dict) else None)
    if requested_geometry is not None:
        geometry, geometry_error = requested_geometry, ""
    else:
        geometry, geometry_error = _parse_geometry(
            response.get("geometry_spec") if isinstance(response, dict) else None
        )
    raw_ambiguities = _strings(response.get("ambiguities")) if isinstance(response, dict) else []
    ambiguities, default_warnings = _partition_ambiguities(raw_ambiguities)
    if requested_geometry is not None:
        ambiguities, context_warnings = _partition_supplied_geometry_ambiguities(
            ambiguities
        )
        default_warnings.extend(context_warnings)

    if pde is not None and geometry is not None:
        logger.info(
            "Typed problem interpretation completed: source=llm_structured_extraction "
            "pde_family=%s geometry_source=%s blocking_ambiguities=%s accepted_defaults=%s",
            pde.equation.family,
            geometry.source.kind,
            len(ambiguities),
            len(default_warnings),
        )
        return _interpretation_result(
            pde,
            geometry,
            source="llm_structured_extraction",
            geometry_source=("request_context" if requested_geometry else "llm_structured_extraction"),
            ambiguities=ambiguities,
            warnings=[*requested_geometry_warnings, *default_warnings],
        )

    failures = [item for item in (pde_error, geometry_error) if item]
    logger.warning(
        "Typed LLM interpretation was unusable; deterministic fallback requested: errors=%s",
        failures or ["model returned no structured object"],
    )
    fallback_geometry_for_run = requested_geometry or fallback_geometry
    if fallback_pde is not None and fallback_geometry_for_run is not None:
        return _interpretation_result(
            fallback_pde,
            fallback_geometry_for_run,
            source="deterministic_fallback",
            geometry_source=("request_context" if requested_geometry else "deterministic_fallback"),
            warnings=[
                "LLM structured interpretation was unusable; AES used the deterministic "
                "compatibility extractor.",
                *failures,
                *requested_geometry_warnings,
                *default_warnings,
            ],
        )

    return _interpretation_result(
        pde,
        geometry,
        source="llm_structured_extraction_failed",
        geometry_source=("request_context" if requested_geometry else "llm_structured_extraction_failed"),
        ambiguities=ambiguities,
        warnings=[
            *(failures or ["The model returned no usable typed specifications."]),
            *default_warnings,
        ],
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


def _partition_ambiguities(items: list[str]) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    for item in items:
        normalized = " ".join(item.lower().replace("_", " ").split())
        has_default_marker = any(marker in normalized for marker in _DEFAULT_MARKERS)
        is_supported_default = any(
            phrase.replace("_", " ") in normalized
            for phrase in _SUPPORTED_NUMERICAL_DEFAULTS
        )
        if has_default_marker and is_supported_default:
            warnings.append(f"Accepted non-blocking numerical default: {item}")
        else:
            blocking.append(item)
    return blocking, warnings


def _partition_supplied_geometry_ambiguities(
    items: list[str],
) -> tuple[list[str], list[str]]:
    blocking: list[str] = []
    warnings: list[str] = []
    for item in items:
        normalized = " ".join(item.lower().split())
        refers_to_geometry = any(
            marker in normalized
            for marker in ("geometry", "uploaded", "file path", "mesh path")
        )
        claims_missing_context = any(
            marker in normalized
            for marker in (
                "not provided",
                "not specified",
                "not explicitly",
                "missing",
                "unknown",
            )
        )
        if refers_to_geometry and claims_missing_context:
            warnings.append(
                "Ignored model geometry ambiguity because a validated GeometrySpec "
                f"was attached: {item}"
            )
        else:
            blocking.append(item)
    return blocking, warnings


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
    geometry_source: str | None = None,
    ambiguities: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "pde_spec": pde.model_dump(mode="json") if pde else {},
        "geometry_spec": geometry.model_dump(mode="json") if geometry else {},
        "typed_spec_source": source,
        "geometry_spec_source": geometry_source or source,
        "typed_spec_ambiguities": ambiguities or [],
        "typed_interpretation_warnings": warnings or [],
    }


def _ensure_boundary_region(geometry: GeometrySpec) -> tuple[GeometrySpec, bool]:
    if any(region.name == "boundary" for region in geometry.regions):
        return geometry, False
    region = RegionSpec(
        name="boundary",
        dimension=geometry.dimension - 1,
        selector=RegionSelector(kind="all_boundary", reference="domain"),
    )
    return geometry.model_copy(update={"regions": [*geometry.regions, region]}), True


def _adapt_pde_to_geometry(
    pde: PDEProblemSpec | None,
    geometry: GeometrySpec,
) -> PDEProblemSpec | None:
    if pde is None:
        return None
    return pde.model_copy(update={"spatial_dimension": geometry.dimension})


def _compact_error(exc: Exception, limit: int = 700) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else f"{text[:limit]}..."
