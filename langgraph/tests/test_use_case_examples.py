from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml

from aes_agent.compiler.capability import build_compilation_plan
from aes_agent.compiler.dolfinx_backend import compile_dolfinx
from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.mesh import MeshArtifact, MeshQualityReport
from aes_agent.specs.pde import PDEProblemSpec
from aes_agent.specs.validation import cross_validate_pde_geometry, validate_pde_spec


EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples"
USE_CASE_CATALOG = EXAMPLE_ROOT / "use-cases" / "catalog.yaml"
WEB_USE_CASE_CATALOG = EXAMPLE_ROOT / "use-cases" / "catalog.json"
GEOMETRY_ROOT = EXAMPLE_ROOT / "geometries"


def test_pde_catalog_contains_all_24_numbered_use_cases():
    catalog = yaml.safe_load(USE_CASE_CATALOG.read_text(encoding="utf-8"))
    use_cases = catalog["use_cases"]

    assert catalog["schema_version"] == "1.0"
    assert [item["number"] for item in use_cases] == list(range(1, 25))
    assert len({item["id"] for item in use_cases}) == 24
    assert {item["status"] for item in use_cases} <= {
        "immediate",
        "compiler_extension",
        "advanced_backend",
    }
    assert all(item["prompt"].strip() for item in use_cases)
    assert all(item["required_capabilities"] for item in use_cases)


def test_browser_catalog_is_a_synchronized_public_projection():
    catalog = yaml.safe_load(USE_CASE_CATALOG.read_text(encoding="utf-8"))
    browser_catalog = json.loads(WEB_USE_CASE_CATALOG.read_text(encoding="utf-8"))
    public_keys = {
        "number",
        "id",
        "category",
        "title",
        "equation",
        "applications",
        "status",
        "geometry_id",
        "required_capabilities",
        "prompt",
    }

    assert browser_catalog["schema_version"] == catalog["schema_version"]
    assert browser_catalog["support_levels"] == catalog["support_levels"]
    assert browser_catalog["use_cases"] == [
        {key: item.get(key) for key in public_keys}
        for item in catalog["use_cases"]
    ]


def test_all_catalog_geometry_references_exist():
    catalog = yaml.safe_load(USE_CASE_CATALOG.read_text(encoding="utf-8"))
    geometry_ids = {
        item["id"]
        for item in json.loads((GEOMETRY_ROOT / "index.json").read_text(encoding="utf-8"))
    }

    assert all(
        item["geometry_id"] is None or item["geometry_id"] in geometry_ids
        for item in catalog["use_cases"]
    )


def test_immediate_use_cases_are_valid_and_compiler_ready():
    catalog = yaml.safe_load(USE_CASE_CATALOG.read_text(encoding="utf-8"))
    immediate = [item for item in catalog["use_cases"] if item["status"] == "immediate"]

    assert {item["number"] for item in immediate} == {1, 2, 9}
    for use_case in immediate:
        pde, validation = validate_pde_spec(use_case["pde_spec"])
        assert validation.status == "valid", validation.errors
        assert isinstance(pde, PDEProblemSpec)

        geometry = GeometrySpec.model_validate_json(
            (GEOMETRY_ROOT / use_case["geometry_id"] / "geometry.json").read_text(
                encoding="utf-8"
            )
        )
        cross_validation = cross_validate_pde_geometry(pde, geometry)
        assert cross_validation.status == "valid", cross_validation.errors

        mesh = MeshArtifact(
            status="completed",
            source_kind=geometry.source.kind,
            dimension=geometry.dimension,
            cell_type=geometry.mesh.cell_type,
            mesh_uri=f"aes://artifacts/meshes/{use_case['geometry_id']}/mesh.msh",
            tag_map={
                region.name: index
                for index, region in enumerate(geometry.regions, start=1)
            },
            quality=MeshQualityReport(status="valid", element_count=1, node_count=1),
        )
        plan = build_compilation_plan(pde, geometry, mesh)
        assert plan.status == "ready", plan.capability_errors
        ast.parse(compile_dolfinx(pde, geometry, plan, mesh))
