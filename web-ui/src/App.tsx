import { useState } from "react";
import { openWebUiUrl } from "./config";
import { ChatPanel } from "./components/ChatPanel";
import { OpenWebUiFrame } from "./components/OpenWebUiFrame";
import { ResultWorkspace } from "./components/ResultWorkspace";
import type { WorkbenchResult } from "./types";

type ChatMode = "native" | "openwebui";

export function App() {
  const [result, setResult] = useState<WorkbenchResult | null>(null);
  const [chatMode, setChatMode] = useState<ChatMode>("native");

  const canEmbedOpenWebUi = Boolean(openWebUiUrl);

  return (
    <main className="workbench">
      <section className="chatPane">
        <header className="paneHeader">
          <div>
            <h1>AES Workbench</h1>
            <p>Agent chat and numerical result review in one window.</p>
          </div>
          <div className="modeSwitch">
            <button
              className={chatMode === "native" ? "active" : ""}
              onClick={() => setChatMode("native")}
            >
              AES Chat
            </button>
            <button
              disabled={!canEmbedOpenWebUi}
              className={chatMode === "openwebui" ? "active" : ""}
              onClick={() => setChatMode("openwebui")}
            >
              Open WebUI
            </button>
          </div>
        </header>

        {chatMode === "openwebui" && canEmbedOpenWebUi ? (
          <OpenWebUiFrame />
        ) : (
          <ChatPanel onResult={setResult} />
        )}
      </section>

      <section className="resultPane">
        <ResultWorkspace result={result} />
      </section>
    </main>
  );
}

