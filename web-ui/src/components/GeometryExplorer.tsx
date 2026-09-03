import { ChangeEvent, useEffect, useMemo, useState } from "react";
import type {
  AesViewerManifest,
  GeometryExampleIndexItem,
  GeometrySpec,
} from "../types";
import { GeometryVtkViewer } from "./GeometryVtkViewer";
import { VtkResultViewer } from "./VtkResultViewer";

type Props = {
  solutionManifest: AesViewerManifest | null;
};

type LoadedExample = {
  id: string;
  spec: GeometrySpec;
};

export function GeometryExplorer({ solutionManifest }: Props) {
  const [examples, setExamples] = useState<LoadedExample[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [uploadedGeometry, setUploadedGeometry] = useState<GeometrySpec | null>(null);
  const [uploadedVtp, setUploadedVtp] = useState<ArrayBuffer | null>(null);
  const [uploadedName, setUploadedName] = useState("");
  const [mode, setMode] = useState<"geometry" | "solution">("geometry");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadExamples()
      .then((items) => {
        if (cancelled) {
          return;
        }
        setExamples(items);
        setSelectedId((current) => current || items[0]?.id || "");
      })
      .catch((loadError: Error) => {
        if (!cancelled) {
          setError(loadError.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (solutionManifest) {
      setMode("solution");
    }
  }, [solutionManifest]);

  const selectedExample = useMemo(
    () => examples.find((example) => example.id === selectedId) || null,
    [examples, selectedId],
  );
  const activeGeometry = uploadedGeometry || selectedExample?.spec || null;
  const title = metadataText(activeGeometry, "title") || uploadedName || "Geometry";
  const description = metadataText(activeGeometry, "description");

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setError("");
    try {
      if (file.name.toLowerCase().endsWith(".vtp")) {
        setUploadedVtp(await file.arrayBuffer());
        setUploadedGeometry(null);
        setUploadedName(file.name);
      } else {
        const parsed = JSON.parse(await file.text()) as GeometrySpec;
        assertGeometrySpec(parsed);
        setUploadedGeometry(parsed);
        setUploadedVtp(null);
        setUploadedName(file.name);
      }
      setMode("geometry");
    } catch (uploadError) {
      setError(`Could not load ${file.name}: ${(uploadError as Error).message}`);
    }
  }

  function selectExample(id: string) {
    setSelectedId(id);
    setUploadedGeometry(null);
    setUploadedVtp(null);
    setUploadedName("");
    setError("");
    setMode("geometry");
  }

  return (
    <section className="scientificViewerCard">
      <header className="viewerToolbar">
        <div>
          <span className="equationEyebrow">Scientific viewport</span>
          <h3>{mode === "solution" ? "Numerical solution" : title}</h3>
          {mode === "geometry" && description ? <p>{description}</p> : null}
        </div>
        <div className="viewerModeSwitch" aria-label="Viewer content">
          <button
            className={mode === "geometry" ? "active" : ""}
            onClick={() => setMode("geometry")}
            type="button"
          >
            Geometry
          </button>
          <button
            className={mode === "solution" ? "active" : ""}
            disabled={!solutionManifest}
            onClick={() => setMode("solution")}
            type="button"
          >
            Solution
          </button>
        </div>
      </header>

      {mode === "geometry" ? (
        <>
          <div className="geometryControls">
            <label>
              Standard geometry
              <select value={selectedId} onChange={(event) => selectExample(event.target.value)}>
                {examples.map((example) => (
                  <option value={example.id} key={example.id}>
                    {metadataText(example.spec, "title") || example.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="uploadGeometryButton">
              Upload GeometrySpec JSON or VTP
              <input accept=".json,.vtp,application/json" onChange={handleUpload} type="file" />
            </label>
            <span className="geometryDimension">
              {activeGeometry ? `${activeGeometry.dimension}D · ${activeGeometry.units}` : "Loading examples..."}
            </span>
          </div>
          <GeometryVtkViewer
            geometry={activeGeometry}
            key={`${selectedId}:${uploadedName}`}
            uploadedName={uploadedName || "uploaded VTP"}
            uploadedVtp={uploadedVtp}
          />
          {activeGeometry ? (
            <div className="regionCatalog">
              <span>Semantic regions</span>
              {activeGeometry.regions.map((region) => (
                <span className="regionChip" key={region.name}>
                  {region.name} <small>{region.dimension}D</small>
                </span>
              ))}
            </div>
          ) : null}
        </>
      ) : solutionManifest ? (
        <VtkResultViewer manifest={solutionManifest} />
      ) : (
        <div className="viewerPlaceholder">No numerical solution is loaded.</div>
      )}

      {error ? <div className="viewerError">{error}</div> : null}
    </section>
  );
}

async function loadExamples() {
  const indexResponse = await fetch("/geometries/index.json");
  if (!indexResponse.ok) {
    throw new Error(`Geometry catalog request failed: ${indexResponse.status}`);
  }
  const index = (await indexResponse.json()) as GeometryExampleIndexItem[];
  return Promise.all(
    index.map(async (entry) => {
      const response = await fetch(`/geometries/${entry.spec}`);
      if (!response.ok) {
        throw new Error(`Geometry example ${entry.id} failed to load: ${response.status}`);
      }
      const spec = (await response.json()) as GeometrySpec;
      assertGeometrySpec(spec);
      return { id: entry.id, spec };
    }),
  );
}

function assertGeometrySpec(value: GeometrySpec) {
  if (!value || value.schema_version !== "1.0") {
    throw new Error("Expected an AES GeometrySpec with schema_version 1.0.");
  }
  if (![1, 2, 3].includes(value.dimension) || !value.source || !Array.isArray(value.regions)) {
    throw new Error("GeometrySpec is missing dimension, source, or regions.");
  }
}

function metadataText(spec: GeometrySpec | null, key: string) {
  const value = spec?.metadata?.[key];
  return typeof value === "string" ? value : "";
}
