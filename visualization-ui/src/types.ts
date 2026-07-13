export type AesArtifact = {
  name: string;
  kind: string;
  media_type: string;
  uri: string;
  storage: string;
  status: string;
  metadata?: Record<string, unknown>;
  public_url?: string;
};

export type AesViewerManifest = {
  schema_version: string;
  created_at: string;
  provider: string;
  source_tool: string;
  problem: Record<string, string>;
  diagnostics: Record<string, unknown>;
  datasets: {
    vtkjs_readable: AesArtifact[];
    raw_solution: AesArtifact[];
    all_artifacts: AesArtifact[];
  };
  preview: {
    static: string;
    interactive: string;
    recommended_frontend: string;
  };
  capabilities: Record<string, boolean>;
  warnings: string[];
};

