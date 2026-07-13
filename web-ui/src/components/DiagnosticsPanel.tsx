import type { AesViewerManifest } from "../types";

type Props = {
  manifest: AesViewerManifest;
};

export function DiagnosticsPanel({ manifest }: Props) {
  const diagnostics = manifest.diagnostics || {};
  const script = (diagnostics.script || {}) as Record<string, unknown>;

  return (
    <section className="card">
      <h3>Diagnostics</h3>
      <dl className="kv">
        <dt>Run id</dt>
        <dd>{String(diagnostics.run_id || "not available")}</dd>
        <dt>Runtime</dt>
        <dd>{formatNumber(diagnostics.elapsed_seconds)} s</dd>
        <dt>Return code</dt>
        <dd>{String(diagnostics.return_code ?? "not available")}</dd>
        <dt>DOFs</dt>
        <dd>{String(script.num_dofs || "not available")}</dd>
        <dt>Steps</dt>
        <dd>{String(script.num_steps || "not available")}</dd>
        <dt>Final max</dt>
        <dd>{formatNumber(script.solution_max)}</dd>
      </dl>
      {manifest.warnings?.length ? (
        <div className="warning">
          {manifest.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function formatNumber(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "not available";
  }
  return number.toPrecision(6).replace(/\.?0+$/, "");
}

