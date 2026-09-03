from __future__ import annotations

from typing import Literal

from pydantic import Field

from aes_agent.specs.base import StrictModel
from aes_agent.specs.expressions import ExpressionSpec


class EquationSpec(StrictModel):
    family: Literal[
        "stationary_diffusion",
        "transient_diffusion",
        "custom",
    ]
    unknown: str = "u"
    strong_form: str = Field(min_length=1)
    diffusion: ExpressionSpec
    source: ExpressionSpec


class BoundaryConditionSpec(StrictModel):
    name: str = Field(min_length=1)
    region: str = Field(min_length=1)
    type: Literal["dirichlet", "neumann", "robin"]
    value: ExpressionSpec


class InitialConditionSpec(StrictModel):
    value: ExpressionSpec


class TimeSpec(StrictModel):
    t0: float = 0.0
    t_end: float
    dt: float
    scheme: Literal["backward_euler", "crank_nicolson"] = "backward_euler"


class FunctionSpaceSpec(StrictModel):
    family: Literal["Lagrange"] = "Lagrange"
    degree: int = Field(default=1, ge=1, le=5)
    value_shape: list[int] = Field(default_factory=list)


class SolverSpec(StrictModel):
    linear_solver: str = "cg"
    preconditioner: str = "hypre"
    relative_tolerance: float = Field(default=1.0e-8, gt=0)
    maximum_iterations: int = Field(default=1000, ge=1)


class PDEProblemSpec(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    problem_class: Literal["forward_problem"] = "forward_problem"
    spatial_dimension: int = Field(ge=1, le=3)
    equation: EquationSpec
    boundary_conditions: list[BoundaryConditionSpec] = Field(min_length=1)
    initial_condition: InitialConditionSpec | None = None
    time: TimeSpec | None = None
    function_space: FunctionSpaceSpec = Field(default_factory=FunctionSpaceSpec)
    solver: SolverSpec = Field(default_factory=SolverSpec)
    outputs: list[str] = Field(
        default_factory=lambda: ["solution.xdmf", "diagnostics.json"]
    )
    assumptions: list[str] = Field(default_factory=list)
