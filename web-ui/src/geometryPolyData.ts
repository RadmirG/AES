import vtkPolyData from "@kitware/vtk.js/Common/DataModel/PolyData";
import type { GeometryPrimitive, GeometrySpec } from "./types";

export type GeometrySurface = {
  name: string;
  color: [number, number, number];
  kind: "surface" | "line";
  data: ReturnType<typeof vtkPolyData.newInstance>;
};

type Point = [number, number, number];

const REGION_COLORS: Record<string, [number, number, number]> = {
  domain: [0.13, 0.64, 0.54],
  x_min: [0.9, 0.29, 0.24],
  x_max: [0.14, 0.39, 0.92],
  y_min: [0.16, 0.67, 0.34],
  y_max: [0.96, 0.58, 0.16],
  z_min: [0.49, 0.31, 0.88],
  z_max: [0.18, 0.67, 0.91],
  hole_wall: [0.86, 0.2, 0.55],
};

export function buildGeometrySurfaces(spec: GeometrySpec): GeometrySurface[] {
  const primitives = spec.source.primitives || [];
  if (spec.dimension === 2) {
    const rectangle = findPrimitive(primitives, "rectangle");
    if (!rectangle?.origin || !rectangle.size) {
      throw new Error("The VTK geometry preview requires a rectangle primitive for 2D examples.");
    }
    const hole = findPrimitive(primitives, "disk");
    return buildRectangle(rectangle, hole);
  }

  if (spec.dimension === 3) {
    const box = findPrimitive(primitives, "box");
    if (!box?.origin || !box.size) {
      throw new Error("The VTK geometry preview requires a box primitive for 3D examples.");
    }
    const hole = findPrimitive(primitives, "cylinder");
    return buildPlate(box, hole);
  }

  throw new Error(`Geometry dimension ${spec.dimension} is not supported by this viewer.`);
}

function buildRectangle(rectangle: GeometryPrimitive, hole?: GeometryPrimitive) {
  const [x0, y0] = rectangle.origin!;
  const [width, height] = rectangle.size!;
  const x1 = x0 + width;
  const y1 = y0 + height;

  if (!hole?.center || !hole.radius) {
    const surfaces = [
      surface("domain", [
        [[x0, y0, 0], [x1, y0, 0], [x1, y1, 0]],
        [[x0, y0, 0], [x1, y1, 0], [x0, y1, 0]],
      ]),
    ];
    return surfaces.concat(rectangleBoundaryLines(x0, x1, y0, y1, 0));
  }

  const center: [number, number] = [hole.center[0], hole.center[1]];
  const ring = squareRingPoints(x0, x1, y0, y1, center, hole.radius, 64);
  const triangles: Point[][] = [];
  for (let index = 0; index < ring.length; index += 1) {
    const next = (index + 1) % ring.length;
    triangles.push([ring[index].outer, ring[next].outer, ring[next].inner]);
    triangles.push([ring[index].outer, ring[next].inner, ring[index].inner]);
  }
  return [
    surface("domain", triangles),
    ...rectangleBoundaryLines(x0, x1, y0, y1, 0),
    line("hole_wall", ring.map((item, index) => [item.inner, ring[(index + 1) % ring.length].inner])),
  ];
}

function buildPlate(box: GeometryPrimitive, hole?: GeometryPrimitive) {
  const [x0, y0, z0] = box.origin!;
  const [width, height, depth] = box.size!;
  const x1 = x0 + width;
  const y1 = y0 + height;
  const z1 = z0 + depth;
  if (!hole?.origin || !hole.axis || !hole.radius) {
    return boxSurfaces(x0, x1, y0, y1, z0, z1);
  }

  const center: [number, number] = [hole.origin[0], hole.origin[1]];
  const ring = squareRingPoints(x0, x1, y0, y1, center, hole.radius, 64);
  const groups: Record<string, Point[][]> = {
    x_min: [],
    x_max: [],
    y_min: [],
    y_max: [],
    z_min: [],
    z_max: [],
    hole_wall: [],
  };

  for (let index = 0; index < ring.length; index += 1) {
    const next = (index + 1) % ring.length;
    const outer0 = ring[index].outer;
    const outer1 = ring[next].outer;
    const inner0 = ring[index].inner;
    const inner1 = ring[next].inner;
    const ob: Point = [outer0[0], outer0[1], z0];
    const on: Point = [outer1[0], outer1[1], z0];
    const ot: Point = [outer0[0], outer0[1], z1];
    const otn: Point = [outer1[0], outer1[1], z1];
    const ib: Point = [inner0[0], inner0[1], z0];
    const ibn: Point = [inner1[0], inner1[1], z0];
    const it: Point = [inner0[0], inner0[1], z1];
    const itn: Point = [inner1[0], inner1[1], z1];

    groups.z_min.push([ob, ibn, on], [ob, ib, ibn]);
    groups.z_max.push([ot, otn, itn], [ot, itn, it]);
    groups.hole_wall.push([ib, itn, ibn], [ib, it, itn]);
    const side = outerSide(outer0, outer1, x0, x1, y0, y1);
    groups[side].push([ob, on, otn], [ob, otn, ot]);
  }

  return Object.entries(groups)
    .filter(([, triangles]) => triangles.length > 0)
    .map(([name, triangles]) => surface(name, triangles));
}

