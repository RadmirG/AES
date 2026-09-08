from __future__ import annotations

import logging
import os
import re
from typing import Any

from pydantic import Field

from aes_agent.compiler.capability import build_compilation_plan
from aes_agent.helpers import ollama_json
from aes_agent.prompts import (
    interpret_pde_for_geometry_prompt,
    interpret_typed_problem_prompt,
)
from aes_agent.specs.base import StrictModel
from aes_agent.specs.expressions import expression_from_text
from aes_agent.specs.geometry import GeometrySpec, RegionSelector, RegionSpec
from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.specs.pde import BoundaryConditionSpec, PDEProblemSpec
from aes_agent.specs.request_evidence import initial_condition_clauses, without_initial_conditions
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
    "homogeneous neumann",
    "zero flux",
    "remaining boundaries",
    "remaining surfaces",
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
    fallback_pde, fallback_boundary_warnings = _reconcile_explicit_boundary_conditions(
        fallback_pde,
        requested_geometry or fallback_geometry,
        str(state.get("raw_user_input", "")),
    )
    scope_ambiguities = _initial_condition_scope_ambiguities(
        fallback_pde, requested_geometry or fallback_geometry, str(state.get("raw_user_input", "")),
    )
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
            warnings=[*requested_geometry_warnings, *fallback_boundary_warnings],
            ambiguities=scope_ambiguities,
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
    pde, pde_error = _parse_pde(
        response.get("pde_spec") if isinstance(response, dict) else None
    )
    if requested_geometry is not None:
        geometry, geometry_error = requested_geometry, ""
    else:
        geometry, geometry_error = _parse_geometry(
            response.get("geometry_spec") if isinstance(response, dict) else None
        )
    pde, explicit_value_warnings = _reconcile_interpreted_pde(
        pde,
        fallback_pde,
        requested_geometry,
        str(state.get("raw_user_input", "")),
    )
    raw_ambiguities = (
        _strings(response.get("ambiguities"))
        if isinstance(response, dict)
        else []
    )
    ambiguities, default_warnings = _partition_ambiguities(raw_ambiguities)
    ambiguities, evidence_warnings = _partition_explicit_value_ambiguities(
        ambiguities,
        fallback_pde,
        str(state.get("raw_user_input", "")),
    )
    default_warnings.extend(evidence_warnings)
    if requested_geometry is not None:
        ambiguities, context_warnings = _partition_supplied_geometry_ambiguities(
            ambiguities
        )
        default_warnings.extend(context_warnings)
        ambiguities, natural_boundary_warnings = _partition_natural_boundary_ambiguities(
            ambiguities,
            pde or fallback_pde,
            requested_geometry,
            str(state.get("raw_user_input", "")),
        )
        default_warnings.extend(natural_boundary_warnings)

    scope_ambiguities = _initial_condition_scope_ambiguities(
        pde or fallback_pde, geometry, str(state.get("raw_user_input", "")),
    )
    ambiguities.extend(item for item in scope_ambiguities if item not in ambiguities)

    if pde is not None and geometry is not None:
        logger.info(
            "Typed problem interpretation completed: source=llm_structured_extraction "
            "pde_family=%s geometry_source=%s blocking_ambiguities=%s accepted_defaults=%s",
            pde.equation.family,
            geometry.source.kind,
            len(ambiguities),
            len(default_warnings) + len(explicit_value_warnings),
        )
        return _interpretation_result(
            pde,
            geometry,
            source="llm_structured_extraction",
            geometry_source=("request_context" if requested_geometry else "llm_structured_extraction"),
            ambiguities=ambiguities,
            warnings=[
                *requested_geometry_warnings,
                *explicit_value_warnings,
                *default_warnings,
            ],
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
            ambiguities=scope_ambiguities,
            warnings=[
                "LLM structured interpretation was unusable; AES used the deterministic "
                "compatibility extractor.",
                *failures,
                *requested_geometry_warnings,
                *fallback_boundary_warnings,
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
        normalized = " ".join(item.lower().replace("_", " ").split())
        refers_to_geometry = any(
            marker in normalized
            for marker in ("geometry", "uploaded", "file path", "mesh path")
        )
        claims_missing_context = (
            normalized
            in {
                "domain geometry specification",
                "domain geometry file",
                "geometry specification",
                "domain geometry file path",
                "geometry file path",
                "geometry path",
                "mesh path",
                "uploaded geometry",
            }
            or any(
                marker in normalized
                for marker in (
                    "not provided",
                    "not specified",
                    "did not specify",
                    "not supplied",
                    "not given",
                    "not explicitly",
                    "missing",
                    "unknown",
                )
            )
        )
        confirms_region_mapping = (
            "mapped" in normalized
            and any(
                marker in normalized
                for marker in ("contains a region", "provided geometry", "attached geometry")
            )
        )
        if refers_to_geometry and claims_missing_context:
            warnings.append(
                "Ignored model geometry ambiguity because a validated "
                f"GeometrySpec was attached: {item}"
            )
        elif refers_to_geometry and confirms_region_mapping:
            warnings.append(
                "Ignored non-blocking model geometry note because a validated "
                f"GeometrySpec was attached: {item}"
            )
        else:
            blocking.append(item)
    return blocking, warnings


def _partition_natural_boundary_ambiguities(
    items: list[str],
    pde: PDEProblemSpec | None,
    geometry: GeometrySpec,
    raw_user_input: str,
) -> tuple[list[str], list[str]]:
    """Treat omitted boundary portions as the FEM natural zero-flux condition."""

    boundary_text = (
        without_initial_conditions(raw_user_input)
        if pde is not None and pde.equation.family == "transient_diffusion"
        else raw_user_input
    )
    explicit, unresolved = _explicit_dirichlet_conditions(boundary_text, geometry)
    if pde is None or not explicit or unresolved:
        return items, []
    if any(condition.region == "boundary" for condition in explicit):
        return items, []

    blocking: list[str] = []
    warnings: list[str] = []
    for item in items:
        normalized = " ".join(item.lower().replace("_", " ").split())
        refers_to_unassigned_boundary = any(
            marker in normalized
            for marker in (
                "remaining boundaries",
                "remaining boundary",
                "remaining surfaces",
                "remaining surface",
                "finned surfaces",
                "unassigned boundaries",
                "unassigned surfaces",
            )
        )
        if refers_to_unassigned_boundary:
            warnings.append(
                "Accepted unspecified boundary portions as homogeneous Neumann "
                f"(zero normal flux), the natural diffusion boundary condition: {item}"
            )
        else:
            blocking.append(item)
    return blocking, warnings


def _partition_explicit_value_ambiguities(
    items: list[str],
    deterministic: PDEProblemSpec | None,
    raw_user_input: str = "",
) -> tuple[list[str], list[str]]:
    """Reject model ambiguity claims contradicted by parsed user values."""

    blocking: list[str] = []
    warnings: list[str] = []
    explicit_time = deterministic.time if deterministic is not None else None
    explicit_initial = (
        deterministic.initial_condition
        if deterministic is not None and _has_explicit_initial_condition(raw_user_input)
        else None
    )
    for item in items:
        normalized = " ".join(item.lower().replace("_", " ").split())
        refers_to_time_values = any(
            marker in normalized
            for marker in (
                "time interval",
                "time step",
                "final time",
                "start time",
                "t end",
                "t0",
                "dt",
            )
        )
        claims_missing_or_defaulted = any(
            marker in normalized
            for marker in (
                "not provided",
                "not specified",
                "did not specify",
                "not specify",
                "not supplied",
                "not given",
                "not explicitly",
                "missing",
                "unknown",
                "used default",
                "defaulted",
                "assumed",
            )
        )
        if explicit_time is not None and refers_to_time_values and claims_missing_or_defaulted:
            warnings.append(
                "Ignored model time ambiguity because AES parsed explicit values "
                f"from the user request (t0={explicit_time.t0:g}, "
                f"T={explicit_time.t_end:g}, dt={explicit_time.dt:g}): {item}"
            )
            continue

        refers_to_initial = "initial condition" in normalized
        asks_for_unused_coordinate_dependence = any(
            marker in normalized
            for marker in (
                "initial condition z dependence",
                "z dependence",
                "z independence",
                "dimension consistency check for initial condition",
            )
        )
        if explicit_initial is not None and (
            (refers_to_initial and claims_missing_or_defaulted)
            or asks_for_unused_coordinate_dependence
        ):
            warnings.append(
                "Ignored model initial-condition ambiguity because AES parsed an "
                "explicit initial field from the user request. A field on a 3D "
                f"domain may validly be independent of z: {item}"
            )
            continue

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


def _reconcile_explicit_boundary_conditions(
    pde: PDEProblemSpec | None,
    geometry: GeometrySpec | None,
    raw_user_input: str,
) -> tuple[PDEProblemSpec | None, list[str]]:
    """Replace model boundary data when the request names values and regions."""

    if pde is None or geometry is None:
        return pde, []
    boundary_text = (
        without_initial_conditions(raw_user_input)
        if pde.equation.family == "transient_diffusion"
        else raw_user_input
    )
    conditions, unresolved = _explicit_dirichlet_conditions(boundary_text, geometry)
    if not conditions or unresolved:
        return pde, []
    if any(condition.region == "boundary" for condition in conditions):
        return pde, []
    if pde.boundary_conditions == conditions:
        return pde, []
    return (
        pde.model_copy(update={"boundary_conditions": conditions}),
        [
            "AES preserved explicitly stated Dirichlet values and semantic "
            "boundary regions instead of conflicting model boundary data."
        ],
    )


def _initial_condition_scope_ambiguities(
    pde: PDEProblemSpec | None,
    geometry: GeometrySpec | None,
    text: str,
) -> list[str]:
    if pde is None or pde.equation.family != "transient_diffusion":
        return []
    issues: list[str] = []
    for clause in initial_condition_clauses(text):
        scope = " ".join(clause.scope.lower().replace("_", " ").split())
        if not scope or re.fullmatch(
            r"(?:the )?(?:(?:whole|entire|attached|uploaded|selected) )?"
            r"(?:domain|volume|geometry|workpiece)", scope,
        ):
            continue
        issues.append(
            f"The initial condition is restricted to '{clause.scope}'. Specify the "
            "initial field throughout the domain (throughout the volume for 3D), "
            "or confirm that this is a boundary value and also provide the volume initial field."
        )
    if issues and geometry is not None:
        boundary_text = without_initial_conditions(text)
        conditions, _ = _explicit_dirichlet_conditions(boundary_text, geometry)
        if not conditions and not re.search(
            r"\b(?:dirichlet|neumann|robin|flux|insulated|adiabatic)\b", boundary_text, re.I,
        ):
            issues.append(
                "No boundary condition is specified separately from the initial condition. "
                "Specify boundary temperatures or normal fluxes and their regions; "
                "for an insulated workpiece, explicitly request zero flux on all boundaries."
            )
    return issues


def _explicit_dirichlet_conditions(
    raw_user_input: str,
    geometry: GeometrySpec,
) -> tuple[list[BoundaryConditionSpec], list[str]]:
    pattern = re.compile(
        r"\bu(?:\s*\([^)]*\))?\s*=\s*(?P<value>.+?)\s+on\s+"
        r"(?P<regions>.+?)"
        r"(?=(?:\s+and\s+u(?:\s*\([^)]*\))?\s*=)|"
        r"(?:,\s*(?:initial|final|time|execute|store|alpha|source|f\s*=)\b)|"
        r"[.;\n]|$)",
        re.IGNORECASE,
    )
    available = {region.name for region in geometry.regions}
    by_region: dict[str, BoundaryConditionSpec] = {}
    unresolved: list[str] = []
    variables = [*(["x", "y", "z"][: geometry.dimension]), "t"]
    for match in pattern.finditer(raw_user_input):
        value = _normalize_explicit_expression(match.group("value"))
        labels = _split_boundary_region_labels(match.group("regions"))
        for label in labels:
            region = _resolve_boundary_region(label, available, geometry.dimension)
            if region is None:
                unresolved.append(label)
                continue
            by_region[region] = BoundaryConditionSpec(
                name=f"explicit_dirichlet_{region}",
                region=region,
                type="dirichlet",
                value=expression_from_text(value, variables=variables),
            )
    return list(by_region.values()), unresolved


def _split_boundary_region_labels(value: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", value.strip())
    labels: list[str] = []
    for item in re.split(r"\s*,\s*|\s+and\s+", normalized, flags=re.IGNORECASE):
        cleaned = re.sub(r"^and\s+", "", item.strip(" ,"), flags=re.IGNORECASE)
        if cleaned:
            labels.append(cleaned)
    return labels


def _resolve_boundary_region(
    label: str,
    available: set[str],
    dimension: int,
) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    normalized = re.sub(r"^the_", "", normalized)
    if normalized in {
        "boundary",
        "complete_boundary",
        "entire_boundary",
        "whole_boundary",
        "all_boundary",
        "all_boundaries",
        "all_exterior_boundaries",
    }:
        return "boundary" if "boundary" in available else None
    if normalized in available:
        return normalized
    without_suffix = re.sub(r"_(?:boundary|surface|face)$", "", normalized)
    if without_suffix in available:
        return without_suffix
    if without_suffix in {"bottom", "base", "base_bottom"}:
        candidates = ["base_bottom", "z_min" if dimension == 3 else "y_min"]
        return next((candidate for candidate in candidates if candidate in available), None)
    return None


def _normalize_explicit_expression(value: str) -> str:
    normalized = value.strip().strip("`$ ")
    normalized = normalized.replace("^", "**")
    normalized = re.sub(r"\bsin\(pi([xyz])\)", r"sin(pi*\1)", normalized)
    normalized = re.sub(r"\)(?=(?:sin|cos|exp|sqrt)\s*\()", ")*", normalized)
    # Coordinate products are common in compact engineering notation (for example xy/20).
    normalized = re.sub(r"\b([xyz])([xyz])\b", r"\1*\2", normalized)
    return normalized


def _reconcile_interpreted_pde(
    interpreted: PDEProblemSpec | None,
    deterministic: PDEProblemSpec | None,
    authoritative_geometry: GeometrySpec | None,
    raw_user_input: str,
) -> tuple[PDEProblemSpec | None, list[str]]:
    """Reconcile an LLM candidate with authoritative deterministic evidence."""

    if interpreted is None:
        return None, []

    reconciled = interpreted
    warnings: list[str] = []

    if (
        authoritative_geometry is not None
        and reconciled.spatial_dimension != authoritative_geometry.dimension
    ):
        model_dimension = reconciled.spatial_dimension
        reconciled = reconciled.model_copy(
            update={"spatial_dimension": authoritative_geometry.dimension}
        )
        warnings.append(
            "AES corrected the model PDE dimension from "
            f"{model_dimension} to {authoritative_geometry.dimension} because the "
            "validated attached GeometrySpec is authoritative."
        )

    reconciled, time_warnings = _preserve_explicit_time_values(
        reconciled,
        deterministic,
    )
    warnings.extend(time_warnings)
    if reconciled is None or deterministic is None:
        return reconciled, warnings

    equation_updates: dict[str, Any] = {}
    if _has_explicit_diffusion(raw_user_input) and (
        reconciled.equation.diffusion != deterministic.equation.diffusion
    ):
        equation_updates["diffusion"] = deterministic.equation.diffusion
        warnings.append(
            "AES preserved the explicitly stated diffusion coefficient instead "
            "of the conflicting model value."
        )
    if _has_explicit_source(raw_user_input) and (
        reconciled.equation.source != deterministic.equation.source
    ):
        equation_updates["source"] = deterministic.equation.source
        warnings.append(
            "AES preserved the explicitly stated source instead of the conflicting "
            "model value."
        )
    if equation_updates:
        reconciled = reconciled.model_copy(
            update={
                "equation": reconciled.equation.model_copy(update=equation_updates)
            }
        )

    reconciled, boundary_warnings = _reconcile_explicit_boundary_conditions(
        reconciled,
        authoritative_geometry,
        raw_user_input,
    )
    warnings.extend(boundary_warnings)

    if (
        _has_explicit_initial_condition(raw_user_input)
        and deterministic.initial_condition is not None
        and reconciled.initial_condition != deterministic.initial_condition
    ):
        reconciled = reconciled.model_copy(
            update={"initial_condition": deterministic.initial_condition}
        )
        warnings.append(
            "AES restored the explicitly stated initial condition that was omitted "
            "or changed by the model."
        )

    if (
        _has_explicit_aggregate_boundary_condition(raw_user_input)
        and reconciled.boundary_conditions != deterministic.boundary_conditions
    ):
        reconciled = reconciled.model_copy(
            update={"boundary_conditions": deterministic.boundary_conditions}
        )
        warnings.append(
            "AES preserved the explicitly stated whole-boundary condition instead "
            "of the conflicting model value."
        )

    return reconciled, warnings


def _has_explicit_diffusion(text: str) -> bool:
    return bool(
        re.search(
            r"(?<![\w])(?:alpha|a|k)(?:\s*\([^)]*\))?\s*(?:=|is)|"
            r"\bdiffusion\s+coefficient\s*(?:=|is)",
            text,
            re.IGNORECASE,
        )
    )


def _has_explicit_source(text: str) -> bool:
    return bool(
        re.search(
            r"(?<![\w])(?:f|source)\s*(?:=|is)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"-?\s*(?:[a-zA-Z]\w*(?:\([^)]*\))?\s*\*?\s*)?"
            r"(?:delta|laplacian)\s*\(\s*u\s*\)\s*=",
            text,
            re.IGNORECASE,
        )
    )


def _has_explicit_initial_condition(text: str) -> bool:
    return bool(
        re.search(r"\binitial\s+condition\b", text, re.IGNORECASE)
        or re.search(r"\binitial\s+temperature\b", text, re.IGNORECASE)
        or re.search(r"\bu\s*\([^)]*,\s*0\s*\)\s*=", text, re.IGNORECASE)
    )


def _has_explicit_aggregate_boundary_condition(text: str) -> bool:
    return bool(
        re.search(r"\bhomogeneous\s+dirichlet\b", text, re.IGNORECASE)
        or re.search(
            r"\bdirichlet\b[^.\n]*\b(?:the\s+)?boundary\b",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"\bu\s*=\s*[^,;.\n]+\s+on\s+(?:the\s+)?boundary\b",
            text,
            re.IGNORECASE,
        )
    )


def _preserve_explicit_time_values(
    interpreted: PDEProblemSpec | None,
    deterministic: PDEProblemSpec | None,
) -> tuple[PDEProblemSpec | None, list[str]]:
    if (
        interpreted is None
        or deterministic is None
        or deterministic.time is None
    ):
        return interpreted, []

    explicit = deterministic.time
    parsed = interpreted.time
    retained_assumptions = [
        assumption
        for assumption in interpreted.assumptions
        if not (
            "assum" in assumption.lower()
            and any(
                marker in assumption.lower()
                for marker in ("dt", "time step", "t_end", "final time")
            )
        )
    ]
    removed_false_assumption = len(retained_assumptions) != len(interpreted.assumptions)
    if parsed is None:
        corrected = interpreted.model_copy(
            update={"time": explicit, "assumptions": retained_assumptions}
        )
        return corrected, [
            "AES restored explicitly stated time values that were omitted from "
            f"the model interpretation (t0={explicit.t0:g}, "
            f"T={explicit.t_end:g}, dt={explicit.dt:g})."
        ]

    conflicting_values = not (
        parsed.t0 == explicit.t0
        and parsed.t_end == explicit.t_end
        and parsed.dt == explicit.dt
    )
    if not conflicting_values and not removed_false_assumption:
        return interpreted, []

    corrected_time = parsed.model_copy(
        update={"t0": explicit.t0, "t_end": explicit.t_end, "dt": explicit.dt}
    )
    corrected = interpreted.model_copy(
        update={"time": corrected_time, "assumptions": retained_assumptions}
    )
    warnings = []
    if conflicting_values:
        warnings.append(
            "AES preserved explicitly stated time values from the user request "
            f"(T={explicit.t_end:g}, dt={explicit.dt:g}) instead of conflicting "
            "model-extracted values."
        )
    if removed_false_assumption:
        warnings.append(
            "AES discarded model assumptions that incorrectly described explicit "
            "time values as unspecified."
        )
    return corrected, warnings


def _compact_error(exc: Exception, limit: int = 700) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else f"{text[:limit]}..."
