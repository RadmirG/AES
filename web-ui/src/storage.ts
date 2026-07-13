import type { Conversation, WorkbenchUser } from "./types";

const USER_KEY = "aes.workbench.user.v1";
const CONVERSATIONS_KEY_PREFIX = "aes.workbench.conversations.v1.";
const ACTIVE_CONVERSATION_KEY_PREFIX = "aes.workbench.activeConversation.v1.";

export function loadStoredUser(): WorkbenchUser | null {
  return readJson<WorkbenchUser>(USER_KEY);
}

export function saveStoredUser(user: WorkbenchUser) {
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearStoredUser() {
  window.localStorage.removeItem(USER_KEY);
}

export function loadStoredConversations(username: string): Conversation[] {
  const conversations = readJson<Conversation[]>(conversationKey(username));
  if (!Array.isArray(conversations)) {
    return [];
  }
  return conversations
    .filter(isConversation)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

export function saveStoredConversations(
  username: string,
  conversations: Conversation[],
) {
  window.localStorage.setItem(
    conversationKey(username),
    JSON.stringify(conversations),
  );
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
