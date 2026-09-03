from __future__ import annotations

import ast
from typing import Any, Literal

from pydantic import Field, ValidationError

from aes_agent.specs.base import StrictModel
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.mesh import MeshArtifact
from aes_agent.specs.pde import PDEProblemSpec


class ValidationReport(StrictModel):
    status: Literal["valid", "invalid"]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_pde_spec(value: dict[str, Any] | PDEProblemSpec) -> tuple[PDEProblemSpec | None, ValidationReport]:
    try:
        spec = value if isinstance(value, PDEProblemSpec) else PDEProblemSpec.model_validate(value)
    except ValidationError as exc:
        return None, ValidationReport(status="invalid", errors=_validation_errors(exc))

    errors: list[str] = []
    warnings: list[str] = []
    transient = spec.equation.family == "transient_diffusion"
    if transient and spec.time is None:
        errors.append("Transient diffusion requires a time specification.")
    if transient and spec.initial_condition is None:
        errors.append("Transient diffusion requires an initial condition.")
    if not transient and (spec.time is not None or spec.initial_condition is not None):
        warnings.append("Stationary diffusion ignores time and initial-condition data.")
    if spec.time is not None:
        if spec.time.t_end <= spec.time.t0:
            errors.append("time.t_end must be greater than time.t0.")
        if spec.time.dt <= 0:
            errors.append("time.dt must be positive.")
        elif spec.time.dt > spec.time.t_end - spec.time.t0:
            errors.append("time.dt must not exceed the simulated time interval.")
    for expression, label in (
        (spec.equation.diffusion, "diffusion coefficient"),
        (spec.equation.source, "source"),
    ):
        if expression.kind == "constant":
            try:
                numeric = float(expression.value)
            except ValueError:
                errors.append(f"The constant {label} is not numeric.")
                continue
            if label == "diffusion coefficient" and numeric <= 0:
                errors.append("The diffusion coefficient must be positive.")
        else:
            errors.extend(_validate_expression(expression.value, label))
    report = ValidationReport(
        status="invalid" if errors else "valid",
        errors=errors,
        warnings=warnings,
    )
    return spec, report


def validate_geometry_spec(value: dict[str, Any] | GeometrySpec) -> tuple[GeometrySpec | None, ValidationReport]:
    try:
        spec = value if isinstance(value, GeometrySpec) else GeometrySpec.model_validate(value)
    except ValidationError as exc:
        return None, ValidationReport(status="invalid", errors=_validation_errors(exc))

    errors: list[str] = []
    warnings: list[str] = []
    names = [region.name for region in spec.regions]
    if len(names) != len(set(names)):
        errors.append("Geometry region names must be unique.")
    if any(region.dimension > spec.dimension for region in spec.regions):
        errors.append("A region dimension cannot exceed the geometry dimension.")
    if spec.source.kind in {"primitives", "csg"}:
        primitive_ids = [item.id for item in spec.source.primitives]
        if len(primitive_ids) != len(set(primitive_ids)):
            errors.append("Primitive identifiers must be unique.")
        if spec.source.kind == "csg":
            known = set(primitive_ids)
            for operation in spec.source.operations:
                missing = [name for name in [*operation.objects, *operation.tools] if name not in known]
                if missing:
                    errors.append(
                        f"CSG operation {operation.result!r} references unknown objects: {missing}."
                    )
                if not operation.tools:
                    errors.append(
                        f"CSG operation {operation.result!r} requires at least one tool object."
                    )
                known.add(operation.result)
        for primitive in spec.source.primitives:
            errors.extend(_validate_primitive(primitive.shape, primitive.model_dump(), spec.dimension))
    if spec.source.kind in {"cad", "mesh_file", "surface_scan"}:
        suffix = spec.source.artifact_path.rsplit(".", 1)[-1].lower()
        if suffix != spec.source.format:
            aliases = ({"step", "stp"}, {"iges", "igs"})
            if not any(suffix in group and spec.source.format in group for group in aliases):
                errors.append(
                    f"Geometry format {spec.source.format!r} does not match file suffix {suffix!r}."
                )
    if spec.source.kind == "surface_scan":
        warnings.append(
            "STL/surface-scan reconstruction is declared but not implemented in this release."
        )
    region_names = set(names)
    expected_cell_types = {
        1: {"line"},
        2: {"triangle", "quadrilateral"},
        3: {"tetrahedron", "hexahedron"},
    }[spec.dimension]
    if spec.mesh.cell_type not in expected_cell_types:
        errors.append(
            f"Cell type {spec.mesh.cell_type!r} is incompatible with {spec.dimension}D geometry."
        )
    for region in spec.regions:
        selector = region.selector
        if selector.kind in {"object", "boundary_of"} and not selector.reference:
            errors.append(f"Region {region.name!r} requires selector.reference.")
        if selector.kind == "bounding_box" and len(selector.bounds or []) not in {4, 6}:
            errors.append(f"Region {region.name!r} bounding_box requires 4 or 6 values.")
        if selector.kind == "entity_tags" and not selector.entity_tags:
            errors.append(f"Region {region.name!r} entity_tags selector is empty.")
    for refinement in spec.mesh.refinements:
        if refinement.region not in region_names:
            errors.append(
                f"Mesh refinement references unknown region {refinement.region!r}."
            )
    report = ValidationReport(
        status="invalid" if errors else "valid",
        errors=errors,
        warnings=warnings,
    )
    return spec, report


