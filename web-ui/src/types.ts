export type ChatRole = "user" | "assistant";

export type ChatTurn = {
  role: ChatRole;
  content: string;
};

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

export type ToolResult = {
  tool_name: string;
  provider: string;
  status: string;
  output: Record<string, unknown>;
  error: string;
};

export type AesResult = {
  agent_status?: string;
  next_action?: string;
  generated_artifact?: string;
  tool_results?: ToolResult[];
  tool_errors?: string[];
  pde_info?: string;
  domain_info?: string;
  time_info?: string;
};

export type ChatCompletionResponse = {
  choices: Array<{
    message: {
      role: string;
      content: string;
    };
  }>;
  aes_result?: AesResult;
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

export type WorkbenchResult = {
  assistantText: string;
  aesResult?: AesResult;
};

