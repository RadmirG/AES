from __future__ import annotations

import json
from pathlib import Path

import yaml

from aes_agent.specs.geometry import GeometrySpec
from aes_agent.specs.validation import validate_geometry_spec


EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "geometries"


def test_all_geometry_examples_match_yaml_and_json_and_validate():
    index = json.loads((EXAMPLE_ROOT / "index.json").read_text(encoding="utf-8"))

    assert {entry["id"] for entry in index} == {
        "unit-square-2d",
        "square-with-hole-2d",
        "unit-plate-solid-3d",
        "plate-with-hole-solid-3d",
    }

    for entry in index:
        directory = EXAMPLE_ROOT / entry["id"]
        yaml_value = yaml.safe_load((directory / "geometry.yaml").read_text(encoding="utf-8"))
        json_value = json.loads((directory / "geometry.json").read_text(encoding="utf-8"))

        assert yaml_value == json_value
        spec, report = validate_geometry_spec(json_value)
        assert report.status == "valid", report.errors
        assert isinstance(spec, GeometrySpec)
        assert spec.metadata["id"] == entry["id"]


def test_hole_examples_expose_a_semantic_hole_wall():
    for example_id in ("square-with-hole-2d", "plate-with-hole-solid-3d"):
        value = json.loads(
            (EXAMPLE_ROOT / example_id / "geometry.json").read_text(encoding="utf-8")
        )
        regions = {region["name"]: region for region in value["regions"]}

        assert regions["hole_wall"]["selector"] == {
            "kind": "boundary_of",
            "reference": "hole",
        }


def test_plate_solids_request_multiple_mesh_layers_through_thickness():
    for example_id in ("unit-plate-solid-3d", "plate-with-hole-solid-3d"):
        value = json.loads(
            (EXAMPLE_ROOT / example_id / "geometry.json").read_text(encoding="utf-8")
        )
        plate = next(
            primitive
            for primitive in value["source"]["primitives"]
            if primitive["shape"] == "box"
        )
        thickness = float(plate["size"][2])

        assert float(value["mesh"]["global_size"]) <= thickness / 4.0
