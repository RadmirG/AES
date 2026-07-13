import { FormEvent, useEffect, useMemo, useState } from "react";
import { aesApiBaseUrl } from "../config";
import type {
  ChatCompletionResponse,
  ChatTurn,
  Conversation,
  ProgressStatus,
} from "../types";

type Props = {
  conversation: Conversation;
  onConversationChange: (conversation: Conversation) => void;
};

const starterPrompt = `Solve the transient heat equation on the unit square Omega=[0,1]^2.
Use du/dt = alpha * Delta(u) + f with alpha=1 and f=1.
Use u=0 on the boundary.
Use initial condition u(x,y,0)=sin(pi*x)sin(pi*y).
Use final time T=1 and time step dt=0.01.`;

const progressLabels = [
  {
    label: "Request sent to AES",
    detail: "Workbench posted the chat history to /v1/chat/completions.",
  },
  {
    label: "LangGraph request gate",
    detail: "AES detects whether the latest message is an engineering/PDE task.",
  },
  {
    label: "Problem extraction",
    detail: "AES classifies the PDE, domain, coefficients, source, boundary data, and time data.",
  },
  {
    label: "Formulation and mode selection",
    detail: "AES validates the formulation and selects summary, code generation, or execution mode.",
  },
  {
    label: "FEniCS code/tool phase",
    detail: "AES may call Ollama, check generated code, and run the FEniCS sandbox.",
  },
  {
    label: "Artifacts and visualization",
    detail: "AES stores manifests, diagnostics, previews, and viewer files.",
  },
  {
    label: "Waiting for final response",
    detail: "The right pane updates when the response returns with aes_result.",
  },
];

export function ChatPanel({ conversation, onConversationChange }: Props) {
  const [input, setInput] = useState(starterPrompt);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");
  const [progressIndex, setProgressIndex] = useState(-1);
  const [progressError, setProgressError] = useState("");

  const turns = conversation.turns;

  const requestMessages = useMemo(
    () => turns.map((turn) => ({ role: turn.role, content: turn.content })),
    [turns],
  );

  useEffect(() => {
    setInput(conversation.turns.length === 0 ? starterPrompt : "");
    setError("");
    setProgressError("");
    setProgressIndex(-1);
  }, [conversation.id]);

  useEffect(() => {
    if (!isRunning) {
      return;
    }

    const timer = window.setInterval(() => {
      setProgressIndex((current) =>
        Math.min(current + 1, progressLabels.length - 1),
      );
    }, 4500);

    return () => window.clearInterval(timer);
  }, [isRunning]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning) {
      return;
    }

    const now = new Date().toISOString();
    const nextTurns: ChatTurn[] = [
      ...turns,
      { role: "user", content: text, createdAt: now },
    ];
    const nextConversation = {
      ...conversation,
      title: conversation.turns.length === 0 ? titleFromPrompt(text) : conversation.title,
      turns: nextTurns,
      updatedAt: now,
    };
    onConversationChange(nextConversation);
    setInput("");
    setIsRunning(true);
    setError("");
    setProgressError("");
    setProgressIndex(0);

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
      const finishedAt = new Date().toISOString();
      onConversationChange({
        ...nextConversation,
        turns: [
          ...nextTurns,
          { role: "assistant", content: assistantText, createdAt: finishedAt },
        ],
        result: { assistantText, aesResult: data.aes_result },
        updatedAt: finishedAt,
      });
      setProgressIndex(progressLabels.length - 1);
    } catch (requestError) {
      const message = (requestError as Error).message;
      setError(message);
      setProgressError(message);
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
        {isRunning || progressIndex >= 0 ? (
          <ProgressLog activeIndex={progressIndex} error={progressError} />
        ) : null}
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

function ProgressLog({
  activeIndex,
  error,
}: {
  activeIndex: number;
  error: string;
}) {
  return (
    <section className="progressLog">
      <strong>AES progress</strong>
      <ol>
        {progressLabels.map((step, index) => {
          const status = statusForStep(index, activeIndex, error);
          return (
            <li className={`progressStep ${status}`} key={step.label}>
              <span>{step.label}</span>
              <small>{step.detail}</small>
            </li>
          );
        })}
      </ol>
      {error ? <p className="warning">Request stopped: {error}</p> : null}
    </section>
  );
}

function statusForStep(
  index: number,
  activeIndex: number,
  error: string,
): ProgressStatus {
  if (error && index === activeIndex) {
    return "error";
  }
  if (index < activeIndex) {
    return "done";
  }
  if (index === activeIndex) {
    return "active";
  }
  return "pending";
}

function titleFromPrompt(prompt: string) {
  const firstLine = prompt.split(/\r?\n/).find((line) => line.trim()) || "AES chat";
  const cleaned = firstLine.trim().replace(/\s+/g, " ");
  return cleaned.length > 56 ? `${cleaned.slice(0, 53)}...` : cleaned;
}
