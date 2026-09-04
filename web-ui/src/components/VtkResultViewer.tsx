import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkCellArray from "@kitware/vtk.js/Common/Core/CellArray";
import vtkDataArray from "@kitware/vtk.js/Common/Core/DataArray";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
import vtkPoints from "@kitware/vtk.js/Common/Core/Points";
import vtkPolyData from "@kitware/vtk.js/Common/DataModel/PolyData";
import vtkXMLPolyDataReader from "@kitware/vtk.js/IO/XML/XMLPolyDataReader";
import { useEffect, useMemo, useRef, useState } from "react";
import { publicArtifactUrl } from "../artifacts";
import type { AesArtifact, AesViewerManifest, SampledFieldDataset } from "../types";

type Props = {
  manifest: AesViewerManifest;
};

export function VtkResultViewer({ manifest }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [message, setMessage] = useState("");

  const dataset = useMemo(
    () => firstFetchableDataset(manifest.datasets.vtkjs_readable || []),
    [manifest],
  );
  const sampledField = manifest.datasets.sampled_field;
  const diagnosticSeries = useMemo(() => seriesFromManifest(manifest), [manifest]);

  useEffect(() => {
    if (!containerRef.current || !dataset) {
      return;
    }
    const activeDataset = dataset;

    const renderWindow = vtkFullScreenRenderWindow.newInstance({
      container: containerRef.current,
      containerStyle: {
        height: "100%",
        width: "100%",
        position: "relative",
      },
      background: [0.02, 0.04, 0.1],
    });

    async function loadDataset() {
      try {
        const response = await fetch(activeDataset.url);
        if (!response.ok) {
          throw new Error(`Dataset request failed: ${response.status}`);
        }
        const buffer = await response.arrayBuffer();
        const reader = readerFor(activeDataset.artifact.name);
        if (!reader) {
          throw new Error(`Unsupported VTK.js dataset type: ${activeDataset.artifact.name}`);
        }
        reader.parseAsArrayBuffer(buffer);

        const mapper = vtkMapper.newInstance();
        mapper.setInputData(reader.getOutputData(0));
        const actor = vtkActor.newInstance();
        actor.setMapper(mapper);

        const renderer = renderWindow.getRenderer();
        renderer.addActor(actor);
        renderer.resetCamera();
        renderWindow.getRenderWindow().render();
        setMessage("");
      } catch (error) {
        setMessage((error as Error).message);
      }
    }

    loadDataset();

    return () => {
      renderWindow.delete();
    };
  }, [dataset]);

  if (!dataset) {
    if (hasSpatialField(sampledField)) {
      return <SampledFieldViewer field={sampledField} />;
    }

    if (diagnosticSeries.length) {
      return <ResultSeriesChart points={diagnosticSeries} />;
    }

    return (
      <div className="viewerPlaceholder">
        <strong>No browser-fetchable VTK.js dataset yet</strong>
        <p>
          AES has diagnostics and preview artifacts, but no sampled field or
          VTK.js-readable dataset was found. Interactive FEM rendering starts
          when sampled field data or a `.vtp`/`.vtu`/`.vtkjs` artifact is served.
        </p>
      </div>
    );
  }

  return (
    <div className="vtkHost">
      <div ref={containerRef} className="vtkContainer" />
      {message ? <div className="viewerError">{message}</div> : null}
    </div>
  );
}

