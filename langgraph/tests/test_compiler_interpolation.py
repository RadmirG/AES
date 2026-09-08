from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from aes_agent.compiler import build_compilation_plan, compile_dolfinx
from aes_agent.fenics_code import _fallback_dolfinx_script, validate_python_code_safety
from aes_agent.specs.expressions import expression_from_text
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.mesh import MeshArtifact, MeshQualityReport
from aes_agent.specs.pde import PDEProblemSpec


EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def heat_sink_specs():
    catalog = yaml.safe_load(
        (EXAMPLES / "use-cases" / "catalog.yaml").read_text(encoding="utf-8")
    )
    case = next(
        item for item in catalog["use_cases"]
        if item["id"] == "transient-heat-heat-sink-3d"
    )
    pde = PDEProblemSpec.model_validate(case["pde_spec"])
    geometry = GeometrySpec.model_validate_json(
        (EXAMPLES / "geometries" / case["geometry_id"] / "geometry.json")
        .read_text(encoding="utf-8")
    )
    mesh = MeshArtifact(
        status="completed",
        source_kind=geometry.source.kind,
        dimension=geometry.dimension,
        cell_type=geometry.mesh.cell_type,
        mesh_uri="aes://artifacts/meshes/test-heat-sink/mesh.msh",
        tag_map={region.name: i for i, region in enumerate(geometry.regions, 1)},
        quality=MeshQualityReport(status="valid", element_count=1, node_count=1),
    )
    return pde, geometry, mesh


@pytest.mark.parametrize("emitter", ["compiler", "fallback"])
@pytest.mark.parametrize(
    "expression, expected",
    [
        ("20", lambda x: np.full(x.shape[1], 20.0)),
        ("0", lambda x: np.zeros(x.shape[1])),
        ("0.01", lambda x: np.full(x.shape[1], 0.01)),
        ("sin(pi/2)", lambda x: np.ones(x.shape[1])),
        ("sin(pi*x)*sin(pi*y)", lambda x: np.sin(np.pi*x[0])*np.sin(np.pi*x[1])),
        ("x[0]+2*x[1]", lambda x: x[0]+2*x[1]),
    ],
)
def test_generated_initial_interpolator_returns_one_typed_value_per_point(
    heat_sink_specs, emitter, expression, expected,
):
    if emitter == "compiler":
        pde, geometry, mesh = heat_sink_specs
        pde.initial_condition.value = expression_from_text(expression)
        plan = build_compilation_plan(pde, geometry, mesh)
        code = compile_dolfinx(pde, geometry, plan, mesh)
    else:
        code = _fallback_dolfinx_script({
            "pde_info": "time_dependent_heat_equation",
            "initial_condition_info": expression,
        })

    assert validate_python_code_safety(code)["status"] == "safe"
    callbacks = [
        node.args[0] for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "interpolate"
    ]
    assert len(callbacks) == 1
    # Execute the emitted callback without importing the container-only FEM runtime.
    callback_code = compile(ast.Expression(callbacks[0]), "solve.py", "eval")
    for scalar_type in (np.float64, np.complex128):
        callback = eval(callback_code, {
            "np": np, "PETSc": SimpleNamespace(ScalarType=scalar_type),
        })
        for point_count in (0, 1, 7):
            coordinates = np.arange(3*point_count, dtype=float).reshape(3, point_count) / 10
            values = callback(coordinates)
            assert isinstance(values, np.ndarray)
            assert values.shape == (point_count,)
            assert values.dtype == np.dtype(scalar_type)
            assert values.flags.c_contiguous
            np.testing.assert_allclose(values, expected(coordinates))
