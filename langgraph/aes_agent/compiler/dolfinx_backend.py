from __future__ import annotations

import ast
import json
import re
from typing import Any

from aes_agent.specs.compilation import CompilationPlan
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.mesh import MeshArtifact
from aes_agent.specs.pde import PDEProblemSpec


COMPILER_VERSION = "0.1.0"


def compile_dolfinx(
    pde: PDEProblemSpec,
    geometry: GeometrySpec,
    plan: CompilationPlan,
    mesh: MeshArtifact | None = None,
) -> str:
    if plan.status != "ready" or plan.numerical_ir is None:
        raise ValueError("Compilation plan is not ready.")

    mesh_setup = _mesh_setup(geometry, mesh)
    bc_setup = _boundary_setup(pde, geometry, mesh)
    common = _common_prefix(mesh_setup, pde)
    if pde.equation.family == "stationary_diffusion":
        body = _stationary_body(pde, bc_setup)
    elif pde.equation.family == "transient_diffusion":
        body = _transient_body(pde, bc_setup)
    else:
        raise ValueError(f"Unsupported equation family: {pde.equation.family}")
    code = common + body
    ast.parse(code)
    return code


def _common_prefix(mesh_setup: str, pde: PDEProblemSpec) -> str:
    return f'''from pathlib import Path
import json
import numpy as np
import ufl
from mpi4py import MPI
from petsc4py import PETSc
from dolfinx import fem, io, mesh, plot
from dolfinx.fem.petsc import LinearProblem

COMPILER = "aes-dolfinx-{COMPILER_VERSION}"
{mesh_setup}
V = fem.functionspace(msh, ("{pde.function_space.family}", {pde.function_space.degree}))
u = ufl.TrialFunction(V)
v = ufl.TestFunction(V)
vtk_topology, vtk_cell_types, vtk_coordinates = plot.vtk_mesh(V)
field_topology = {{
    "format": "vtk_cell_array",
    "cells": vtk_topology.tolist(),
    "cell_types": vtk_cell_types.tolist(),
    "cell_count": int(len(vtk_cell_types)),
    "topological_dimension": int(msh.topology.dim),
}}

def field_values(function):
    function.x.scatter_forward()
    values = np.real(function.x.array)
    if len(values) != len(vtk_coordinates):
        raise RuntimeError(
            f"VTK point/value mismatch: {{len(vtk_coordinates)}} points, {{len(values)}} values"
        )
    return values.tolist()
'''


def _mesh_setup(geometry: GeometrySpec, mesh_artifact: MeshArtifact | None) -> str:
    if mesh_artifact is not None and not mesh_artifact.mesh_uri.startswith("builtin://"):
        return '''from dolfinx.io import gmsh as gmshio
mesh_data = gmshio.read_from_msh("mesh.msh", MPI.COMM_WORLD, rank=0, gdim=%d)
if hasattr(mesh_data, "mesh"):
    msh = mesh_data.mesh
    cell_tags = mesh_data.cell_tags
    facet_tags = mesh_data.facet_tags
else:
    msh, cell_tags, facet_tags = mesh_data
''' % geometry.dimension

    source = geometry.source
    if source.kind != "primitives" or len(source.primitives) != 1:
        raise ValueError("A generated mesh artifact is required for non-primitive geometry.")
    primitive = source.primitives[0]
    if primitive.shape != "rectangle" or primitive.origin is None or primitive.size is None:
        raise ValueError("The built-in compiler currently supports rectangle primitives only.")
    x0, y0 = primitive.origin[:2]
    width, height = primitive.size[:2]
    nx = max(1, int(round(width / geometry.mesh.global_size)))
    ny = max(1, int(round(height / geometry.mesh.global_size)))
    return f'''msh = mesh.create_rectangle(
    MPI.COMM_WORLD,
    [np.array([{x0}, {y0}]), np.array([{x0 + width}, {y0 + height}])],
    [{nx}, {ny}],
    cell_type=mesh.CellType.triangle,
)
facet_tags = None
'''


def _boundary_setup(
    pde: PDEProblemSpec,
    geometry: GeometrySpec,
    mesh_artifact: MeshArtifact | None,
) -> str:
    snippets: list[str] = []
    regions = {region.name: region for region in geometry.regions}
    for index, condition in enumerate(pde.boundary_conditions):
        value = _constant_number(condition.value.value, "Dirichlet boundary value")
        region = regions.get(condition.region)
        is_all_boundary = region is not None and region.selector.kind == "all_boundary"
        if (
            mesh_artifact is None
            or mesh_artifact.mesh_uri.startswith("builtin://")
            or is_all_boundary
        ):
            locate = f'''facets_{index} = mesh.locate_entities_boundary(
    msh, msh.topology.dim - 1, lambda x: np.full(x.shape[1], True, dtype=bool)
)
dofs_{index} = fem.locate_dofs_topological(V, msh.topology.dim - 1, facets_{index})
'''
        else:
            tag = mesh_artifact.tag_map.get(condition.region)
            if tag is None:
                raise ValueError(f"Mesh tag not found for boundary {condition.region!r}.")
            locate = f'''facets_{index} = facet_tags.find({tag})
dofs_{index} = fem.locate_dofs_topological(V, msh.topology.dim - 1, facets_{index})
'''
        snippets.append(
            locate
            + f'''bc_{index} = fem.dirichletbc(PETSc.ScalarType({value}), dofs_{index}, V)
'''
        )
    names = ", ".join(f"bc_{index}" for index in range(len(snippets)))
    return "".join(snippets) + f"bcs = [{names}]\n"


