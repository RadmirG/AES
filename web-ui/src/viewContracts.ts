import type { GeometrySpec, PDEProblemSpec } from "./types";

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");
const numbers = (value: unknown) => Array.isArray(value) && value.every(Number.isFinite);
const expression = (value: unknown) => record(value) &&
  ["constant", "symbolic"].includes(String(value.kind)) && typeof value.value === "string";

// View-shape checks, not mathematical validation. API and restored JSON are untrusted.
export function isGeometrySpec(value: unknown): value is GeometrySpec {
  if (!record(value) || value.schema_version !== "1.0" ||
      ![1, 2, 3].includes(Number(value.dimension)) || typeof value.dimension !== "number" ||
      typeof value.units !== "string" || !record(value.source) || !record(value.mesh) ||
      !Array.isArray(value.regions) || !value.regions.every((region) =>
        record(region) && typeof region.name === "string" && Number.isInteger(region.dimension) && record(region.selector))) return false;
  const source = value.source;
  if (!["primitives", "csg", "cad", "mesh_file", "surface_scan"].includes(String(source.kind))) return false;
  if (["primitives", "csg"].includes(String(source.kind))) {
    if (!Array.isArray(source.primitives) || !source.primitives.length || !source.primitives.every((item) =>
      record(item) && typeof item.id === "string" &&
      ["rectangle", "disk", "box", "sphere", "cylinder"].includes(String(item.shape)) &&
      ["origin", "size", "center", "axis"].every((key) => item[key] === undefined || numbers(item[key])) &&
      ["radius", "height"].every((key) => item[key] === undefined || Number.isFinite(item[key])))) return false;
  }
  return source.operations === undefined || (Array.isArray(source.operations) && source.operations.every((op) =>
    record(op) && typeof op.result === "string" && strings(op.objects) && strings(op.tools) &&
    ["union", "difference", "intersection", "fragment"].includes(String(op.type))));
}

export function isPdeSpec(value: unknown): value is PDEProblemSpec {
  if (!record(value) || !record(value.equation) || !Number.isInteger(value.spatial_dimension)) return false;
  const equation = value.equation;
  return typeof equation.unknown === "string" && typeof equation.strong_form === "string" &&
    ["stationary_diffusion", "transient_diffusion", "custom"].includes(String(equation.family)) &&
    expression(equation.diffusion) && expression(equation.source) &&
    Array.isArray(value.boundary_conditions) && value.boundary_conditions.every((bc) =>
      record(bc) && typeof bc.region === "string" && typeof bc.name === "string" &&
      ["dirichlet", "neumann", "robin"].includes(String(bc.type)) && expression(bc.value)) &&
    (value.initial_condition == null || (record(value.initial_condition) && expression(value.initial_condition.value))) &&
    (value.time == null || (record(value.time) && typeof value.time.scheme === "string" &&
      [value.time.t0, value.time.t_end, value.time.dt].every(Number.isFinite)));
}
