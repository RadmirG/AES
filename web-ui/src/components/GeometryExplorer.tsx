import { ChangeEvent, useEffect, useMemo, useState } from "react";
import type {
  AesViewerManifest,
  GeometryContext,
  GeometryExampleIndexItem,
  GeometrySpec,
} from "../types";
import { GeometryVtkViewer } from "./GeometryVtkViewer";
import { VtkResultViewer } from "./VtkResultViewer";

type Props = {
  geometryContext?: GeometryContext;
  onGeometryContextChange: (context?: GeometryContext) => void;
  resultGeometry: GeometrySpec | null;
  resultGeometryContext?: GeometryContext;
  solutionManifest: AesViewerManifest | null;
};

type LoadedExample = {
  id: string;
  spec: GeometrySpec;
};

export function GeometryExplorer({
  geometryContext,
  onGeometryContextChange,
  resultGeometry,
  resultGeometryContext,
  solutionManifest,
}: Props) {
  const [examples, setExamples] = useState<LoadedExample[]>([]);
  const [uploadedVtp, setUploadedVtp] = useState<ArrayBuffer | null>(null);
  const [uploadedName, setUploadedName] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadExamples()
      .then((items) => {
        if (cancelled) {
          return;
        }
        setExamples(items);
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

  const selectedExample = useMemo(
    () => examples.find((example) => example.id === geometryContext?.id) || null,
    [examples, geometryContext?.id],
  );
  const activeGeometry =
    geometryContext?.spec || resultGeometry || selectedExample?.spec || null;
  const showSolution = Boolean(
    solutionManifest &&
      !uploadedVtp &&
      sameGeometryContext(geometryContext, resultGeometryContext),
  );
  const title = uploadedName || metadataText(activeGeometry, "title") || "Geometry";
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
        setUploadedName(file.name);
        onGeometryContextChange(undefined);
      } else {
        const parsed = JSON.parse(await file.text()) as GeometrySpec;
        assertGeometrySpec(parsed);
        setUploadedVtp(null);
        setUploadedName(file.name);
        onGeometryContextChange({
          source: "uploaded_spec",
          id: metadataText(parsed, "id") || `upload:${file.name}`,
          name: metadataText(parsed, "title") || file.name,
          spec: parsed,
        });
      }
    } catch (uploadError) {
      setError(`Could not load ${file.name}: ${(uploadError as Error).message}`);
    }
  }

  function selectExample(id: string) {
    setUploadedVtp(null);
    setUploadedName("");
    setError("");
    const example = examples.find((item) => item.id === id);
    if (!example) {
      onGeometryContextChange(undefined);
      return;
    }
    onGeometryContextChange({
      source: "standard",
      id: example.id,
      name: metadataText(example.spec, "title") || example.id,
      spec: example.spec,
    });
  }

  return (
    <section className="scientificViewerCard">
      <header className="viewerToolbar">
        <div>
          <span className="equationEyebrow">Scientific viewport</span>
          <h3>{showSolution ? `Numerical solution on ${title}` : title}</h3>
          {!showSolution && description ? <p>{description}</p> : null}
        </div>
        <span
          className={`geometryAttachmentStatus ${geometryContext ? "attached" : ""}`}
        >
          {geometryContext ? "Attached to conversation" : "Geometry comes from chat"}
        </span>
      </header>

      <div className="geometryControls">
        <label>
          Standard geometry
          <select
            value={geometryContext?.source === "standard" ? geometryContext.id : ""}
            onChange={(event) => selectExample(event.target.value)}
          >
            <option value="">Use geometry described in chat</option>
            {examples.map((example) => (
              <option value={example.id} key={example.id}>
                {metadataText(example.spec, "title") || example.id}
              </option>
            ))}
          </select>
        </label>
        <label className="uploadGeometryButton">
          Upload GeometrySpec JSON or display-only VTP
          <input
            accept=".json,.vtp,application/json"
            onChange={handleUpload}
            type="file"
          />
        </label>
        <span className="geometryDimension">
          {activeGeometry
            ? `${activeGeometry.dimension}D / ${activeGeometry.units}`
            : "Geometry from chat"}
        </span>
      </div>

      {showSolution && solutionManifest ? (
        <VtkResultViewer manifest={solutionManifest} />
      ) : activeGeometry || uploadedVtp ? (
        <>
          {uploadedVtp ? (
            <div className="geometryNotice">
              VTP is loaded for inspection only. Attach a GeometrySpec JSON to
              use a geometry as an FEM computation domain.
            </div>
          ) : null}
          <GeometryVtkViewer
            geometry={activeGeometry}
            key={`${geometryContext?.id || "result"}:${uploadedName}`}
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
      ) : (
        <div className="viewerPlaceholder">
          Select a standard geometry, upload a GeometrySpec, or describe the
          domain in the chat request.
        </div>
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

function sameGeometryContext(
  current?: GeometryContext,
  solved?: GeometryContext,
) {
  if (!current) {
    return true;
  }
  return Boolean(
    solved && current.id === solved.id && current.source === solved.source,
  );
}
