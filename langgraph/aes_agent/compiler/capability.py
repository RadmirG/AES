from __future__ import annotations

from aes_agent.compiler.weak_form import build_numerical_ir
from aes_agent.specs.compilation import CompilationPlan
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.mesh import MeshArtifact
from aes_agent.specs.pde import PDEProblemSpec


SUPPORTED_EQUATIONS = {"stationary_diffusion", "transient_diffusion"}


def build_compilation_plan(
    pde: PDEProblemSpec,
    geometry: GeometrySpec,
    mesh: MeshArtifact | None = None,
) -> CompilationPlan:
    errors: list[str] = []
    if pde.equation.family not in SUPPORTED_EQUATIONS:
        errors.append(f"Unsupported PDE family: {pde.equation.family}.")
    if geometry.source.kind == "surface_scan":
        errors.append("STL/surface-scan meshing is declared but not implemented.")
    if pde.equation.diffusion.kind != "constant":
        errors.append("The first compiler release supports constant diffusion only.")
    if pde.equation.source.kind != "constant":
        errors.append("The first compiler release supports constant sources only.")
    unsupported_bcs = sorted(
        {
            condition.type
            for condition in pde.boundary_conditions
            if condition.type != "dirichlet"
        }
    )
    if unsupported_bcs:
        errors.append(f"Unsupported boundary-condition types: {unsupported_bcs}.")
    if any(condition.value.kind != "constant" for condition in pde.boundary_conditions):
        errors.append("The first compiler release supports constant Dirichlet data only.")

    if errors:
        return CompilationPlan(status="unsupported", capability_errors=errors)

    mesh_uri = mesh.mesh_uri if mesh else _planned_mesh_uri(geometry)
    return CompilationPlan(
        status="ready",
        numerical_ir=build_numerical_ir(pde),
        mesh_uri=mesh_uri,
        expected_artifacts=["solve.py", "solution.xdmf", "diagnostics.json"],
    )


def _planned_mesh_uri(geometry: GeometrySpec) -> str:
    source = geometry.source
    if source.kind == "primitives" and len(source.primitives) == 1:
        primitive = source.primitives[0]
        if primitive.shape == "rectangle":
            return "builtin://rectangle"
    return "mesh://pending"
