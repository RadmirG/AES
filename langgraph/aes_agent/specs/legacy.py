from __future__ import annotations

import re
from typing import Any

from aes_agent.specs.expressions import expression_from_text
from aes_agent.specs.geometry import (
    CADGeometrySource,
    GeometrySpec,
    MeshFileGeometrySource,
    MeshRequirements,
    PrimitiveGeometrySource,
    PrimitiveSpec,
    RegionSelector,
    RegionSpec,
    SurfaceScanGeometrySource,
)
from aes_agent.specs.pde import (
    BoundaryConditionSpec,
    EquationSpec,
    InitialConditionSpec,
    PDEProblemSpec,
    TimeSpec,
)


def build_legacy_specs(state: dict[str, Any]) -> tuple[PDEProblemSpec | None, GeometrySpec | None]:
    """Convert the current string-valued state into typed compatibility specs."""

    pde = _build_pde_spec(state)
    geometry = _build_geometry_spec(state)
    return pde, geometry


def _build_pde_spec(state: dict[str, Any]) -> PDEProblemSpec | None:
    pde_info = str(state.get("pde_info", "")).lower()
    if pde_info == "stationary_diffusion_equation":
        family = "stationary_diffusion"
        strong_form = "-div(k * grad(u)) = f"
    elif pde_info == "time_dependent_heat_equation":
        family = "transient_diffusion"
        strong_form = "du/dt - div(k * grad(u)) = f"
    else:
        return None

    raw = str(state.get("raw_user_input", ""))
    dimension = _spatial_dimension(state)
    spatial_variables = ["x", "y", "z"][:dimension]
    coefficient = _explicit_named_scalar(
        raw,
        ("alpha", "a", "k", "diffusion coefficient"),
    ) or _clean_scalar(state.get("coefficient_info"), default="1")
    source = _explicit_named_scalar(raw, ("f", "source")) or _clean_scalar(
        state.get("source_info"),
        default="0",
    )
    boundary_value = _boundary_value(raw)
    boundary_type = _boundary_type(str(state.get("bc_info", "")))

    initial = None
    time = None
    if family == "transient_diffusion":
        initial_text = str(state.get("initial_condition_info", "")).strip()
        if initial_text and not initial_text.startswith("unknown_"):
            initial = InitialConditionSpec(
                value=expression_from_text(
                    _normalize_math_expression(initial_text),
                    variables=spatial_variables,
                )
            )
        parsed_time = _parse_time(str(state.get("time_info", "")), raw)
        if parsed_time:
            time = TimeSpec(**parsed_time)

    try:
        return PDEProblemSpec(
            spatial_dimension=dimension,
            equation=EquationSpec(
                family=family,
                strong_form=strong_form,
                diffusion=expression_from_text(coefficient, variables=spatial_variables),
                source=expression_from_text(source, variables=[*spatial_variables, "t"]),
            ),
            boundary_conditions=[
                BoundaryConditionSpec(
                    name="primary_boundary_condition",
                    region="boundary",
                    type=boundary_type,
                    value=expression_from_text(
                        boundary_value,
                        variables=[*spatial_variables, "t"],
                    ),
                )
            ],
            initial_condition=initial,
            time=time,
        )
    except ValueError:
        return None


def _build_geometry_spec(state: dict[str, Any]) -> GeometrySpec | None:
    raw = str(state.get("raw_user_input", ""))
    file_source = _file_geometry_source(raw)
    dimension = _spatial_dimension(state)
    if file_source is not None:
        cell_type = "triangle" if dimension == 2 else "tetrahedron"
        return GeometrySpec(
            dimension=dimension,
            source=file_source,
            regions=_default_regions(dimension),
            mesh=MeshRequirements(
                cell_type=cell_type,
                global_size=0.05,
            ),
        )

    domain_info = str(state.get("domain_info", "")).lower()
    if domain_info not in {"unit_square", "rectangular_domain", "rectangle"}:
        return None

    x0, x1, y0, y1 = _rectangle_bounds(raw)
    source = PrimitiveGeometrySource(
        primitives=[
            PrimitiveSpec(
                id="domain",
                shape="rectangle",
                origin=[x0, y0],
                size=[x1 - x0, y1 - y0],
            )
        ]
    )
    return GeometrySpec(
        dimension=2,
        source=source,
        regions=_default_regions(2),
        mesh=MeshRequirements(cell_type="triangle", global_size=1.0 / 32.0),
        metadata={"compatibility_source": "legacy_agent_state"},
    )


