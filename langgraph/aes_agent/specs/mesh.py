from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from aes_agent.specs.base import StrictModel


class MeshQualityReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["valid", "invalid", "not_evaluated"]
    element_count: int = Field(default=0, ge=0)
    node_count: int = Field(default=0, ge=0)
    minimum_quality: float | None = None
    maximum_quality: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MeshArtifact(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["completed", "imported", "planned"]
    source_kind: Literal["primitives", "csg", "cad", "mesh_file"]
    dimension: int = Field(ge=1, le=3)
    cell_type: str
    mesh_uri: str = Field(min_length=1)
    cell_tags_uri: str | None = None
    facet_tags_uri: str | None = None
    tag_map: dict[str, int] = Field(default_factory=dict)
    quality: MeshQualityReport
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
