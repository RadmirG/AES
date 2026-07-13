import { useEffect, useMemo, useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { LoginScreen } from "./components/LoginScreen";
import { ResultWorkspace } from "./components/ResultWorkspace";
import {
  clearStoredUser,
  loadStoredActiveConversationId,
  loadStoredConversations,
  loadStoredUser,
  saveStoredActiveConversationId,
  saveStoredConversations,
  saveStoredUser,
} from "./storage";
import type { Conversation, WorkbenchUser } from "./types";

export function App() {
  const [user, setUser] = useState<WorkbenchUser | null>(() => loadStoredUser());
  const [conversations, setConversations] = useState<Conversation[]>(() =>
    user ? withDefaultConversation(loadStoredConversations(user.username)) : [],
  );
  const [activeConversationId, setActiveConversationId] = useState(
    () => initialActiveConversationId(user, conversations),
  );

  useEffect(() => {
    if (user) {
      saveStoredUser(user);
      saveStoredConversations(user.username, conversations);
      saveStoredActiveConversationId(user.username, activeConversationId);
    }
  }, [user, conversations, activeConversationId]);

  const activeConversation = useMemo(
    () =>
      conversations.find((conversation) => conversation.id === activeConversationId) ||
      conversations[0],
    [activeConversationId, conversations],
  );

  function handleLogin(nextUser: WorkbenchUser) {
    const storedConversations = withDefaultConversation(
      loadStoredConversations(nextUser.username),
    );
    const storedActiveId = initialActiveConversationId(
      nextUser,
      storedConversations,
    );
    setUser(nextUser);
    setConversations(storedConversations);
    setActiveConversationId(storedActiveId);
    saveStoredUser(nextUser);
    saveStoredConversations(nextUser.username, storedConversations);
    saveStoredActiveConversationId(nextUser.username, storedActiveId);
  }

  function handleLogout() {
    clearStoredUser();
    setUser(null);
    setConversations([]);
    setActiveConversationId("");
  }

  function handleNewConversation() {
    const conversation = createConversation();
    setConversations((current) => [conversation, ...current]);
    setActiveConversationId(conversation.id);
  }

  function handleConversationChange(nextConversation: Conversation) {
    setConversations((current) =>
      current
        .map((conversation) =>
          conversation.id === nextConversation.id ? nextConversation : conversation,
        )
        .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
    );
    setActiveConversationId(nextConversation.id);
  }

  function handleDeleteConversation(id: string) {
    const remaining = withDefaultConversation(
      conversations.filter((conversation) => conversation.id !== id),
    );
    setConversations(remaining);
    if (id === activeConversationId) {
      setActiveConversationId(remaining[0].id);
    }
  }

  if (!user || !activeConversation) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  return (
    <main className="workbench">
      <section className="chatPane">
        <header className="paneHeader">
          <div>
            <h1>AES Workbench</h1>
            <p>Agent chat and numerical result review in one window.</p>
          </div>
          <div className="userMenu">
            <span>{user.displayName}</span>
            <button onClick={handleLogout} type="button">
              Sign out
            </button>
          </div>
        </header>

        <div className="chatShell">
          <ConversationSidebar
            conversations={conversations}
            activeConversationId={activeConversation.id}
            onSelect={setActiveConversationId}
            onNew={handleNewConversation}
            onDelete={handleDeleteConversation}
          />
          <ChatPanel
            conversation={activeConversation}
            onConversationChange={handleConversationChange}
          />
        </div>
      </section>

      <section className="resultPane">
        <ResultWorkspace result={activeConversation.result || null} />
      </section>
    </main>
  );
}

function withDefaultConversation(conversations: Conversation[]) {
  return conversations.length > 0 ? conversations : [createConversation()];
}

function initialActiveConversationId(
  user: WorkbenchUser | null,
  conversations: Conversation[],
) {
  if (!user) {
    return conversations[0]?.id || "";
  }
  const storedId = loadStoredActiveConversationId(user.username);
  if (storedId && conversations.some((conversation) => conversation.id === storedId)) {
    return storedId;
  }
  return conversations[0]?.id || "";
}

function createConversation(): Conversation {
  const now = new Date().toISOString();
  return {
    id: createId(),
    title: "New AES chat",
    createdAt: now,
    updatedAt: now,
    turns: [],
  };
}

function createId() {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
