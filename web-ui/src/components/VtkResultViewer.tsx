import "@kitware/vtk.js/Rendering/Profiles/Geometry";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkFullScreenRenderWindow from "@kitware/vtk.js/Rendering/Misc/FullScreenRenderWindow";
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
    if (sampledField && sampledField.samples?.length && sampledField.coordinates?.length) {
      return <SampledFieldViewer field={sampledField} />;
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
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [sampleIndex, setSampleIndex] = useState(Math.max(0, field.samples.length - 1));
  const safeSampleIndex = Math.min(
    Math.max(0, sampleIndex),
    Math.max(0, field.samples.length - 1),
  );
  const sample = field.samples[safeSampleIndex];
  const lastSample = field.samples[field.samples.length - 1];
  const isTimeDependent =
    field.samples.length > 1 || String(field.type || "").toLowerCase().includes("time");
  const fieldLabel = `${field.field || "u"}(${isTimeDependent ? "x,y,t" : "x,y"})`;

  useEffect(() => {
    setSampleIndex(Math.max(0, field.samples.length - 1));
  }, [field]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !sample) {
      return;
    }
    drawSampledField(canvas, field, sample);
  }, [field, sample]);

  return (
    <div className="sampledFieldViewer">
      <div className="sampledFieldHeader">
        <div>
          <strong>Sampled solution field {fieldLabel}</strong>
          <span>
            {field.space || "FEM"} samples, {field.coordinates.length} spatial points
          </span>
        </div>
        <span>{isTimeDependent ? `t = ${formatNumber(sample?.time ?? 0)}` : "stationary"}</span>
      </div>
      <canvas
        ref={canvasRef}
        className="fieldCanvas"
        width={720}
        height={420}
        aria-label="Sampled FEM solution field"
      />
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
  return {
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

function heatColor(value: number, vmin: number, vmax: number) {
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
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
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