def cross_validate_pde_geometry(
    pde: PDEProblemSpec,
    geometry: GeometrySpec,
) -> ValidationReport:
    errors: list[str] = []
    if pde.spatial_dimension != geometry.dimension:
        errors.append(
            f"PDE dimension {pde.spatial_dimension} does not match geometry dimension {geometry.dimension}."
        )
    regions = {region.name: region for region in geometry.regions}
    for condition in pde.boundary_conditions:
        region = regions.get(condition.region)
        if region is None:
            errors.append(
                f"Boundary condition {condition.name!r} references unknown geometry region {condition.region!r}."
            )
        elif region.dimension != geometry.dimension - 1:
            errors.append(
                f"Boundary region {condition.region!r} must have dimension {geometry.dimension - 1}."
            )
    return ValidationReport(status="invalid" if errors else "valid", errors=errors)


def _validate_primitive(shape: str, value: dict[str, Any], dimension: int) -> list[str]:
    errors: list[str] = []
    expected_dimension = 2 if shape in {"rectangle", "disk"} else 3
    if dimension != expected_dimension:
        errors.append(
            f"Primitive {shape!r} is {expected_dimension}D but GeometrySpec.dimension is {dimension}."
        )
    for field in ("size", "axis"):
        vector = value.get(field)
        if vector is not None and len(vector) != expected_dimension:
            errors.append(
                f"Primitive {shape!r} field {field!r} requires {expected_dimension} values."
            )
    for field in ("origin", "center"):
        vector = value.get(field)
        if vector is not None and len(vector) != expected_dimension:
            errors.append(
                f"Primitive {shape!r} field {field!r} requires {expected_dimension} values."
            )
    if shape in {"rectangle", "box"} and any(item <= 0 for item in value.get("size") or []):
        errors.append(f"Primitive {shape!r} size values must be positive.")
    if shape == "cylinder" and not any(abs(item) > 0 for item in value.get("axis") or []):
        errors.append("Cylinder axis must have non-zero length.")
    return errors


def cross_validate_pde_mesh(
    pde: PDEProblemSpec,
    mesh: MeshArtifact,
) -> ValidationReport:
    errors: list[str] = []
    if pde.spatial_dimension != mesh.dimension:
        errors.append(
            f"PDE dimension {pde.spatial_dimension} does not match mesh dimension {mesh.dimension}."
        )
    available = set(mesh.tag_map)
    required = {condition.region for condition in pde.boundary_conditions}
    missing = sorted(required - available)
    if missing:
        errors.append(f"Mesh is missing PDE boundary regions: {missing}.")
    if mesh.quality.status != "valid":
        errors.append("Mesh quality report is not valid.")
    return ValidationReport(status="invalid" if errors else "valid", errors=errors)


def _validate_expression(source: str, label: str) -> list[str]:
    normalized = source.replace("^", "**")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        return [f"Invalid {label} expression: {exc.msg}."]
    allowed_names = {"x", "y", "z", "t", "pi", "sin", "cos", "exp", "sqrt"}
    invalid = sorted(
        {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id not in allowed_names
        }
    )
    return [f"Unsupported symbols in {label}: {invalid}."] if invalid else []


def _validation_errors(exc: ValidationError) -> list[str]:
    errors = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        errors.append(f"{location}: {item.get('msg', 'invalid value')}")
    return errors