function boxSurfaces(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number) {
  const p = (x: number, y: number, z: number): Point => [x, y, z];
  return [
    quad("x_min", p(x0, y0, z0), p(x0, y0, z1), p(x0, y1, z1), p(x0, y1, z0)),
    quad("x_max", p(x1, y0, z0), p(x1, y1, z0), p(x1, y1, z1), p(x1, y0, z1)),
    quad("y_min", p(x0, y0, z0), p(x1, y0, z0), p(x1, y0, z1), p(x0, y0, z1)),
    quad("y_max", p(x0, y1, z0), p(x0, y1, z1), p(x1, y1, z1), p(x1, y1, z0)),
    quad("z_min", p(x0, y0, z0), p(x0, y1, z0), p(x1, y1, z0), p(x1, y0, z0)),
    quad("z_max", p(x0, y0, z1), p(x1, y0, z1), p(x1, y1, z1), p(x0, y1, z1)),
  ];
}

function rectangleBoundaryLines(x0: number, x1: number, y0: number, y1: number, z: number) {
  return [
    line("x_min", [[[x0, y0, z], [x0, y1, z]]]),
    line("x_max", [[[x1, y0, z], [x1, y1, z]]]),
    line("y_min", [[[x0, y0, z], [x1, y0, z]]]),
    line("y_max", [[[x0, y1, z], [x1, y1, z]]]),
  ];
}

function squareRingPoints(
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  center: [number, number],
  radius: number,
  count: number,
) {
  return Array.from({ length: count }, (_, index) => {
    const angle = (2 * Math.PI * index) / count;
    const dx = Math.cos(angle);
    const dy = Math.sin(angle);
    const distances = [
      dx > 0 ? (x1 - center[0]) / dx : Number.POSITIVE_INFINITY,
      dx < 0 ? (x0 - center[0]) / dx : Number.POSITIVE_INFINITY,
      dy > 0 ? (y1 - center[1]) / dy : Number.POSITIVE_INFINITY,
      dy < 0 ? (y0 - center[1]) / dy : Number.POSITIVE_INFINITY,
    ].filter((value) => value > 0);
    const outerDistance = Math.min(...distances);
    return {
      outer: [center[0] + dx * outerDistance, center[1] + dy * outerDistance, 0] as Point,
      inner: [center[0] + dx * radius, center[1] + dy * radius, 0] as Point,
    };
  });
}

function outerSide(a: Point, b: Point, x0: number, x1: number, y0: number, y1: number) {
  const midpoint = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const distances: Array<[string, number]> = [
    ["x_min", Math.abs(midpoint[0] - x0)],
    ["x_max", Math.abs(midpoint[0] - x1)],
    ["y_min", Math.abs(midpoint[1] - y0)],
    ["y_max", Math.abs(midpoint[1] - y1)],
  ];
  distances.sort((left, right) => left[1] - right[1]);
  return distances[0][0];
}

function quad(name: string, a: Point, b: Point, c: Point, d: Point) {
  return surface(name, [[a, b, c], [a, c, d]]);
}

function surface(name: string, triangles: Point[][]): GeometrySurface {
  const points: number[] = [];
  const cells: number[] = [];
  for (const triangle of triangles) {
    const start = points.length / 3;
    triangle.forEach((point) => points.push(...point));
    cells.push(3, start, start + 1, start + 2);
  }
  const data = vtkPolyData.newInstance();
  data.getPoints().setData(Float32Array.from(points), 3);
  data.getPolys().setData(Uint32Array.from(cells));
  return { name, color: colorFor(name), kind: "surface", data };
}

function line(name: string, segments: Point[][]): GeometrySurface {
  const points: number[] = [];
  const cells: number[] = [];
  for (const segment of segments) {
    const start = points.length / 3;
    segment.forEach((point) => points.push(...point));
    cells.push(2, start, start + 1);
  }
  const data = vtkPolyData.newInstance();
  data.getPoints().setData(Float32Array.from(points), 3);
  data.getLines().setData(Uint32Array.from(cells));
  return { name, color: colorFor(name), kind: "line", data };
}

function findPrimitive(primitives: GeometryPrimitive[], shape: GeometryPrimitive["shape"]) {
  return primitives.find((primitive) => primitive.shape === shape);
}

function colorFor(name: string): [number, number, number] {
  return REGION_COLORS[name] || [0.42, 0.48, 0.58];
}
