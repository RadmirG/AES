from __future__ import annotations

import ast
import unittest

from aes_agent.compiler import build_compilation_plan, compile_dolfinx
from aes_agent.compiler.dolfinx_backend import _numpy_expression
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.legacy import build_legacy_specs
from aes_agent.specs.mesh import MeshArtifact, MeshQualityReport
from aes_agent.specs.pde import PDEProblemSpec
from aes_agent.specs.validation import (
    cross_validate_pde_geometry,
    cross_validate_pde_mesh,
    validate_geometry_spec,
    validate_pde_spec,
)


class TypedSpecificationTests(unittest.TestCase):
    def test_legacy_transient_problem_builds_valid_typed_specs(self):
        pde, geometry = build_legacy_specs(
            {
                "raw_user_input": (
                    "Solve the transient heat equation on Omega=[0,1]x[0,1]. "
                    "Use u=0, alpha=1, f=1, initial condition "
                    "sin(pi*x)*sin(pi*y), T=1 and dt=0.01."
                ),
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "sin(pi*x)*sin(pi*y)",
                "time_info": "T=1, dt=0.01",
            }
        )

        self.assertIsNotNone(pde)
        self.assertIsNotNone(geometry)
        _, pde_report = validate_pde_spec(pde)
        _, geometry_report = validate_geometry_spec(geometry)
        self.assertEqual(pde_report.status, "valid")
        self.assertEqual(geometry_report.status, "valid")

    def test_legacy_time_parser_accepts_explicit_t0_tend_and_dt(self):
        pde, _ = build_legacy_specs(
            {
                "raw_user_input": (
                    "Solve the transient heat equation on the unit square. "
                    "Use T_0=-1e-1, T_end=1, and time step dt=1e-2."
                ),
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "unit_square",
                "coefficient_info": "1",
                "source_info": "1",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "sin(pi*x)*sin(pi*y)",
                "time_info": "unknown_time",
            }
        )

        self.assertIsNotNone(pde)
        assert pde is not None and pde.time is not None
        self.assertEqual(pde.time.t0, -0.1)
        self.assertEqual(pde.time.t_end, 1.0)
        self.assertEqual(pde.time.dt, 0.01)

    def test_legacy_spec_prefers_explicit_raw_physics_and_normalizes_initial(self):
        pde, _ = build_legacy_specs(
            {
                "raw_user_input": (
                    "Solve the transient heat equation on uploaded 3D geometry. "
                    "Use alpha=1 and f=1. Use u=0 on the boundary. "
                    "Use initial condition u(x,y,z,0)=sin(pi*x)sin(pi*y). "
                    "Use final time T=1 and time step dt=0.01."
                ),
                "pde_info": "time_dependent_heat_equation",
                "domain_info": "domain_symbolically_specified",
                "coefficient_info": "constant_coefficient_given",
                "source_info": "unknown_source",
                "bc_info": "dirichlet_boundary_condition",
                "initial_condition_info": "sin(pi*x)sin(pi*y)",
                "time_info": "unknown_time",
            }
        )

        self.assertIsNotNone(pde)
        assert pde is not None and pde.initial_condition is not None
        self.assertEqual(pde.spatial_dimension, 3)
        self.assertEqual(pde.equation.diffusion.value, "1")
        self.assertEqual(pde.equation.source.value, "1")
        self.assertEqual(
            pde.initial_condition.value.value,
            "sin(pi*x)*sin(pi*y)",
        )

    def test_transient_spec_requires_time_and_initial_condition(self):
        value = _pde_dict("transient_diffusion")
        pde, report = validate_pde_spec(value)

        self.assertIsNotNone(pde)
        self.assertEqual(report.status, "invalid")
        self.assertTrue(any("time specification" in item for item in report.errors))
        self.assertTrue(any("initial condition" in item for item in report.errors))

    def test_surface_scan_is_schema_valid_but_compiler_unsupported(self):
        geometry = GeometrySpec.model_validate(_surface_geometry_dict())
        _, report = validate_geometry_spec(geometry)
        pde = PDEProblemSpec.model_validate(_pde_dict("stationary_diffusion"))
        plan = build_compilation_plan(pde, geometry)

        self.assertEqual(report.status, "valid")
        self.assertEqual(plan.status, "unsupported")
        self.assertTrue(any("surface-scan" in item for item in plan.capability_errors))

    def test_compiler_emits_syntax_valid_stationary_dolfinx(self):
        pde = PDEProblemSpec.model_validate(_pde_dict("stationary_diffusion"))
        geometry = GeometrySpec.model_validate(_rectangle_geometry_dict())
        plan = build_compilation_plan(pde, geometry)

        code = compile_dolfinx(pde, geometry, plan)

        ast.parse(code)
        self.assertIn("mesh.create_rectangle", code)
        self.assertIn("LinearProblem", code)
        self.assertIn("plot.vtk_mesh(V)", code)
        self.assertIn('"topology": field_topology', code)
        self.assertIn('"compiler": COMPILER', code)

    def test_transient_compiler_exports_every_solved_time_step(self):
        value = _pde_dict("transient_diffusion")
        value["initial_condition"] = {
            "value": {
                "kind": "symbolic",
                "value": "sin(pi*x)*sin(pi*y)",
                "variables": ["x", "y"],
            }
        }
        value["time"] = {
            "t0": 0.0,
            "t_end": 1.0,
            "dt": 0.01,
            "scheme": "backward_euler",
        }
        pde = PDEProblemSpec.model_validate(value)
        geometry = GeometrySpec.model_validate(_rectangle_geometry_dict())
        plan = build_compilation_plan(pde, geometry)

        code = compile_dolfinx(pde, geometry, plan)

        ast.parse(code)
        self.assertNotIn("sample_stride", code)
        self.assertIn(
            'samples.append({"time": t0 + step * dt, "step": step',
            code,
        )

    def test_compiler_locates_aggregate_exterior_boundary_without_overlapping_tag(self):
        pde = PDEProblemSpec.model_validate(_pde_dict("stationary_diffusion"))
        geometry = GeometrySpec.model_validate(_rectangle_geometry_dict())
        mesh = MeshArtifact(
            status="completed",
            source_kind="csg",
            dimension=2,
            cell_type="triangle",
            mesh_uri="aes://artifacts/meshes/test/mesh.msh",
            tag_map={"domain": 1, "boundary": 2},
            quality=MeshQualityReport(status="valid", element_count=10, node_count=8),
        )
        plan = build_compilation_plan(pde, geometry, mesh)

        code = compile_dolfinx(pde, geometry, plan, mesh)

        self.assertIn("mesh.locate_entities_boundary", code)
        self.assertNotIn("facet_tags.find(2)", code)

    def test_cross_validation_requires_boundary_tag(self):
        pde = PDEProblemSpec.model_validate(_pde_dict("stationary_diffusion"))
        mesh = MeshArtifact(
            status="completed",
            source_kind="csg",
            dimension=2,
            cell_type="triangle",
            mesh_uri="mcp://meshing/workspace/runs/test/mesh.msh",
            tag_map={"domain": 1},
            quality=MeshQualityReport(status="valid", element_count=10, node_count=8),
        )

        report = cross_validate_pde_mesh(pde, mesh)

        self.assertEqual(report.status, "invalid")
        self.assertTrue(any("boundary" in item for item in report.errors))

    def test_pde_geometry_cross_validation_rejects_unknown_boundary_region(self):
        pde_value = _pde_dict("stationary_diffusion")
        pde_value["boundary_conditions"][0]["region"] = "inlet"
        pde = PDEProblemSpec.model_validate(pde_value)
        geometry = GeometrySpec.model_validate(_rectangle_geometry_dict())

        report = cross_validate_pde_geometry(pde, geometry)

        self.assertEqual(report.status, "invalid")
        self.assertTrue(any("inlet" in item for item in report.errors))

    def test_geometry_validation_rejects_3d_primitive_in_2d_spec(self):
        value = _rectangle_geometry_dict()
        value["source"]["primitives"][0].update(
            {"shape": "box", "origin": [0, 0, 0], "size": [1, 1, 1]}
        )

        _, report = validate_geometry_spec(value)

        self.assertEqual(report.status, "invalid")
        self.assertTrue(any("3D" in item for item in report.errors))

    def test_numpy_expression_preserves_indexed_coordinates(self):
        self.assertEqual(
            _numpy_expression("sin(pi*x[0])*sin(pi*x[1])"),
            "np.sin(np.pi*x[0])*np.sin(np.pi*x[1])",
        )
        self.assertEqual(
            _numpy_expression("sin(pi*x)*sin(pi*y)"),
            "np.sin(np.pi*x[0])*np.sin(np.pi*x[1])",
        )


