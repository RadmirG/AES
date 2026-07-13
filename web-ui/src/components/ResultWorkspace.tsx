import { useEffect, useState } from "react";
import {
  artifactsFromResult,
  latestArtifactStore,
  manifestFromArtifactStore,
  previewUrl,
  resultLinks,
  visualizationManifestUrl,
} from "../artifacts";
import type { AesViewerManifest, WorkbenchResult } from "../types";
import { ArtifactPanel } from "./ArtifactPanel";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { VtkResultViewer } from "./VtkResultViewer";

type Props = {
  result: WorkbenchResult | null;
};

export function ResultWorkspace({ result }: Props) {
  const [viewerManifest, setViewerManifest] = useState<AesViewerManifest | null>(null);
  const [viewerError, setViewerError] = useState("");

  const aesResult = result?.aesResult;
  const artifacts = artifactsFromResult(aesResult);
  const links = resultLinks(aesResult);
  const preview = previewUrl(aesResult);
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

  if (!result) {
    return (
      <div className="resultEmpty">
        <h2>Results will appear here</h2>
        <p>Run a solve from the chat panel to populate previews and artifacts.</p>
      </div>
    );
  }

  return (
    <div className="resultWorkspace">
      <header className="resultHeader">
        <div>
          <h2>{aesResult?.pde_info || "AES result"}</h2>
          <p>
            Status: <strong>{aesResult?.agent_status || "unknown"}</strong> | Next:{" "}
            <strong>{aesResult?.next_action || "unknown"}</strong>
          </p>
        </div>
        <div className="statusBadge">{artifactStatus}</div>
      </header>

      <section className="linkStrip">
        {links.length === 0 ? (
          <span className="muted">No AES-owned artifact links yet.</span>
        ) : (
          links.map((link) => (
            <a href={link.url} target="_blank" rel="noreferrer" key={link.name}>
              {labelFor(link.name)}
            </a>
          ))
        )}
      </section>

      <section className="previewGrid">
        <div className="previewCard">
          <h3>Preview</h3>
          {preview ? (
            <iframe title="AES preview" src={preview} />
          ) : (
            <p className="muted">No preview.svg artifact found.</p>
          )}
        </div>

        <div className="previewCard">
          <h3>Interactive Viewer</h3>
          {viewerManifest ? (
            <VtkResultViewer manifest={viewerManifest} />
          ) : (
            <p className="muted">
              {viewerError || "No viewer_manifest.json loaded yet."}
            </p>
          )}
        </div>
      </section>

      {viewerManifest ? <DiagnosticsPanel manifest={viewerManifest} /> : null}
      <ArtifactPanel artifacts={artifacts} />
    </div>
  );
}

function labelFor(name: string) {
  const labels: Record<string, string> = {
    "viewer.html": "Viewer",
    "preview.svg": "Preview",
    "viewer_manifest.json": "Manifest",
    "diagnostics.json": "Diagnostics",
    "solve.py": "solve.py",
    "stdout.txt": "stdout",
  };
  return labels[name] || name;
}
