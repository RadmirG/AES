import type {
  AesArtifact,
  AesResult,
  Conversation,
  ProgressStatus,
  ToolResult,
} from "./types";

const CONVERSATIONS_KEY_PREFIX = "aes.workbench.conversations.v1.";
const ACTIVE_CONVERSATION_KEY_PREFIX = "aes.workbench.activeConversation.v1.";

export function loadStoredConversations(username: string): Conversation[] {
  const conversations = readJson<Conversation[]>(conversationKey(username));
  if (!Array.isArray(conversations)) {
    return [];
  }
  return conversations
    .filter(isConversation)
    .map(markInterruptedRequests)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

export function saveStoredConversations(
  username: string,
  conversations: Conversation[],
) {
  const compactConversations = conversations.map(compactConversationForStorage);
  try {
    window.localStorage.setItem(
      conversationKey(username),
      JSON.stringify(compactConversations),
    );
  } catch (error) {
    console.error("AES could not persist the local chat history.", error);
  }
}

export function loadStoredActiveConversationId(username: string): string {
  return window.localStorage.getItem(activeConversationKey(username)) || "";
}

export function saveStoredActiveConversationId(username: string, id: string) {
  if (!id) {
    return;
  }
  window.localStorage.setItem(activeConversationKey(username), id);
}

function conversationKey(username: string) {
  return `${CONVERSATIONS_KEY_PREFIX}${normalizeKey(username)}`;
}

function activeConversationKey(username: string) {
  return `${ACTIVE_CONVERSATION_KEY_PREFIX}${normalizeKey(username)}`;
}

function normalizeKey(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "_") || "default";
}

function readJson<T>(key: string): T | null {
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function isConversation(value: unknown): value is Conversation {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Partial<Conversation>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.createdAt === "string" &&
    typeof candidate.updatedAt === "string" &&
    Array.isArray(candidate.turns)
  );
}

function compactConversationForStorage(conversation: Conversation): Conversation {
  if (!conversation.result?.aesResult) {
    return conversation;
  }
  return {
    ...conversation,
    result: {
      ...conversation.result,
      aesResult: compactAesResult(conversation.result.aesResult),
    },
  };
}

function compactAesResult(result: AesResult): AesResult {
  return {
    agent_status: result.agent_status,
    next_action: result.next_action,
    generated_artifact: result.generated_artifact,
    tool_errors: result.tool_errors,
    pde_info: result.pde_info,
    domain_info: result.domain_info,
    time_info: result.time_info,
    tool_results: (result.tool_results || [])
      .filter((tool) => tool.tool_name === "artifact_store")
      .map(compactArtifactStoreResult),
  };
}

function compactArtifactStoreResult(tool: ToolResult): ToolResult {
  const manifest = isRecord(tool.output?.manifest) ? tool.output.manifest : {};
  const artifacts = Array.isArray(manifest.artifacts)
    ? manifest.artifacts.filter(isRecord).map(compactArtifact)
    : [];
  return {
    tool_name: tool.tool_name,
    provider: tool.provider,
    status: tool.status,
    error: tool.error,
    output: {
      execution_mode: tool.output?.execution_mode,
      manifest_path: tool.output?.manifest_path,
      summary_path: tool.output?.summary_path,
      manifest: {
        schema_version: manifest.schema_version,
        run_id: manifest.run_id,
        created_at: manifest.created_at,
        status: manifest.status,
        problem: manifest.problem,
        agent: manifest.agent,
        errors: manifest.errors,
        warnings: manifest.warnings,
        artifacts,
      },
    },
  };
}

function compactArtifact(value: Record<string, unknown>): AesArtifact {
  return {
    name: stringValue(value.name),
    kind: stringValue(value.kind),
    media_type: stringValue(value.media_type),
    uri: stringValue(value.uri),
    storage: stringValue(value.storage),
    status: stringValue(value.status),
    metadata: isRecord(value.metadata) ? value.metadata : undefined,
    public_url: stringValue(value.public_url) || undefined,
  };
}

function markInterruptedRequests(conversation: Conversation): Conversation {
  const turns = conversation.turns.map((turn) => {
    if (turn.role !== "progress" || !turn.progressSteps?.length) {
      return turn;
    }
    const interruptedIndex = turn.progressSteps.findIndex(
      (step) => step.status === "active" || step.status === "pending",
    );
    if (interruptedIndex < 0) {
      return turn;
    }
    return {
      ...turn,
      progressSteps: turn.progressSteps.map((step, index) => {
        if (index < interruptedIndex) {
          return { ...step, status: "done" as ProgressStatus };
        }
        if (index === interruptedIndex) {
          return {
            ...step,
            detail: "The page was reloaded before the final response was saved. Submit the request again.",
            status: "error" as ProgressStatus,
          };
        }
        return step;
      }),
    };
  });
  return { ...conversation, turns };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}