function SampledFieldViewer({ field }: { field: SampledFieldDataset }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<SampledFieldScene | null>(null);
  const [sampleIndex, setSampleIndex] = useState(Math.max(0, field.samples.length - 1));
  const [sliceAxis, setSliceAxis] = useState<SliceAxis>(2);
  const [slicePercent, setSlicePercent] = useState(50);
  const [colorScale, setColorScale] = useState<ColorScale>("sample");
  const surface = useMemo(
    () => buildSurfacePolygons(field.topology),
    [field.topology],
  );
  const safeSampleIndex = Math.min(
    Math.max(0, sampleIndex),
    Math.max(0, field.samples.length - 1),
  );
  const sample = field.samples[safeSampleIndex];
  const lastSample = field.samples[field.samples.length - 1];
  const isTimeDependent =
    field.samples.length > 1 || String(field.type || "").toLowerCase().includes("time");
  const spatialDimension = field.topology?.topological_dimension || 2;
  const volumeCellCount = useMemo(
    () => countVolumeCells(field.topology),
    [field.topology],
  );
  const hasVolume = spatialDimension === 3 && volumeCellCount > 0;
  const activeRange = useMemo(
    () =>
      colorScale === "global" && field.value_range
        ? field.value_range
        : valueRange(sample?.values || []),
    [colorScale, field.value_range, sample],
  );
  const volumeSlice = useMemo(
    () =>
      hasVolume && sample
        ? buildVolumeSlice(field, sample.values, sliceAxis, slicePercent / 100)
        : emptyVolumeSlice(),
    [field, hasVolume, sample, sliceAxis, slicePercent],
  );
  const spatialVariables = ["x", "y", "z"].slice(0, spatialDimension).join(",");
  const fieldLabel = `${field.field || "u"}(${spatialVariables}${isTimeDependent ? ",t" : ""})`;

  useEffect(() => {
    setSampleIndex(Math.max(0, field.samples.length - 1));
  }, [field]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    container.replaceChildren();
    const view = vtkFullScreenRenderWindow.newInstance({
      container,
      containerStyle: {
        height: "100%",
        width: "100%",
        position: "relative",
      },
      background: [0.97, 0.98, 1.0],
    });
    const points = vtkPoints.newInstance();
    points.setData(
      Float32Array.from(
        field.coordinates.flatMap((point) => [
          point[0] || 0,
          point[1] || 0,
          point[2] || 0,
        ]),
      ),
      3,
    );
    const colors = vtkDataArray.newInstance({
      name: `${field.field || "u"}_colors`,
      numberOfComponents: 3,
      values: new Uint8Array(field.coordinates.length * 3),
    });
    const polyData = vtkPolyData.newInstance();
    polyData.setPoints(points);
    if (surface.polygonCount) {
      polyData.setPolys(vtkCellArray.newInstance({ values: surface.values }));
    } else {
      polyData.setVerts(
        vtkCellArray.newInstance({
          values: Uint32Array.from(
            field.coordinates.flatMap((_point, index) => [1, index]),
          ),
        }),
      );
    }
    polyData.getPointData().setScalars(colors);

    const mapper = vtkMapper.newInstance();
    mapper.setInputData(polyData);
    mapper.setColorModeToDirectScalars();
    mapper.setScalarModeToUsePointData();
    const actor = vtkActor.newInstance();
    actor.setMapper(mapper);
    if (surface.polygonCount) {
      actor.getProperty().setEdgeVisibility(true);
      actor.getProperty().setEdgeColor(0.16, 0.2, 0.27);
      actor.getProperty().setLineWidth(1);
      actor.getProperty().setInterpolationToGouraud();
      if (hasVolume) {
        actor.getProperty().setOpacity(0.16);
      }
    } else {
      actor.getProperty().setPointSize(7);
    }

    const renderer = view.getRenderer();
    renderer.addActor(actor);
    let sliceData: ReturnType<typeof vtkPolyData.newInstance> | null = null;
    let sliceActor: ReturnType<typeof vtkActor.newInstance> | null = null;
    if (hasVolume) {
      sliceData = vtkPolyData.newInstance();
      const sliceMapper = vtkMapper.newInstance();
      sliceMapper.setInputData(sliceData);
      sliceMapper.setColorModeToDirectScalars();
      sliceMapper.setScalarModeToUsePointData();
      sliceActor = vtkActor.newInstance();
      sliceActor.setMapper(sliceMapper);
      sliceActor.getProperty().setEdgeVisibility(true);
      sliceActor.getProperty().setEdgeColor(0.18, 0.22, 0.3);
      sliceActor.getProperty().setLineWidth(1);
      sliceActor.getProperty().setInterpolationToGouraud();
      sliceActor.setVisibility(false);
      renderer.addActor(sliceActor);
    }
    sceneRef.current = {
      view,
      surfaceData: polyData,
      sliceData,
      sliceActor,
    };
    renderer.resetCamera();
    const isThreeDimensional = field.coordinates.some(
      (point) => point.length > 2 && Math.abs(point[2] || 0) > 1.0e-12,
    );
    if (!isThreeDimensional) {
      const bounds = polyData.getBounds();
      const centerX = (bounds[0] + bounds[1]) / 2;
      const centerY = (bounds[2] + bounds[3]) / 2;
      const span = Math.max(bounds[1] - bounds[0], bounds[3] - bounds[2], 1.0e-6);
      const camera = renderer.getActiveCamera();
      camera.setFocalPoint(centerX, centerY, 0);
      camera.setPosition(centerX, centerY, 2 * span);
      camera.setViewUp(0, 1, 0);
      camera.setParallelProjection(true);
      camera.setParallelScale(span * 0.58);
      renderer.resetCameraClippingRange();
    }
    view.getRenderWindow().render();

    return () => {
      if (sceneRef.current?.view === view) {
        sceneRef.current = null;
      }
      view.delete();
      container.replaceChildren();
    };
  }, [field, hasVolume, surface]);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !sample) {
      return;
    }
    scene.surfaceData.getPointData().setScalars(
      vtkDataArray.newInstance({
        name: `${field.field || "u"}_colors`,
        numberOfComponents: 3,
        values: Uint8Array.from(
          sample.values.flatMap((value) =>
            heatRgb(value, activeRange.min, activeRange.max),
          ),
        ),
      }),
    );
    scene.surfaceData.modified();

    if (scene.sliceData && scene.sliceActor) {
      const hasSlice = hasVolume && volumeSlice.polygonCount > 0;
      scene.sliceActor.setVisibility(hasSlice);
      if (hasSlice) {
        const slicePoints = vtkPoints.newInstance();
        slicePoints.setData(
          Float32Array.from(volumeSlice.coordinates.flatMap((point) => point)),
          3,
        );
        scene.sliceData.setPoints(slicePoints);
        scene.sliceData.setPolys(
          vtkCellArray.newInstance({
            values: Uint32Array.from(volumeSlice.polygons),
          }),
        );
        scene.sliceData.getPointData().setScalars(
          vtkDataArray.newInstance({
            name: `${field.field || "u"}_slice_colors`,
            numberOfComponents: 3,
            values: Uint8Array.from(
              volumeSlice.values.flatMap((value) =>
                heatRgb(value, activeRange.min, activeRange.max),
              ),
            ),
          }),
        );
        scene.sliceData.modified();
      }
    }

    scene.view.getRenderWindow().render();
  }, [activeRange, field.field, hasVolume, sample, volumeSlice]);

  return (
    <div className="sampledFieldViewer">
      <div className="sampledFieldHeader">
        <div>
          <strong>Sampled solution field {fieldLabel}</strong>
          <span>
            {field.space || "FEM"}, {field.coordinates.length} points
            {hasVolume
              ? `, ${volumeCellCount} volume cells, ${surface.polygonCount} exterior faces`
              : surface.polygonCount
              ? `, ${surface.polygonCount} exterior mesh faces`
              : ", point samples (mesh topology unavailable)"}
          </span>
        </div>
        <span>{isTimeDependent ? `t = ${formatNumber(sample?.time ?? 0)}` : "stationary"}</span>
      </div>
      <div
        ref={containerRef}
        className="sampledFieldVtkContainer"
        aria-label="Interactive sampled FEM solution field"
      />
      <div className="fieldLegend" aria-label="Solution value color scale">
        <span>min {formatNumber(activeRange.min)}</span>
        <i />
        <span>max {formatNumber(activeRange.max)}</span>
      </div>
      {hasVolume ? (
        <div className="volumeControls" aria-label="Volumetric result controls">
          <label>
            Interior section
            <select
              value={sliceAxis}
              onChange={(event) =>
                setSliceAxis(Number(event.target.value) as SliceAxis)
              }
            >
              <option value={0}>X plane</option>
              <option value={1}>Y plane</option>
              <option value={2}>Z plane</option>
            </select>
          </label>
          <label className="slicePositionControl">
            <span className="slicePositionLabel">Plane position</span>
            <input
              type="range"
              min={1}
              max={99}
              step={1}
              value={slicePercent}
              onChange={(event) => setSlicePercent(Number(event.target.value))}
            />
            <span className="slicePositionValue">{slicePercent}%</span>
          </label>
          <label>
            Color scale
            <select
              value={colorScale}
              onChange={(event) => setColorScale(event.target.value as ColorScale)}
            >
              <option value="sample">Current step</option>
              <option value="global">All steps</option>
            </select>
          </label>
          <span className="volumeSliceStatus">
            {volumeSlice.polygonCount} intersected volume cells
          </span>
        </div>
      ) : null}
      <div className="fieldControls">
        {isTimeDependent ? (
          <>
            <input
              type="range"
              min={0}
              max={Math.max(0, field.samples.length - 1)}
              value={safeSampleIndex}
              onChange={(event) => setSampleIndex(Number(event.target.value))}
            />
            <span>
              step {sample?.step ?? 0} of {lastSample?.step ?? field.samples.length - 1}
            </span>
          </>
        ) : (
          <span>stationary solution sample</span>
        )}
      </div>
    </div>
  );
}

