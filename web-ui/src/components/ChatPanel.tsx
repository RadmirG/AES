import { FormEvent, useEffect, useMemo, useState } from "react";
import { aesApiBaseUrl } from "../config";
import type {
  ChatCompletionResponse,
  ChatTurn,
  Conversation,
  ProgressStep,
  ProgressStatus,
} from "../types";

type Props = {
  conversation: Conversation;
  onConversationChange: (conversation: Conversation) => void;
  onConversationUpdate: (
    conversationId: string,
    updater: (conversation: Conversation) => Conversation,
  ) => void;
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

const progressTemplate: ProgressStep[] = progressLabels.map((step, index) => ({
  id: `step-${index}`,
  label: step.label,
  detail: step.detail,
  status: index === 0 ? "active" : "pending",
}));

export function ChatPanel({
  conversation,
  onConversationChange,
  onConversationUpdate,
}: Props) {
  const [input, setInput] = useState(starterPrompt);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState("");
  const [activeProgressTurnId, setActiveProgressTurnId] = useState("");

  const turns = conversation.turns;

  const requestMessages = useMemo(
    () =>
      turns
        .filter((turn) => turn.role === "user" || turn.role === "assistant")
        .map((turn) => ({ role: turn.role, content: turn.content })),
    [turns],
  );

  useEffect(() => {
    setInput(conversation.turns.length === 0 ? starterPrompt : "");
    setError("");
    setActiveProgressTurnId("");
  }, [conversation.id]);

  useEffect(() => {
    if (!isRunning || !activeProgressTurnId) {
      return;
    }

    const timer = window.setInterval(() => {
      onConversationUpdate(
        conversation.id,
        (currentConversation) =>
          updateProgressTurn(
            currentConversation,
            activeProgressTurnId,
            advanceProgressSteps(
              progressStepsForTurn(currentConversation, activeProgressTurnId),
            ),
            new Date().toISOString(),
          ),
      );
    }, 4500);

    return () => window.clearInterval(timer);
  }, [activeProgressTurnId, conversation.id, isRunning, onConversationUpdate]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning) {
      return;
    }

    const now = new Date().toISOString();
    const progressTurnId = createId();
    const nextTurns: ChatTurn[] = [
      ...turns,
      { role: "user", content: text, createdAt: now },
      {
        role: "progress",
        content: progressTurnId,
        createdAt: now,
        progressSteps: progressTemplate,
      },
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
    setActiveProgressTurnId(progressTurnId);

    try {
      const response = await fetch(`${aesApiBaseUrl}/v1/chat/completions`, {
        method: "POST",
        credentials: "include",
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
      onConversationUpdate(conversation.id, (currentConversation) => ({
        ...currentConversation,
        turns: [
          ...replaceProgressTurn(
            currentConversation.turns,
            progressTurnId,
            completeProgressSteps(
              progressStepsForTurn(currentConversation, progressTurnId),
            ),
          ),
          { role: "assistant", content: assistantText, createdAt: finishedAt },
        ],
        result: { assistantText, aesResult: data.aes_result },
        updatedAt: finishedAt,
      }));
    } catch (requestError) {
      const message = (requestError as Error).message;
      setError(message);
      onConversationUpdate(
        conversation.id,
        (currentConversation) =>
          updateProgressTurn(
            currentConversation,
            progressTurnId,
            failProgressSteps(
              progressStepsForTurn(currentConversation, progressTurnId),
              message,
            ),
            new Date().toISOString(),
          ),
      );
    } finally {
      setIsRunning(false);
      setActiveProgressTurnId("");
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
            <TurnView turn={turn} index={index} key={`${turn.role}-${index}`} />
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

function TurnView({ turn, index }: { turn: ChatTurn; index: number }) {
  if (turn.role === "progress") {
    return <ProgressLog steps={turn.progressSteps || progressTemplate} />;
  }

  return (
    <article className={`turn ${turn.role}`} key={`${turn.role}-${index}`}>
      <strong>{turn.role === "user" ? "You" : "aes-agent"}</strong>
      <pre>{turn.content}</pre>
    </article>
  );
}

function ProgressLog({ steps }: { steps: ProgressStep[] }) {
  const failedStep = steps.find((step) => step.status === "error");
  return (
    <section className="progressLog">
      <strong>AES progress</strong>
      <ol>
        {steps.map((step) => (
          <li className={`progressStep ${step.status}`} key={step.id}>
            <span>{step.label}</span>
            <small>{step.detail}</small>
          </li>
        ))}
      </ol>
      {failedStep ? <p className="warning">Request stopped: {failedStep.detail}</p> : null}
    </section>
  );
}

function advanceProgressSteps(steps: ProgressStep[]) {
  const activeIndex = steps.findIndex((step) => step.status === "active");
  if (activeIndex < 0) {
    return steps;
  }
  const nextIndex = Math.min(activeIndex + 1, steps.length - 1);
  return steps.map((step, index) => {
    if (index < nextIndex) {
      return { ...step, status: "done" as ProgressStatus };
    }
    if (index === nextIndex) {
      return { ...step, status: "active" as ProgressStatus };
    }
    return step;
  });
}

function completeProgressSteps(steps: ProgressStep[]) {
  return steps.map((step) => ({ ...step, status: "done" as ProgressStatus }));
}

function failProgressSteps(steps: ProgressStep[], message: string) {
  const activeIndex = Math.max(
    steps.findIndex((step) => step.status === "active"),
    0,
  );
  return steps.map((step, index) => {
    if (index < activeIndex) {
      return { ...step, status: "done" as ProgressStatus };
    }
    if (index === activeIndex) {
      return {
        ...step,
        detail: message,
        status: "error" as ProgressStatus,
      };
    }
    return step;
  });
}

function progressStepsForTurn(conversation: Conversation, turnId: string) {
  const turn = conversation.turns.find(
    (candidate) => candidate.role === "progress" && candidate.content === turnId,
  );
  return turn?.progressSteps || progressTemplate;
}

function updateProgressTurn(
  conversation: Conversation,
  turnId: string,
  steps: ProgressStep[],
  updatedAt: string,
) {
  return {
    ...conversation,
    updatedAt,
    turns: replaceProgressTurn(conversation.turns, turnId, steps),
  };
}

function replaceProgressTurn(
  turns: ChatTurn[],
  turnId: string,
  steps: ProgressStep[],
) {
  return turns.map((turn) => {
    if (turn.role === "progress" && turn.content === turnId) {
      return { ...turn, progressSteps: steps };
    }
    return turn;
  });
}

function createId() {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `progress-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function titleFromPrompt(prompt: string) {
  const firstLine = prompt.split(/\r?\n/).find((line) => line.trim()) || "AES chat";
  const cleaned = firstLine.trim().replace(/\s+/g, " ");
  return cleaned.length > 56 ? `${cleaned.slice(0, 53)}...` : cleaned;
}
