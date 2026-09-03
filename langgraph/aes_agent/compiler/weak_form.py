from __future__ import annotations

from aes_agent.specs.compilation import NumericalIR, WeakFormTerm
from aes_agent.specs.pde import PDEProblemSpec


def build_numerical_ir(spec: PDEProblemSpec) -> NumericalIR:
    diffusion = spec.equation.diffusion.value
    source = spec.equation.source.value
    if spec.equation.family == "stationary_diffusion":
        terms = [
            WeakFormTerm(side="bilinear", operator="diffusion", coefficient=diffusion),
            WeakFormTerm(side="linear", operator="source", coefficient=source),
        ]
        time = None
    elif spec.equation.family == "transient_diffusion":
        terms = [
            WeakFormTerm(side="bilinear", operator="mass", coefficient="1"),
            WeakFormTerm(side="bilinear", operator="diffusion", coefficient=diffusion),
            WeakFormTerm(side="linear", operator="mass", coefficient="1", field="u_previous"),
            WeakFormTerm(side="linear", operator="source", coefficient=source),
        ]
        time = spec.time.model_dump(mode="json") if spec.time else None
    else:
        raise ValueError(f"Unsupported equation family: {spec.equation.family}")

    boundary_conditions = [
        condition.model_dump(mode="json") for condition in spec.boundary_conditions
    ]
    return NumericalIR(
        equation_family=spec.equation.family,
        spatial_dimension=spec.spatial_dimension,
        unknown=spec.equation.unknown,
        terms=terms,
        boundary_conditions=boundary_conditions,
        time=time,
    )
