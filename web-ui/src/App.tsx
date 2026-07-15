import { useEffect, useMemo, useState } from "react";
import { currentAuthenticatedUser, loginUser, logoutUser } from "./auth";
import { ChatPanel } from "./components/ChatPanel";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { LoginScreen } from "./components/LoginScreen";
import { ResultWorkspace } from "./components/ResultWorkspace";
import {
  loadStoredActiveConversationId,
  loadStoredConversations,
  saveStoredActiveConversationId,
  saveStoredConversations,
} from "./storage";
import type { Conversation, WorkbenchUser } from "./types";

export function App() {
  const [user, setUser] = useState<WorkbenchUser | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [authenticationError, setAuthenticationError] = useState("");

  useEffect(() => {
    let cancelled = false;
    currentAuthenticatedUser()
      .then((authenticatedUser) => {
        if (cancelled || !authenticatedUser) {
          return;
        }
        activateUser(authenticatedUser);
      })
      .catch((error) => {
        if (!cancelled) {
          setAuthenticationError((error as Error).message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsCheckingSession(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (user) {
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

  function activateUser(nextUser: WorkbenchUser) {
    const storedConversations = withDefaultConversation(
      loadStoredConversations(nextUser.username),
    );
    const storedActiveId = initialActiveConversationId(
      nextUser.username,
      storedConversations,
    );
    setUser(nextUser);
    setConversations(storedConversations);
    setActiveConversationId(storedActiveId);
    saveStoredConversations(nextUser.username, storedConversations);
    saveStoredActiveConversationId(nextUser.username, storedActiveId);
  }

  async function handleLogin(username: string, password: string) {
    const nextUser = await loginUser(username, password);
    setAuthenticationError("");
    activateUser(nextUser);
  }

  async function handleLogout() {
    try {
      await logoutUser();
    } catch (error) {
      setAuthenticationError((error as Error).message);
    } finally {
      setUser(null);
      setConversations([]);
      setActiveConversationId("");
    }
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

  function handleConversationUpdate(
    id: string,
    updater: (conversation: Conversation) => Conversation,
  ) {
    setConversations((current) =>
      current
        .map((conversation) =>
          conversation.id === id ? updater(conversation) : conversation,
        )
        .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)),
    );
    setActiveConversationId(id);
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

  if (isCheckingSession) {
    return (
      <main className="loginShell">
        <div className="loginCard">Checking AES session...</div>
      </main>
    );
  }

  if (!user || !activeConversation) {
    return (
      <LoginScreen
        initialError={authenticationError}
        onLogin={handleLogin}
      />
    );
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
            <button onClick={() => void handleLogout()} type="button">
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
            onConversationUpdate={handleConversationUpdate}
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
  username: string,
  conversations: Conversation[],
) {
  const storedId = loadStoredActiveConversationId(username);
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