def _file_geometry_source(raw: str):
    match = re.search(r"([^\s'\"]+\.(step|stp|brep|iges|igs|msh|xdmf|stl|obj|ply))", raw, re.I)
    if not match:
        return None
    path = match.group(1)
    suffix = match.group(2).lower()
    if suffix in {"step", "stp", "brep", "iges", "igs"}:
        return CADGeometrySource(format=suffix, artifact_path=path)
    if suffix in {"msh", "xdmf"}:
        return MeshFileGeometrySource(format=suffix, artifact_path=path)
    return SurfaceScanGeometrySource(format=suffix, artifact_path=path)


def _default_regions(dimension: int) -> list[RegionSpec]:
    return [
        RegionSpec(
            name="domain",
            dimension=dimension,
            selector=RegionSelector(kind="object", reference="domain"),
        ),
        RegionSpec(
            name="boundary",
            dimension=dimension - 1,
            selector=RegionSelector(kind="all_boundary", reference="domain"),
        ),
    ]


def _rectangle_bounds(raw: str) -> tuple[float, float, float, float]:
    match = re.search(
        r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]\s*[x×]\s*"
        r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]",
        raw,
        re.I,
    )
    if not match:
        return 0.0, 1.0, 0.0, 1.0
    return tuple(float(match.group(index)) for index in range(1, 5))  # type: ignore[return-value]


def _parse_time(time_info: str, raw: str) -> dict[str, float] | None:
    # Explicit values in the user's request take precedence over a model-created
    # legacy summary when both contain a parseable time value.
    text = f"{raw} {time_info}"
    number = r"[-+]?(?:\d+\.\d+|\d+|\.\d+)(?:[eE][-+]?\d+)?"
    start = re.search(
        rf"(?:t_0|t0|initial\s+time|start\s+time)\s*=\s*({number})",
        text,
        re.I,
    )
    end = re.search(
        rf"(?:t_end|final\s+time(?:\s+T)?|T)\s*=\s*({number})",
        text,
        re.I,
    )
    step = re.search(rf"(?:dt|time\s+step)\s*=\s*({number})", text, re.I)
    if not end or not step:
        return None
    return {
        "t0": float(start.group(1)) if start else 0.0,
        "t_end": float(end.group(1)),
        "dt": float(step.group(1)),
    }


def _boundary_value(raw: str) -> str:
    if re.search(r"homogeneous\s+dirichlet|u\s*=\s*0", raw, re.I):
        return "0"
    match = re.search(r"\bg\s*=\s*(-?\d+(?:\.\d+)?)", raw, re.I)
    return match.group(1) if match else "0"


def _boundary_type(value: str) -> str:
    lowered = value.lower()
    if "neumann" in lowered:
        return "neumann"
    if "robin" in lowered:
        return "robin"
    return "dirichlet"


def _spatial_dimension(state: dict[str, Any]) -> int:
    text = f"{state.get('raw_user_input', '')} {state.get('domain_info', '')}".lower()
    if "2d" in text or "r^2" in text or "unit_square" in text or "rectangle" in text:
        return 2
    if "3d" in text or "r^3" in text or "cube" in text:
        return 3
    if "1d" in text or "interval" in text:
        return 1
    return 2


def _clean_scalar(value: Any, *, default: str) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("unknown_"):
        return default
    match = re.search(r"(?:=\s*)?(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$", text)
    return match.group(1) if match else text


def _explicit_named_scalar(raw: str, names: tuple[str, ...]) -> str:
    number = r"[-+]?(?:\d+\.\d+|\d+|\.\d+)(?:[eE][-+]?\d+)?"
    matches: list[tuple[int, str]] = []
    for name in names:
        pattern = rf"(?<![\w]){re.escape(name)}\s*(?:=|is)\s*({number})"
        matches.extend(
            (match.start(), match.group(1))
            for match in re.finditer(pattern, raw, re.IGNORECASE)
        )
    return max(matches, default=(-1, ""), key=lambda item: item[0])[1]


def _normalize_math_expression(value: str) -> str:
    normalized = value.strip()
    normalized = re.sub(r"\bsin\(pi([xyz])\)", r"sin(pi*\1)", normalized)
    normalized = re.sub(r"\)(?=(?:sin|cos|exp|sqrt)\s*\()", ")*", normalized)
    return normalized
