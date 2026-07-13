import { useEffect, useMemo, useState } from "react";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { VtkResultViewer } from "./components/VtkResultViewer";
import type { AesViewerManifest } from "./types";

const defaultManifestPath = "/viewer_manifest.json";

export function App() {
  const [manifest, setManifest] = useState<AesViewerManifest | null>(null);
  const [error, setError] = useState("");

  const manifestUrl = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("manifest") || defaultManifestPath;
  }, []);

  useEffect(() => {
    fetch(manifestUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Manifest request failed: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => setManifest(data as AesViewerManifest))
      .catch((requestError: Error) => setError(requestError.message));
  }, [manifestUrl]);

  if (error) {
    return (
      <main className="shell">
        <section className="empty">
          <h1>AES Visualization UI</h1>
          <p>{error}</p>
          <p className="muted">Pass a manifest URL with ?manifest=...</p>
        </section>
      </main>
    );
  }

  if (!manifest) {
    return (
      <main className="shell">
        <section className="empty">Loading AES visualization manifest...</section>
      </main>
    );
  }

  return (
    <main className="shell">
      <section className="viewerRegion">
        <VtkResultViewer manifest={manifest} />
      </section>
      <aside className="sidePanel">
        <h1>AES Visualization</h1>
        <p className="muted">{manifest.problem.pde || "Unknown PDE"}</p>
        <DiagnosticsPanel manifest={manifest} />
        <ArtifactPanel manifest={manifest} />
      </aside>
    </main>
  );
}