def _stationary_body(pde: PDEProblemSpec, bc_setup: str) -> str:
    diffusion = _constant_number(pde.equation.diffusion.value, "diffusion coefficient")
    source = _constant_number(pde.equation.source.value, "source")
    return f'''{bc_setup}
k = fem.Constant(msh, PETSc.ScalarType({diffusion}))
f = fem.Constant(msh, PETSc.ScalarType({source}))
a = k * ufl.dot(ufl.grad(u), ufl.grad(v)) * ufl.dx
L = f * v * ufl.dx
u_sol = fem.Function(V)
u_sol.name = "u"
problem = LinearProblem(
    a, L, bcs=bcs, u=u_sol,
    petsc_options_prefix="aes_stationary_",
    petsc_options={{"ksp_type": "cg", "pc_type": "hypre"}},
)
problem.solve()
values = field_values(u_sol)
with io.XDMFFile(msh.comm, "solution.xdmf", "w") as xdmf:
    xdmf.write_mesh(msh)
    xdmf.write_function(u_sol)
diagnostics = {{
    "compiler": COMPILER,
    "problem": "stationary_diffusion",
    "num_dofs": int(V.dofmap.index_map.size_global * V.dofmap.index_map_bs),
    "solution_min": float(np.min(np.real(u_sol.x.array))),
    "solution_max": float(np.max(np.real(u_sol.x.array))),
    "solution_mean": float(np.mean(np.real(u_sol.x.array))),
    "field_samples": {{
        "type": "fem_mesh",
        "field": "u",
        "space": "{pde.function_space.family} P{pde.function_space.degree}",
        "coordinates": vtk_coordinates.tolist(),
        "topology": field_topology,
        "samples": [{{"step": 0, "time": 0.0, "values": values}}],
    }},
}}
Path("diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
print(json.dumps(diagnostics, indent=2))
'''


def _transient_body(pde: PDEProblemSpec, bc_setup: str) -> str:
    if pde.time is None or pde.initial_condition is None:
        raise ValueError("Transient compilation requires time and initial-condition specifications.")
    diffusion = _constant_number(pde.equation.diffusion.value, "diffusion coefficient")
    source = _constant_number(pde.equation.source.value, "source")
    initial = _numpy_expression(pde.initial_condition.value.value)
    return f'''{bc_setup}
dt = {pde.time.dt!r}
t0 = {pde.time.t0!r}
t_end = {pde.time.t_end!r}
num_steps = int(round((t_end - t0) / dt))
k = fem.Constant(msh, PETSc.ScalarType({diffusion}))
f = fem.Constant(msh, PETSc.ScalarType({source}))
u_previous = fem.Function(V)
u_previous.name = "u_previous"
u_previous.interpolate(lambda x: {initial})
a = (u * v + dt * k * ufl.dot(ufl.grad(u), ufl.grad(v))) * ufl.dx
L = (u_previous + dt * f) * v * ufl.dx
u_sol = fem.Function(V)
u_sol.name = "u"
problem = LinearProblem(
    a, L, bcs=bcs, u=u_sol,
    petsc_options_prefix="aes_transient_",
    petsc_options={{"ksp_type": "cg", "pc_type": "hypre"}},
)
samples = [{{"time": t0, "step": 0, "values": field_values(u_previous)}}]
sample_stride = max(1, num_steps // 10)
for step in range(1, num_steps + 1):
    problem.solve()
    u_previous.x.array[:] = u_sol.x.array
    if step % sample_stride == 0 or step == num_steps:
        samples.append({{"time": t0 + step * dt, "step": step, "values": field_values(u_sol)}})
with io.XDMFFile(msh.comm, "solution.xdmf", "w") as xdmf:
    xdmf.write_mesh(msh)
    xdmf.write_function(u_sol, t_end)
diagnostics = {{
    "compiler": COMPILER,
    "problem": "transient_diffusion",
    "num_dofs": int(V.dofmap.index_map.size_global * V.dofmap.index_map_bs),
    "num_steps": num_steps,
    "dt": dt,
    "final_time": t_end,
    "solution_min": float(np.min(np.real(u_sol.x.array))),
    "solution_max": float(np.max(np.real(u_sol.x.array))),
    "solution_mean": float(np.mean(np.real(u_sol.x.array))),
    "field_samples": {{
        "type": "fem_mesh_time_series",
        "field": "u",
        "space": "{pde.function_space.family} P{pde.function_space.degree}",
        "coordinates": vtk_coordinates.tolist(),
        "topology": field_topology,
        "samples": samples,
    }},
}}
Path("diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
print(json.dumps(diagnostics, indent=2))
'''


def _constant_number(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be constant in compiler version {COMPILER_VERSION}.") from exc


def _numpy_expression(source: str) -> str:
    expression = source.replace("^", "**")
    replacements = {
        "pi": "np.pi",
        "sin": "np.sin",
        "cos": "np.cos",
        "exp": "np.exp",
        "sqrt": "np.sqrt",
        "x": "x[0]",
        "y": "x[1]",
        "z": "x[2]",
    }
    for name in ("sin", "cos", "exp", "sqrt", "pi"):
        expression = re.sub(rf"(?<![\w.]){name}\b", replacements[name], expression)
    for name in ("x", "y", "z"):
        expression = re.sub(
            rf"\b{name}\b(?!\s*\[)",
            replacements[name],
            expression,
        )
    ast.parse(expression, mode="eval")
    return expression
