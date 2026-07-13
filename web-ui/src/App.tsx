import { useState } from "react";
import { ChatPanel } from "./components/ChatPanel";
import { ResultWorkspace } from "./components/ResultWorkspace";
import type { WorkbenchResult } from "./types";

export function App() {
  const [result, setResult] = useState<WorkbenchResult | null>(null);

  return (
    <main className="workbench">
      <section className="chatPane">
        <header className="paneHeader">
          <div>
            <h1>AES Workbench</h1>
            <p>Agent chat and numerical result review in one window.</p>
          </div>
        </header>

        <ChatPanel onResult={setResult} />
      </section>

      <section className="resultPane">
        <ResultWorkspace result={result} />
      </section>
    </main>
  );
}
