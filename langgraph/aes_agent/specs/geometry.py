from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from aes_agent.specs.base import StrictModel


class PrimitiveSpec(StrictModel):
    id: str = Field(min_length=1)
    shape: Literal["rectangle", "disk", "box", "sphere", "cylinder"]
    origin: list[float] | None = None
    size: list[float] | None = None
    center: list[float] | None = None
    radius: float | None = Field(default=None, gt=0)
    axis: list[float] | None = None
    height: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_shape_parameters(self) -> "PrimitiveSpec":
        if self.shape in {"rectangle", "box"} and (
            self.origin is None or self.size is None
        ):
            raise ValueError(f"{self.shape} requires origin and size")
        if self.shape in {"disk", "sphere"} and (
            self.center is None or self.radius is None
        ):
            raise ValueError(f"{self.shape} requires center and radius")
        if self.shape == "cylinder" and (
            self.origin is None or self.axis is None or self.radius is None
        ):
            raise ValueError("cylinder requires origin, axis, and radius")
        return self


class BooleanOperationSpec(StrictModel):
    type: Literal["union", "difference", "intersection", "fragment"]
    objects: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    result: str = Field(min_length=1)


class PrimitiveGeometrySource(StrictModel):
    kind: Literal["primitives"] = "primitives"
    primitives: list[PrimitiveSpec] = Field(min_length=1)


class CSGGeometrySource(StrictModel):
    kind: Literal["csg"] = "csg"
    primitives: list[PrimitiveSpec] = Field(min_length=1)
    operations: list[BooleanOperationSpec] = Field(min_length=1)


class CADRepairSpec(StrictModel):
    heal_shapes: bool = True
    remove_duplicates: bool = True
    tolerance: float = Field(default=1.0e-8, gt=0)


class CADGeometrySource(StrictModel):
    kind: Literal["cad"] = "cad"
    format: Literal["step", "stp", "brep", "iges", "igs"]
    artifact_path: str = Field(min_length=1)
    repair: CADRepairSpec = Field(default_factory=CADRepairSpec)


class MeshFileGeometrySource(StrictModel):
    kind: Literal["mesh_file"] = "mesh_file"
    format: Literal["msh", "xdmf"]
    artifact_path: str = Field(min_length=1)
    tag_map: dict[str, int] = Field(default_factory=dict)
    physical_data_name: str = "name_to_read"


class SurfaceScanGeometrySource(StrictModel):
    kind: Literal["surface_scan"] = "surface_scan"
    format: Literal["stl", "obj", "ply"]
    artifact_path: str = Field(min_length=1)


GeometrySource = Annotated[
    PrimitiveGeometrySource
    | CSGGeometrySource
    | CADGeometrySource
    | MeshFileGeometrySource
    | SurfaceScanGeometrySource,
    Field(discriminator="kind"),
]


class RegionSelector(StrictModel):
    kind: Literal[
        "object",
        "boundary_of",
        "all_boundary",
        "bounding_box",
        "entity_tags",
    ]
    reference: str | None = None
    bounds: list[float] | None = None
    entity_tags: list[int] = Field(default_factory=list)


class RegionSpec(StrictModel):
    name: str = Field(min_length=1)
    dimension: int = Field(ge=0, le=3)
    selector: RegionSelector


class RefinementRule(StrictModel):
    region: str = Field(min_length=1)
    size: float = Field(gt=0)
    distance: float | None = Field(default=None, gt=0)


class QualityRequirements(StrictModel):
    minimum_scaled_jacobian: float = Field(default=0.0, ge=-1.0, le=1.0)
    maximum_elements: int = Field(default=2_000_000, ge=1)


class MeshRequirements(StrictModel):
    cell_type: Literal["line", "triangle", "quadrilateral", "tetrahedron", "hexahedron"]
    order: int = Field(default=1, ge=1, le=5)
    global_size: float = Field(gt=0)
    refinements: list[RefinementRule] = Field(default_factory=list)
    quality: QualityRequirements = Field(default_factory=QualityRequirements)


class GeometrySpec(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    dimension: int = Field(ge=1, le=3)
    units: Literal["m", "cm", "mm"] = "m"
    source: GeometrySource
    regions: list[RegionSpec] = Field(min_length=1)
    mesh: MeshRequirements
    metadata: dict[str, Any] = Field(default_factory=dict)