type SliceAxis = 0 | 1 | 2;
type ColorScale = "sample" | "global";

type SampledFieldScene = {
  view: ReturnType<typeof vtkFullScreenRenderWindow.newInstance>;
  surfaceData: ReturnType<typeof vtkPolyData.newInstance>;
  sliceData: ReturnType<typeof vtkPolyData.newInstance> | null;
  sliceActor: ReturnType<typeof vtkActor.newInstance> | null;
};

type TopologyCell = {
  type: number;
  points: number[];
};

type VolumeSlice = {
  coordinates: number[][];
  values: number[];
  polygons: number[];
  polygonCount: number;
};

function emptyVolumeSlice(): VolumeSlice {
  return { coordinates: [], values: [], polygons: [], polygonCount: 0 };
}

function topologyCells(
  topology: SampledFieldDataset["topology"],
): TopologyCell[] {
  if (!topology || topology.format !== "vtk_cell_array") {
    return [];
  }
  const cells: TopologyCell[] = [];
  let offset = 0;
  let cellIndex = 0;
  while (offset < topology.cells.length && cellIndex < topology.cell_types.length) {
    const width = topology.cells[offset];
    if (!Number.isInteger(width) || width <= 0 || offset + width >= topology.cells.length) {
      break;
    }
    cells.push({
      type: topology.cell_types[cellIndex],
      points: topology.cells.slice(offset + 1, offset + width + 1),
    });
    offset += width + 1;
    cellIndex += 1;
  }
  return cells;
}

