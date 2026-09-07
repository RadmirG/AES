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
    const hole = findPrimitive(primitives, "disk");
    if (isSimpleRectangleGeometry(spec, rectangle, hole)) {
      return buildRectangle(rectangle!, hole);
    }
    return buildImplicit2D(spec);
  }

  if (spec.dimension === 3) {
    const box = findPrimitive(primitives, "box");
    const hole = findPrimitive(primitives, "cylinder");
    if (isSimpleBoxGeometry(spec, box, hole)) {
      return buildPlate(box!, hole);
    }
    return buildImplicit3D(spec);
  }

  throw new Error(`Geometry dimension ${spec.dimension} is not supported by this viewer.`);
}

function isSimpleRectangleGeometry(
  spec: GeometrySpec,
  rectangle?: GeometryPrimitive,
  hole?: GeometryPrimitive,
) {
  const primitives = spec.source.primitives || [];
  return Boolean(
    rectangle?.origin &&
      rectangle.size &&
      primitives.length <= (hole ? 2 : 1) &&
      primitives.every((item) => item === rectangle || item === hole),
  );
}

function isSimpleBoxGeometry(
  spec: GeometrySpec,
  box?: GeometryPrimitive,
  hole?: GeometryPrimitive,
) {
  const primitives = spec.source.primitives || [];
  return Boolean(
    box?.origin &&
      box.size &&
      primitives.length <= (hole ? 2 : 1) &&
      primitives.every((item) => item === box || item === hole),
  );
}

function buildImplicit2D(spec: GeometrySpec) {
  const bounds = geometryBounds(spec.source.primitives || []);
  const inside = geometryPredicate(spec);
  const [nx, ny] = gridResolution(bounds, 110).slice(0, 2);
  const dx = (bounds[1] - bounds[0]) / nx;
  const dy = (bounds[3] - bounds[2]) / ny;
  const triangles: Point[][] = [];
  for (let row = 0; row < ny; row += 1) {
    for (let column = 0; column < nx; column += 1) {
      const x0 = bounds[0] + column * dx;
      const x1 = x0 + dx;
      const y0 = bounds[2] + row * dy;
      const y1 = y0 + dy;
      if (!inside([(x0 + x1) / 2, (y0 + y1) / 2, 0])) {
        continue;
      }
      triangles.push(
        [[x0, y0, 0], [x1, y0, 0], [x1, y1, 0]],
        [[x0, y0, 0], [x1, y1, 0], [x0, y1, 0]],
      );
    }
  }
  if (!triangles.length) {
    throw new Error("The CSG geometry preview produced an empty 2D domain.");
  }
  return [surface("domain", triangles)];
}