def _expression(value: str) -> dict:
    return {"kind": "constant", "value": value, "variables": []}


def _pde_dict(family: str) -> dict:
    return {
        "schema_version": "2.0",
        "problem_class": "forward_problem",
        "spatial_dimension": 2,
        "equation": {
            "family": family,
            "unknown": "u",
            "strong_form": "-div(k*grad(u))=f",
            "diffusion": _expression("1"),
            "source": _expression("1"),
        },
        "boundary_conditions": [
            {
                "name": "wall_temperature",
                "region": "boundary",
                "type": "dirichlet",
                "value": _expression("0"),
            }
        ],
        "initial_condition": None,
        "time": None,
        "function_space": {"family": "Lagrange", "degree": 1, "value_shape": []},
        "solver": {
            "linear_solver": "cg",
            "preconditioner": "hypre",
            "relative_tolerance": 1e-8,
            "maximum_iterations": 1000,
        },
        "outputs": ["solution.xdmf", "diagnostics.json"],
        "assumptions": [],
    }


def _rectangle_geometry_dict() -> dict:
    return {
        "schema_version": "1.0",
        "dimension": 2,
        "units": "m",
        "source": {
            "kind": "primitives",
            "primitives": [
                {
                    "id": "domain",
                    "shape": "rectangle",
                    "origin": [0, 0],
                    "size": [1, 1],
                    "center": None,
                    "radius": None,
                    "axis": None,
                    "height": None,
                }
            ],
        },
        "regions": [
            {"name": "domain", "dimension": 2, "selector": {"kind": "object", "reference": "domain", "bounds": None, "entity_tags": []}},
            {"name": "boundary", "dimension": 1, "selector": {"kind": "all_boundary", "reference": "domain", "bounds": None, "entity_tags": []}},
        ],
        "mesh": {
            "cell_type": "triangle",
            "order": 1,
            "global_size": 0.1,
            "refinements": [],
            "quality": {"minimum_scaled_jacobian": 0.0, "maximum_elements": 10000},
        },
        "metadata": {},
    }


def _surface_geometry_dict() -> dict:
    value = _rectangle_geometry_dict()
    value["source"] = {"kind": "surface_scan", "format": "stl", "artifact_path": "uploads/part.stl"}
    return value


if __name__ == "__main__":
    unittest.main()