function countVolumeCells(topology: SampledFieldDataset["topology"]) {
  return topologyCells(topology).filter((cell) => volumeCellDefinition(cell)).length;
}

function volumeCellDefinition(cell: TopologyCell) {
  if ((cell.type === 10 || cell.type === 24) && cell.points.length >= 4) {
    return {
      points: cell.points.slice(0, 4),
      edges: [
        [0, 1],
        [0, 2],
        [0, 3],
        [1, 2],
        [1, 3],
        [2, 3],
      ],
    };
  }
  if ((cell.type === 12 || cell.type === 25) && cell.points.length >= 8) {
    return {
      points: cell.points.slice(0, 8),
      edges: [
        [0, 1],
        [1, 2],
        [2, 3],
        [3, 0],
        [4, 5],
        [5, 6],
        [6, 7],
        [7, 4],
        [0, 4],
        [1, 5],
        [2, 6],
        [3, 7],
      ],
    };
  }
  return null;
}

function buildVolumeSlice(
  field: SampledFieldDataset,
  sampleValues: number[],
  axis: SliceAxis,
  fraction: number,
): VolumeSlice {
  const axisValues = field.coordinates
    .map((point) => Number(point[axis] || 0))
    .filter(Number.isFinite);
  if (!axisValues.length) {
    return emptyVolumeSlice();
  }
  const minimum = Math.min(...axisValues);
  const maximum = Math.max(...axisValues);
  const span = maximum - minimum;
  if (!(span > 0)) {
    return emptyVolumeSlice();
  }
  const plane = minimum + Math.max(0, Math.min(1, fraction)) * span;
  const epsilon = Math.max(span * 1.0e-9, 1.0e-12);
  const planeAxes: Array<[number, number]> = [
    [1, 2],
    [0, 2],
    [0, 1],
  ];
  const [horizontal, vertical] = planeAxes[axis];
  const result = emptyVolumeSlice();

  for (const cell of topologyCells(field.topology)) {
    const definition = volumeCellDefinition(cell);
    if (!definition) {
      continue;
    }
    const intersections: Array<{ point: number[]; value: number }> = [];
    const addIntersection = (point: number[], value: number) => {
      const duplicate = intersections.some((entry) =>
        entry.point.every(
          (coordinate, index) => Math.abs(coordinate - point[index]) <= epsilon,
        ),
      );
      if (!duplicate) {
        intersections.push({ point, value });
      }
    };

    for (const [localA, localB] of definition.edges) {
      const indexA = definition.points[localA];
      const indexB = definition.points[localB];
      const pointA = point3(field.coordinates[indexA]);
      const pointB = point3(field.coordinates[indexB]);
      if (!pointA || !pointB) {
        continue;
      }
      const distanceA = pointA[axis] - plane;
      const distanceB = pointB[axis] - plane;
      const valueA = Number(sampleValues[indexA] ?? 0);
      const valueB = Number(sampleValues[indexB] ?? 0);

      if (Math.abs(distanceA) <= epsilon) {
        addIntersection(pointA, valueA);
      }
      if (Math.abs(distanceB) <= epsilon) {
        addIntersection(pointB, valueB);
      }
      if (distanceA * distanceB < 0) {
        const interpolation = (plane - pointA[axis]) / (pointB[axis] - pointA[axis]);
        addIntersection(
          pointA.map(
            (coordinate, index) =>
              coordinate + interpolation * (pointB[index] - coordinate),
          ),
          valueA + interpolation * (valueB - valueA),
        );
      }
    }

    if (intersections.length < 3) {
      continue;
    }
    const centerHorizontal =
      intersections.reduce((sum, entry) => sum + entry.point[horizontal], 0) /
      intersections.length;
    const centerVertical =
      intersections.reduce((sum, entry) => sum + entry.point[vertical], 0) /
      intersections.length;
    intersections.sort(
      (left, right) =>
        Math.atan2(
          left.point[vertical] - centerVertical,
          left.point[horizontal] - centerHorizontal,
        ) -
        Math.atan2(
          right.point[vertical] - centerVertical,
          right.point[horizontal] - centerHorizontal,
        ),
    );

    const start = result.coordinates.length;
    result.coordinates.push(...intersections.map((entry) => entry.point));
    result.values.push(...intersections.map((entry) => entry.value));
    result.polygons.push(
      intersections.length,
      ...intersections.map((_entry, index) => start + index),
    );
    result.polygonCount += 1;
  }

  return result;
}

