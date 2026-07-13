import type { AesArtifact, AesViewerManifest } from "../types";

type Props = {
  manifest: AesViewerManifest;
};

export function ArtifactPanel({ manifest }: Props) {
  const artifacts = manifest.datasets.all_artifacts || [];
  return (
    <section className="card">
      <h2>Artifacts</h2>
      {artifacts.length === 0 ? (
        <p className="muted">No artifacts listed.</p>
      ) : (
        <ul className="artifactList">
          {artifacts.map((artifact, index) => (
            <ArtifactItem key={`${artifact.name}-${index}`} artifact={artifact} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ArtifactItem({ artifact }: { artifact: AesArtifact }) {
  const href = artifact.public_url || toFetchableUrl(artifact.uri);
  return (
    <li>
      <strong>{artifact.name}</strong>
      <span className="muted"> {artifact.kind} / {artifact.storage}</span>
      {href ? (
        <a href={href} target="_blank" rel="noreferrer">open</a>
      ) : (
        <span className="muted">not browser-fetchable yet</span>
      )}
    </li>
  );
}

function toFetchableUrl(uri: string) {
  if (!uri) {
    return "";
  }
  if (uri.startsWith("http://") || uri.startsWith("https://") || uri.startsWith("/")) {
    return uri;
  }
  return "";
}

