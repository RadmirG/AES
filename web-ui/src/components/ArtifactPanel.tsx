import { publicArtifactUrl } from "../artifacts";
import type { AesArtifact } from "../types";

type Props = {
  artifacts: AesArtifact[];
};

export function ArtifactPanel({ artifacts }: Props) {
  return (
    <section className="card">
      <h3>Artifacts</h3>
      {artifacts.length === 0 ? (
        <p className="muted">No artifacts listed.</p>
      ) : (
        <ul className="artifactList">
          {artifacts.map((artifact, index) => {
            const url = publicArtifactUrl(artifact);
            return (
              <li key={`${artifact.name}-${index}`}>
                <div>
                  <strong>{artifact.name}</strong>
                  <span>{artifact.kind} / {artifact.storage}</span>
                </div>
                {url ? (
                  <a href={url} target="_blank" rel="noreferrer">
                    open
                  </a>
                ) : (
                  <span className="muted">provider-only</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