function point3(value: number[] | undefined): number[] | null {
  if (!Array.isArray(value) || value.length < 2) {
    return null;
  }
  const point = [Number(value[0]), Number(value[1]), Number(value[2] || 0)];
  return point.every(Number.isFinite) ? point : null;
}

type SurfacePolygons = {
  values: Uint32Array;
  polygonCount: number;
};

function buildSurfacePolygons(
  topology: SampledFieldDataset["topology"],
): SurfacePolygons {
  if (!topology || topology.format !== "vtk_cell_array") {
    return { values: new Uint32Array(), polygonCount: 0 };
  }

  const directFaces: number[][] = [];
  const volumeFaces = new Map<string, { face: number[]; count: number }>();
  const addVolumeFace = (face: number[]) => {
    const key = [...face].sort((left, right) => left - right).join(":");
    const existing = volumeFaces.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      volumeFaces.set(key, { face, count: 1 });
    }
  };

  let offset = 0;
  let cellIndex = 0;
  while (offset < topology.cells.length && cellIndex < topology.cell_types.length) {
    const width = topology.cells[offset];
    const points = topology.cells.slice(offset + 1, offset + width + 1);
    const cellType = topology.cell_types[cellIndex];

    // VTK linear and quadratic surface cells. Higher-order edge nodes are not
    // needed to recover the exterior polygon used for result visualization.
    if ((cellType === 5 || cellType === 22) && points.length >= 3) {
      directFaces.push(points.slice(0, 3));
    } else if ((cellType === 9 || cellType === 23) && points.length >= 4) {
      directFaces.push(points.slice(0, 4));
    } else if ((cellType === 10 || cellType === 24) && points.length >= 4) {
      const [a, b, c, d] = points;
      addVolumeFace([a, c, b]);
      addVolumeFace([a, b, d]);
      addVolumeFace([b, c, d]);
      addVolumeFace([c, a, d]);
    } else if ((cellType === 12 || cellType === 25) && points.length >= 8) {
      const [a, b, c, d, e, f, g, h] = points;
      addVolumeFace([a, d, c, b]);
      addVolumeFace([e, f, g, h]);
      addVolumeFace([a, b, f, e]);
      addVolumeFace([b, c, g, f]);
      addVolumeFace([c, d, h, g]);
      addVolumeFace([d, a, e, h]);
    }

    offset += width + 1;
    cellIndex += 1;
  }

  const exteriorFaces = [
    ...directFaces,
    ...Array.from(volumeFaces.values())
      .filter((entry) => entry.count === 1)
      .map((entry) => entry.face),
  ];
  return {
    values: Uint32Array.from(
      exteriorFaces.flatMap((face) => [face.length, ...face]),
    ),
    polygonCount: exteriorFaces.length,
  };
}

