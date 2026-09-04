import { useEffect, useState } from "react";
import {
  artifactsFromResult,
  latestArtifactStore,
  manifestFromArtifactStore,
  resultLinks,
  visualizationManifestUrl,
} from "../artifacts";
import type {
  AesViewerManifest,
  GeometryContext,
  WorkbenchResult,
} from "../types";
import { ArtifactPanel } from "./ArtifactPanel";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { EquationSummary } from "./EquationSummary";
import { GeometryExplorer } from "./GeometryExplorer";

type Props = {
  geometryContext?: GeometryContext;
  isRunning: boolean;
  onGeometryContextChange: (context?: GeometryContext) => void;
  result: WorkbenchResult | null;
};

export function ResultWorkspace({
  geometryContext,
  isRunning,
  onGeometryContextChange,
  result,
}: Props) {
  const [viewerManifest, setViewerManifest] = useState<AesViewerManifest | null>(null);
  const [viewerError, setViewerError] = useState("");

  const aesResult = result?.aesResult;
  const artifacts = artifactsFromResult(aesResult);
  const links = resultLinks(aesResult).filter((link) =>
    ["viewer_manifest.json", "stdout.txt"].includes(link.name),
  );
  const manifestUrl = visualizationManifestUrl(aesResult);
  const artifactStore = latestArtifactStore(aesResult);
  const artifactManifest = manifestFromArtifactStore(artifactStore);
  const artifactStatus =
    typeof artifactManifest?.status === "string" ? artifactManifest.status : "no manifest";

  useEffect(() => {
    setViewerManifest(null);
    setViewerError("");
    if (!manifestUrl) {
      return;
    }

    fetch(manifestUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Viewer manifest request failed: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => setViewerManifest(data as AesViewerManifest))
      .catch((error: Error) => setViewerError(error.message));
  }, [manifestUrl]);

  return (
    <div className="resultWorkspace">
      {result ? (
        <EquationSummary aesResult={aesResult} status={artifactStatus} />
      ) : (
        <header className="geometryIntro">
          <span className="equationEyebrow">Geometry workspace</span>
          <h2>Select or upload a geometry</h2>
          <p>
            Inspect a standard AES geometry now. A validated PDE formulation and
            numerical solution will appear here after a solve.
          </p>
        </header>
      )}

      <GeometryExplorer
        geometryContext={geometryContext}
        isRunning={isRunning}
        onGeometryContextChange={onGeometryContextChange}
        resultGeometry={aesResult?.geometry_spec || null}
        resultGeometryContext={result?.geometryContext}
        solutionManifest={viewerManifest}
      />

      {viewerError ? <div className="viewerError">{viewerError}</div> : null}

      {result ? <section className="artifactActions" aria-label="Result files">
        <span>Run files</span>
        {links.length === 0 ? (
          <span className="muted">Manifest and stdout are not available.</span>
        ) : (
          links.map((link) => (
            <a href={link.url} target="_blank" rel="noreferrer" key={link.name}>
              {labelFor(link.name)}
            </a>
          ))
        )}
      </section> : null}

      {viewerManifest ? <DiagnosticsPanel manifest={viewerManifest} /> : null}
      {result ? <ArtifactPanel artifacts={artifacts} /> : null}
    </div>
  );
}

function labelFor(name: string) {
  const labels: Record<string, string> = {
    "viewer_manifest.json": "Manifest",
    "stdout.txt": "stdout",
  };
  return labels[name] || name;
}
