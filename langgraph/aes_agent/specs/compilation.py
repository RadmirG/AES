from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from aes_agent.specs.base import StrictModel


class WeakFormTerm(StrictModel):
    side: Literal["bilinear", "linear"]
    operator: Literal["mass", "diffusion", "source", "neumann", "robin"]
    coefficient: str = "1"
    field: str | None = None
    region: str | None = None


class NumericalIR(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    equation_family: Literal["stationary_diffusion", "transient_diffusion"]
    spatial_dimension: int = Field(ge=1, le=3)
    unknown: str
    terms: list[WeakFormTerm] = Field(min_length=1)
    boundary_conditions: list[dict[str, Any]] = Field(default_factory=list)
    time: dict[str, Any] | None = None


class CompilationPlan(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["ready", "unsupported"]
    backend: Literal["dolfinx"] = "dolfinx"
    compiler_version: str = "0.1.0"
    numerical_ir: NumericalIR | None = None
    mesh_uri: str | None = None
    expected_artifacts: list[str] = Field(default_factory=list)
    capability_errors: list[str] = Field(default_factory=list)