type SeriesPoint = {
  x: number;
  y: number;
  label: string;
};

function ResultSeriesChart({ points }: { points: SeriesPoint[] }) {
  const width = 760;
  const height = 420;
  const padding = 54;
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  const ymin = Math.min(...ys);
  const ymax = Math.max(...ys);
  const xrange = xmax - xmin || 1;
  const yrange = ymax - ymin || 1;
  const path = points
    .map((point, index) => {
      const x = padding + ((point.x - xmin) / xrange) * (width - 2 * padding);
      const y = height - padding - ((point.y - ymin) / yrange) * (height - 2 * padding);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <div className="resultSeriesChart">
      <div className="sampledFieldHeader">
        <div>
          <strong>Numerical result history</strong>
          <span>{points[0]?.label || "diagnostic value"}</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Numerical result chart">
        <rect x={padding} y={padding} width={width - 2 * padding} height={height - 2 * padding} />
        <path d={path} />
        <text x={padding} y={height - 17}>x {formatNumber(xmin)} to {formatNumber(xmax)}</text>
        <text x={padding + 220} y={height - 17}>value {formatNumber(ymin)} to {formatNumber(ymax)}</text>
      </svg>
    </div>
  );
}

function drawSampledField(
  canvas: HTMLCanvasElement,
  field: SampledFieldDataset,
  sample: SampledFieldDataset["samples"][number],
) {
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const width = canvas.width;
  const height = canvas.height;
  const padding = 34;
  const plotWidth = width - 2 * padding;
  const plotHeight = height - 2 * padding - 34;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#f8fafc";
  context.fillRect(0, 0, width, height);

  const xs = field.coordinates.map((point) => point[0]);
  const ys = field.coordinates.map((point) => point[1]);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  const ymin = Math.min(...ys);
  const ymax = Math.max(...ys);
  const xrange = xmax - xmin || 1;
  const yrange = ymax - ymin || 1;
  const range = field.value_range || valueRange(field.samples.flatMap((item) => item.values));
  const vmin = Number.isFinite(range.min) ? range.min : 0;
  const vmax = Number.isFinite(range.max) && range.max > vmin ? range.max : vmin + 1;
  const cell = Math.max(2, Math.min(9, plotWidth / Math.sqrt(field.coordinates.length || 1)));

  context.strokeStyle = "#d1d5db";
  context.lineWidth = 1;
  context.strokeRect(padding, padding, plotWidth, plotHeight);

  for (let index = 0; index < field.coordinates.length; index += 1) {
    const point = field.coordinates[index];
    const value = sample.values[index] ?? 0;
    const x = padding + ((point[0] - xmin) / xrange) * (plotWidth - cell);
    const y = padding + (1 - (point[1] - ymin) / yrange) * (plotHeight - cell);
    context.fillStyle = heatColor(value, vmin, vmax);
    context.fillRect(x, y, cell, cell);
  }

  drawLegend(context, padding, height - 34, plotWidth, vmin, vmax);
  context.fillStyle = "#6b7280";
  context.font = "13px system-ui, sans-serif";
  context.fillText("x", padding + plotWidth + 8, padding + plotHeight + 4);
  context.fillText("y", padding - 16, padding + 12);
}

function drawLegend(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  vmin: number,
  vmax: number,
) {
  const gradient = context.createLinearGradient(x, y, x + width, y);
  for (const [offset, color] of [
    [0, "#2563eb"],
    [0.25, "#06b6d4"],
    [0.5, "#10b981"],
    [0.75, "#facc15"],
    [1, "#ef4444"],
  ] as const) {
    gradient.addColorStop(offset, color);
  }
  context.fillStyle = gradient;
  context.fillRect(x, y, width, 12);
  context.strokeStyle = "#d1d5db";
  context.strokeRect(x, y, width, 12);
  context.fillStyle = "#6b7280";
  context.font = "12px system-ui, sans-serif";
  context.fillText(`min ${formatNumber(vmin)}`, x, y + 29);
  context.fillText(`max ${formatNumber(vmax)}`, x + width - 82, y + 29);
}

function valueRange(values: number[]) {
  if (!values.length) {
    return { min: 0, max: 1 };
  }
  return {
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

function heatColor(value: number, vmin: number, vmax: number) {
  const rgb = heatRgb(value, vmin, vmax);
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

function heatRgb(value: number, vmin: number, vmax: number) {
  const stops = [
    [37, 99, 235],
    [6, 182, 212],
    [16, 185, 129],
    [250, 204, 21],
    [239, 68, 68],
  ];
  const t = Math.max(0, Math.min(1, (value - vmin) / (vmax - vmin || 1)));
  const scaled = t * (stops.length - 1);
  const index = Math.min(Math.floor(scaled), stops.length - 2);
  const local = scaled - index;
  const rgb = stops[index].map((channel, channelIndex) =>
    Math.round(channel + (stops[index + 1][channelIndex] - channel) * local),
  );
  return rgb;
}

function hasSpatialField(
  field: SampledFieldDataset | undefined,
): field is SampledFieldDataset {
  if (!field?.coordinates?.length || !field.samples?.length) {
    return false;
  }
  return (
    field.coordinates.every(
      (point) =>
        Array.isArray(point) &&
        point.length >= 2 &&
        point.slice(0, 3).every(Number.isFinite),
    ) &&
    field.samples.every(
      (sample) =>
        Array.isArray(sample.values) &&
        sample.values.length === field.coordinates.length,
    )
  );
}

function seriesFromManifest(manifest: AesViewerManifest): SeriesPoint[] {
  const sampled = manifest.datasets.sampled_field;
  if (sampled?.samples?.length) {
    return sampled.samples
      .filter((sample) => sample.values?.length)
      .map((sample, index) => ({
        x: Number.isFinite(sample.time) ? sample.time : sample.step ?? index,
        y: Math.max(...sample.values),
        label: `max(${sampled.field || "u"})`,
      }));
  }

  const diagnostics = asRecord(manifest.diagnostics);
  const script = asRecord(diagnostics.script);
  for (const candidate of [script.time_series, diagnostics.time_series]) {
    if (!Array.isArray(candidate)) {
      continue;
    }
    const points = candidate
      .map((value, index) => diagnosticPoint(value, index))
      .filter((value): value is SeriesPoint => Boolean(value));
    if (points.length) {
      return points;
    }
  }
  return [];
}

function diagnosticPoint(value: unknown, index: number): SeriesPoint | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return { x: index, y: value, label: "diagnostic value" };
  }
  const row = asRecord(value);
  const x = firstFinite(row.time, row.t, row.step, index);
  const entries: Array<[string, unknown]> = [
    ["max", row.max],
    ["mean", row.mean],
    ["residual", row.residual],
    ["value", row.value],
  ];
  const selected = entries.find((entry) => Number.isFinite(Number(entry[1])));
  return selected
    ? { x, y: Number(selected[1]), label: selected[0] }
    : null;
}

function firstFinite(...values: unknown[]) {
  const value = values.map(Number).find(Number.isFinite);
  return value ?? 0;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function formatNumber(value: number) {
  if (!Number.isFinite(value)) {
    return "n/a";
  }
  if (value === 0) {
    return "0";
  }
  if (Math.abs(value) >= 1000 || Math.abs(value) < 0.001) {
    return value.toExponential(3);
  }
  return value.toPrecision(5).replace(/\.?0+$/, "");
}

function firstFetchableDataset(artifacts: AesArtifact[]) {
  for (const artifact of artifacts) {
    if (!canReadDataset(artifact.name)) {
      continue;
    }
    const url = publicArtifactUrl(artifact) || fetchableUrl(artifact.uri);
    if (url) {
      return { artifact, url };
    }
  }
  return null;
}

function fetchableUrl(uri: string) {
  if (uri.startsWith("http://") || uri.startsWith("https://") || uri.startsWith("/")) {
    return uri;
  }
  return "";
}

function readerFor(name: string) {
  if (canReadDataset(name)) {
    return vtkXMLPolyDataReader.newInstance();
  }
  return null;
}

function canReadDataset(name: string) {
  return name.toLowerCase().endsWith(".vtp");
}
