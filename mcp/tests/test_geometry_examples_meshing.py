from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


SERVER_PATH = Path(__file__).resolve().parents[1] / "providers" / "meshing" / "server.py"
EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "geometries"
SPEC = importlib.util.spec_from_file_location("aes_geometry_example_provider", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(server)


@pytest.mark.skipif(
    os.getenv("AES_RUN_GMSH_TESTS", "false").lower() not in {"1", "true", "yes"},
    reason="Set AES_RUN_GMSH_TESTS=true to run native Gmsh example tests.",
)
@pytest.mark.parametrize(
    "example_id",
    [
        "unit-square-2d",
        "square-with-hole-2d",
        "unit-plate-solid-3d",
        "plate-with-hole-solid-3d",
    ],
)
def test_standard_geometry_generates_a_mesh(example_id, tmp_path, monkeypatch):
    geometry = json.loads(
        (EXAMPLE_ROOT / example_id / "geometry.json").read_text(encoding="utf-8")
    )
    monkeypatch.setenv("MESHING_WORKSPACE", str(tmp_path))

    result = server._generate_mesh(geometry)

    assert result["status"] == "completed", result.get("errors")
    artifact = result["mesh_artifact"]
    assert artifact["quality"]["status"] == "valid"
    assert artifact["quality"]["element_count"] > 0
    assert set(artifact["tag_map"]) == {
        region["name"] for region in geometry["regions"]
    }