function buildImplicit3D(spec: GeometrySpec) {
  const bounds = geometryBounds(spec.source.primitives || []);
  const inside = geometryPredicate(spec);
  const [nx, ny, nz] = gridResolution(bounds, 48);
  const dx = (bounds[1] - bounds[0]) / nx;
  const dy = (bounds[3] - bounds[2]) / ny;
  const dz = (bounds[5] - bounds[4]) / nz;
  const occupied = new Uint8Array(nx * ny * nz);
  const cellIndex = (x: number, y: number, z: number) => x + nx * (y + ny * z);
  const isOccupied = (x: number, y: number, z: number) =>
    x >= 0 && x < nx && y >= 0 && y < ny && z >= 0 && z < nz
      ? occupied[cellIndex(x, y, z)] === 1
      : false;

  for (let z = 0; z < nz; z += 1) {
    for (let y = 0; y < ny; y += 1) {
      for (let x = 0; x < nx; x += 1) {
        const point: Point = [
          bounds[0] + (x + 0.5) * dx,
          bounds[2] + (y + 0.5) * dy,
          bounds[4] + (z + 0.5) * dz,
        ];
        occupied[cellIndex(x, y, z)] = inside(point) ? 1 : 0;
      }
    }
  }

  const triangles: Point[][] = [];
  for (let z = 0; z < nz; z += 1) {
    for (let y = 0; y < ny; y += 1) {
      for (let x = 0; x < nx; x += 1) {
        if (!isOccupied(x, y, z)) {
          continue;
        }
        const x0 = bounds[0] + x * dx;
        const x1 = x0 + dx;
        const y0 = bounds[2] + y * dy;
        const y1 = y0 + dy;
        const z0 = bounds[4] + z * dz;
        const z1 = z0 + dz;
        if (!isOccupied(x - 1, y, z)) {
          addQuad(triangles, [x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]);
        }
        if (!isOccupied(x + 1, y, z)) {
          addQuad(triangles, [x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [x1, y0, z1]);
        }
        if (!isOccupied(x, y - 1, z)) {
          addQuad(triangles, [x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]);
        }
        if (!isOccupied(x, y + 1, z)) {
          addQuad(triangles, [x0, y1, z0], [x0, y1, z1], [x1, y1, z1], [x1, y1, z0]);
        }
        if (!isOccupied(x, y, z - 1)) {
          addQuad(triangles, [x0, y0, z0], [x0, y1, z0], [x1, y1, z0], [x1, y0, z0]);
        }
        if (!isOccupied(x, y, z + 1)) {
          addQuad(triangles, [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]);
        }
      }
    }
  }
  if (!triangles.length) {
    throw new Error("The CSG geometry preview produced an empty 3D domain.");
  }
  return [surface("domain", triangles)];
}

function addQuad(triangles: Point[][], a: Point, b: Point, c: Point, d: Point) {
  triangles.push([a, b, c], [a, c, d]);
}

function geometryPredicate(spec: GeometrySpec) {
  const predicates = new Map<string, (point: Point) => boolean>();
  for (const primitive of spec.source.primitives || []) {
    predicates.set(primitive.id, primitivePredicate(primitive));
  }
  for (const operation of spec.source.operations || []) {
    const objects = operation.objects.map((name) => predicates.get(name)).filter(isPredicate);
    const tools = operation.tools.map((name) => predicates.get(name)).filter(isPredicate);
    const inObjects = (point: Point) => objects.some((predicate) => predicate(point));
    const inTools = (point: Point) => tools.some((predicate) => predicate(point));
    if (operation.type === "difference") {
      predicates.set(operation.result, (point) => inObjects(point) && !inTools(point));
    } else if (operation.type === "intersection") {
      predicates.set(operation.result, (point) => inObjects(point) && inTools(point));
    } else {
      predicates.set(operation.result, (point) => inObjects(point) || inTools(point));
    }
  }
  const operations = spec.source.operations || [];
  const finalOperation = operations[operations.length - 1];
  const domain =
    (finalOperation && predicates.get(finalOperation.result)) ||
    predicates.get("domain");
  if (domain) {
    return domain;
  }
  const primitivePredicates = [...predicates.values()];
  return (point: Point) => primitivePredicates.some((predicate) => predicate(point));
}

function isPredicate(
  value: ((point: Point) => boolean) | undefined,
): value is (point: Point) => boolean {
  return Boolean(value);
}

function primitivePredicate(primitive: GeometryPrimitive) {
  if (primitive.shape === "rectangle" && primitive.origin && primitive.size) {
    const [x0, y0] = primitive.origin;
    const [dx, dy] = primitive.size;
    return ([x, y]: Point) => x >= x0 && x <= x0 + dx && y >= y0 && y <= y0 + dy;
  }
  if (primitive.shape === "disk" && primitive.center && primitive.radius) {
    const [cx, cy] = primitive.center;
    const radiusSquared = primitive.radius ** 2;
    return ([x, y]: Point) => (x - cx) ** 2 + (y - cy) ** 2 <= radiusSquared;
  }
  if (primitive.shape === "box" && primitive.origin && primitive.size) {
    const [x0, y0, z0] = primitive.origin;
    const [dx, dy, dz] = primitive.size;
    return ([x, y, z]: Point) =>
      x >= x0 && x <= x0 + dx && y >= y0 && y <= y0 + dy && z >= z0 && z <= z0 + dz;
  }
  if (primitive.shape === "sphere" && primitive.center && primitive.radius) {
    const [cx, cy, cz] = primitive.center;
    const radiusSquared = primitive.radius ** 2;
    return ([x, y, z]: Point) =>
      (x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2 <= radiusSquared;
  }
  if (primitive.shape === "cylinder" && primitive.origin && primitive.axis && primitive.radius) {
    const origin = point3(primitive.origin);
    const axis = point3(primitive.axis);
    const lengthSquared = dot(axis, axis);
    const radiusSquared = primitive.radius ** 2;
    return (point: Point) => {
      const relative = subtract(point, origin);
      const position = dot(relative, axis) / lengthSquared;
      if (position < 0 || position > 1) {
        return false;
      }
      const radial = subtract(relative, scale(axis, position));
      return dot(radial, radial) <= radiusSquared;
    };
  }
  throw new Error(`Unsupported preview primitive: ${primitive.shape}`);
}

function geometryBounds(primitives: GeometryPrimitive[]): [number, number, number, number, number, number] {
  if (!primitives.length) {
    throw new Error("The geometry preview requires primitive bounds.");
  }
  const bounds = primitives.map(primitiveBounds);
  return [
    Math.min(...bounds.map((item) => item[0])),
    Math.max(...bounds.map((item) => item[1])),
    Math.min(...bounds.map((item) => item[2])),
    Math.max(...bounds.map((item) => item[3])),
    Math.min(...bounds.map((item) => item[4])),
    Math.max(...bounds.map((item) => item[5])),
  ];
}

function primitiveBounds(primitive: GeometryPrimitive): [number, number, number, number, number, number] {
  if ((primitive.shape === "rectangle" || primitive.shape === "box") && primitive.origin && primitive.size) {
    const origin = point3(primitive.origin);
    const size = point3(primitive.size);
    return [origin[0], origin[0] + size[0], origin[1], origin[1] + size[1], origin[2], origin[2] + size[2]];
  }
  if ((primitive.shape === "disk" || primitive.shape === "sphere") && primitive.center && primitive.radius) {
    const center = point3(primitive.center);
    const zRadius = primitive.shape === "sphere" ? primitive.radius : 0;
    return [
      center[0] - primitive.radius,
      center[0] + primitive.radius,
      center[1] - primitive.radius,
      center[1] + primitive.radius,
      center[2] - zRadius,
      center[2] + zRadius,
    ];
  }
  if (primitive.shape === "cylinder" && primitive.origin && primitive.axis && primitive.radius) {
    const origin = point3(primitive.origin);
    const end = origin.map((value, index) => value + point3(primitive.axis!)[index]) as Point;
    return [
      Math.min(origin[0], end[0]) - primitive.radius,
      Math.max(origin[0], end[0]) + primitive.radius,
      Math.min(origin[1], end[1]) - primitive.radius,
      Math.max(origin[1], end[1]) + primitive.radius,
      Math.min(origin[2], end[2]) - primitive.radius,
      Math.max(origin[2], end[2]) + primitive.radius,
    ];
  }
  throw new Error(`Could not determine bounds for preview primitive ${primitive.id}.`);
}

function gridResolution(
  bounds: [number, number, number, number, number, number],
  longestAxisCells: number,
): [number, number, number] {
  const spans = [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]];
  const maximum = Math.max(...spans, 1.0e-12);
  return spans.map((span) => Math.max(1, Math.round(longestAxisCells * span / maximum))) as [number, number, number];
}

function point3(values: number[]): Point {
  return [values[0] || 0, values[1] || 0, values[2] || 0];
}

function subtract(left: Point, right: Point): Point {
  return [left[0] - right[0], left[1] - right[1], left[2] - right[2]];
}

function scale(value: Point, factor: number): Point {
  return [value[0] * factor, value[1] * factor, value[2] * factor];
}

function dot(left: Point, right: Point) {
  return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
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
