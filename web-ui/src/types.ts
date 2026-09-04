export type ChatRole = "user" | "assistant" | "progress";

export type ChatTurn = {
  role: ChatRole;
  content: string;
  createdAt?: string;
  progressSteps?: ProgressStep[];
};

export type WorkbenchUser = {
  id: string;
  username: string;
  displayName: string;
  createdAt: string;
};

export type Conversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ChatTurn[];
  geometryContext?: GeometryContext;
  result?: WorkbenchResult;
};

export type ProgressStatus = "pending" | "active" | "done" | "error";

export type ProgressStep = {
  id: string;
  label: string;
  detail: string;
  status: ProgressStatus;
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
  coefficient_info?: string;
  source_info?: string;
  bc_info?: string;
  initial_condition_info?: string;
  time_info?: string;
  pde_spec?: PDEProblemSpec;
  geometry_spec?: GeometrySpec;
  geometry_spec_source?: string;
};

export type ExpressionSpec = {
  kind: "constant" | "symbolic";
  value: string;
  variables?: string[];
};

export type PDEProblemSpec = {
  schema_version: string;
  problem_class: string;
  spatial_dimension: number;
  equation: {
    family: "stationary_diffusion" | "transient_diffusion" | "custom";
    unknown: string;
    strong_form: string;
    diffusion: ExpressionSpec;
    source: ExpressionSpec;
  };
  boundary_conditions: Array<{
    name: string;
    region: string;
    type: "dirichlet" | "neumann" | "robin";
    value: ExpressionSpec;
  }>;
  initial_condition?: { value: ExpressionSpec } | null;
  time?: {
    t0: number;
    t_end: number;
    dt: number;
    scheme: string;
  } | null;
  function_space?: {
    family: string;
    degree: number;
    value_shape: number[];
  };
  solver?: Record<string, unknown>;
  assumptions?: string[];
};

export type GeometryPrimitive = {
  id: string;
  shape: "rectangle" | "disk" | "box" | "sphere" | "cylinder";
  origin?: number[];
  size?: number[];
  center?: number[];
  radius?: number;
  axis?: number[];
  height?: number;
};

export type GeometrySpec = {
  schema_version: string;
  dimension: 1 | 2 | 3;
  units: string;
  source: {
    kind: "primitives" | "csg" | "cad" | "mesh_file" | "surface_scan";
    primitives?: GeometryPrimitive[];
    operations?: Array<{
      type: "union" | "difference" | "intersection" | "fragment";
      objects: string[];
      tools: string[];
      result: string;
    }>;
  };
  regions: Array<{
    name: string;
    dimension: number;
    selector: Record<string, unknown>;
  }>;
  mesh: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type GeometryExampleIndexItem = {
  id: string;
  spec: string;
};

export type GeometryContext = {
  source: "standard" | "uploaded_spec";
  id: string;
  name: string;
  spec: GeometrySpec;
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
    sampled_field?: SampledFieldDataset;
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

export type SampledFieldDataset = {
  type: string;
  field: string;
  domain: string;
  space: string;
  coordinates: number[][];
  topology?: {
    format: "vtk_cell_array";
    cells: number[];
    cell_types: number[];
    cell_count: number;
    topological_dimension: number;
  };
  samples: Array<{
    step: number;
    time: number;
    values: number[];
  }>;
  value_range?: {
    min: number;
    max: number;
  };
};

export type WorkbenchResult = {
  assistantText: string;
  aesResult?: AesResult;
  geometryContext?: GeometryContext;
};
