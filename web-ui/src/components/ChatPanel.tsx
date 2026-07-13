import { FormEvent, useMemo, useState } from "react";
import { aesApiBaseUrl } from "../config";
import type { ChatCompletionResponse, ChatTurn, WorkbenchResult } from "../types";

type Props = {
  onResult: (result: WorkbenchResult) => void;
};

const starterPrompt = `Solve the transient heat equation on the unit square Omega=[0,1]^2.
Use du/dt = alpha * Delta(u) + f with alpha=1 and f=1.
Use u=0 on the boundary.
Use initial condition u(x,y,0)=sin(pi*x)sin(pi*y).
Use final time T=1 and time step dt=0.01.`;

export function ChatPanel({ onResult }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState(starterPrompt);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");

  const requestMessages = useMemo(
    () => turns.map((turn) => ({ role: turn.role, content: turn.content })),
    [turns],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning) {
      return;
    }

    const nextTurns: ChatTurn[] = [...turns, { role: "user", content: text }];
    setTurns(nextTurns);
    setInput("");
    setIsRunning(true);
    setError("");

    try {
      const response = await fetch(`${aesApiBaseUrl}/v1/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "aes-agent",
          stream: false,
          messages: [...requestMessages, { role: "user", content: text }],
        }),
      });
      if (!response.ok) {
        throw new Error(`AES request failed: ${response.status}`);
      }
      const data = (await response.json()) as ChatCompletionResponse;
      const assistantText = data.choices?.[0]?.message?.content || "";
      setTurns([...nextTurns, { role: "assistant", content: assistantText }]);
      onResult({ assistantText, aesResult: data.aes_result });
    } catch (requestError) {
      setError((requestError as Error).message);
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <div className="chatPanel">
      <div className="turnList">
        {turns.length === 0 ? (
          <div className="emptyState">
            <h2>Ask AES to solve or analyze a PDE</h2>
            <p>The result workspace will update when AES returns artifacts.</p>
          </div>
        ) : (
          turns.map((turn, index) => (
            <article className={`turn ${turn.role}`} key={`${turn.role}-${index}`}>
              <strong>{turn.role === "user" ? "You" : "aes-agent"}</strong>
              <pre>{turn.content}</pre>
            </article>
          ))
        )}
      </div>

      {error ? <div className="errorBox">{error}</div> : null}

      <form className="composer" onSubmit={submit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Describe the engineering/PDE problem..."
        />
        <button disabled={isRunning || !input.trim()} type="submit">
          {isRunning ? "Running..." : "Send"}
        </button>
      </form>
    </div>
  );
}

