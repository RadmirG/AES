import { useEffect, useMemo, useState } from "react";
import { currentAuthenticatedUser, loginUser, logoutUser } from "./auth";
import { loadModelCatalog } from "./backend";
import { useRunRecovery } from "./useRunRecovery";
import { BackendLogPanel } from "./components/BackendLogPanel";
import { ChatPanel } from "./components/ChatPanel";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { LoginScreen } from "./components/LoginScreen";
import { ResultWorkspace } from "./components/ResultWorkspace";
import { PanelErrorBoundary } from "./components/PanelErrorBoundary";
import {
  loadStoredActiveConversationId,
  loadStoredConversations,
  saveStoredActiveConversationId,
  saveStoredConversations,
} from "./storage";
import type {
  Conversation,
  GeometryContext,
  ModelCatalog,
  WorkbenchUser,
} from "./types";

export function App() {
  const [user, setUser] = useState<WorkbenchUser | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [authenticationError, setAuthenticationError] = useState("");
  const [leftMode, setLeftMode] = useState<"chat" | "logs">("chat");
  const [modelCatalog, setModelCatalog] = useState<ModelCatalog | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [modelError, setModelError] = useState("");
  const isSolveRunning = conversations.some((conversation) => Boolean(conversation.pendingRun));
  useRunRecovery(user?.id, conversations, handleConversationUpdate);

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
    if (!user) {
      setModelCatalog(null);
      setSelectedModel("");
      return;
    }
    let cancelled = false;
    loadModelCatalog()
      .then((catalog) => {
        if (cancelled) {
          return;
        }
        const storedModel = window.localStorage.getItem(modelKey(user.username)) || "";
        const availableIds = new Set(catalog.models.map((model) => model.id));
        const nextModel = availableIds.has(storedModel)
          ? storedModel
          : catalog.default_model;
        setModelCatalog(catalog);
        setSelectedModel(nextModel);
        setModelError(catalog.warning || "");
      })
      .catch((error) => {
        if (!cancelled) {
          setModelError((error as Error).message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  useEffect(() => {
    if (user && selectedModel) {
      window.localStorage.setItem(modelKey(user.username), selectedModel);
    }
  }, [selectedModel, user]);

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
      setLeftMode("chat");
    }
  }

  function handleNewConversation() {
    const conversation = createConversation();
    setConversations((current) => [conversation, ...current]);
    setActiveConversationId(conversation.id);
  }

  function handleConversationChange(nextConversation: Conversation) {
    if (user && nextConversation.pendingRun) {
      saveStoredConversations(user.username, conversations.map((conversation) =>
        conversation.id === nextConversation.id ? nextConversation : conversation,
      ), true);
    }
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
  }

  function handleDeleteConversation(id: string) {
    if (conversations.find((conversation) => conversation.id === id)?.pendingRun) return;
    const remaining = withDefaultConversation(
      conversations.filter((conversation) => conversation.id !== id),
    );
    setConversations(remaining);
    if (id === activeConversationId) {
      setActiveConversationId(remaining[0].id);
    }
  }

  function handleGeometryContextChange(context?: GeometryContext) {
    if (isSolveRunning) {
      return;
    }
    handleConversationUpdate(activeConversation.id, (conversation) => ({
      ...conversation,
      geometryContext: context,
      updatedAt: new Date().toISOString(),
    }));
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
            <div className="workspaceModeSwitch" aria-label="Left workspace mode">
              <button
                className={leftMode === "chat" ? "active" : ""}
                onClick={() => setLeftMode("chat")}
                type="button"
              >
                Chat
              </button>
              <button
                className={leftMode === "logs" ? "active" : ""}
                onClick={() => setLeftMode("logs")}
                type="button"
              >
                Logs
              </button>
            </div>
            <label className="modelSelector" title={modelError || "Select the LLM used by AES for this request."}>
              <span>{modelCatalog?.provider || "LLM"}</span>
              <select
                disabled={isSolveRunning || !modelCatalog?.models.length}
                onChange={(event) => setSelectedModel(event.target.value)}
                value={selectedModel}
              >
                {(modelCatalog?.models || []).map((model) => (
                  <option key={model.id} value={model.id}>{model.label}</option>
                ))}
              </select>
            </label>
            <span>{user.displayName}</span>
            <button onClick={() => void handleLogout()} type="button">
              Sign out
            </button>
          </div>
        </header>

        <PanelErrorBoundary name="Chat and logs" resetKeys={[activeConversation.id, leftMode]}>
          {leftMode === "chat" ? (
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
                isRunning={isSolveRunning}
                selectedModel={selectedModel || modelCatalog?.default_model || ""}
                onConversationChange={handleConversationChange}
                onGeometryContextChange={handleGeometryContextChange}
              />
            </div>
          ) : (
            <BackendLogPanel active={leftMode === "logs"} />
          )}
        </PanelErrorBoundary>
      </section>

      <section className="resultPane">
        <PanelErrorBoundary name="Results" resetKeys={[activeConversation.id, activeConversation.result]}>
          <ResultWorkspace
            geometryContext={activeConversation.geometryContext}
            isRunning={isSolveRunning}
            onGeometryContextChange={handleGeometryContextChange}
            result={activeConversation.result || null}
          />
        </PanelErrorBoundary>
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

function modelKey(username: string) {
  const normalized = username.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "_");
  return `aes.workbench.backendModel.v1.${normalized || "default"}`;
}
