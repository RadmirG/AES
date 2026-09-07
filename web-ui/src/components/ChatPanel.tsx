import { FormEvent, useEffect, useState } from "react";
import type { ChatTurn, Conversation, GeometryContext, ProgressStep } from "../types";
import { ProblemCatalog } from "./ProblemCatalog";

type Props = {
  conversation: Conversation;
  isRunning: boolean;
  selectedModel: string;
  onGeometryContextChange: (context?: GeometryContext) => void;
  onConversationChange: (conversation: Conversation) => void;
};

const starterPrompt = `Solve the transient heat equation on the unit square Omega=[0,1]^2.
Use du/dt = alpha * Delta(u) + f with alpha=1 and f=1.
Use u=0 on the boundary.
Use initial condition u(x,y,0)=sin(pi*x)sin(pi*y).
Use final time T=1 and time step dt=0.01.`;

export function ChatPanel({ conversation, isRunning, selectedModel, onGeometryContextChange, onConversationChange }: Props) {
  const [input, setInput] = useState(starterPrompt);
  const [error, setError] = useState("");

  useEffect(() => {
    setInput(conversation.turns.length === 0 ? starterPrompt : "");
    setError("");
  }, [conversation.id]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isRunning) return;
    const now = new Date().toISOString();
    const runId = createRunId();
    const nextTurns: ChatTurn[] = [
      ...conversation.turns,
      { role: "user", content: text, createdAt: now },
      { role: "progress", content: runId, createdAt: now, runId, progressSteps: [{
        id: "submission", label: "Submitting request to AES",
        detail: "The saved request ID allows reconnection after a refresh.", status: "active",
      }] },
    ];
    try {
      // App persists this snapshot before its recovery hook sends a request.
      // Losing a POST acknowledgement cannot lose the request ID.
      onConversationChange({
        ...conversation,
        title: conversation.turns.length === 0 ? titleFromPrompt(text) : conversation.title,
        turns: nextTurns,
        updatedAt: now,
        runConnectionError: "",
        pendingRun: {
          id: runId, progressTurnId: runId, geometryContext: conversation.geometryContext,
          request: {
            run_id: runId, conversation_id: conversation.id,
            model: "aes-agent", backend_model: selectedModel, stream: false,
            messages: nextTurns.filter((turn) => turn.role !== "progress")
              .map((turn) => ({ role: turn.role, content: turn.content })),
            geometry_spec: conversation.geometryContext?.spec,
          },
        },
      });
      setInput("");
      setError("");
    } catch (submissionError) {
      setError((submissionError as Error).message);
    }
  }

  return (
    <div className="chatPanel">
      <div className="turnList">
        {conversation.turns.length === 0 ? (
          <div className="emptyState">
            <h2>Ask AES to solve or analyze a PDE</h2>
            <p>The result workspace will update when AES returns artifacts.</p>
          </div>
        ) : conversation.turns.map((turn, index) => <TurnView turn={turn} key={`${turn.role}-${index}`} />)}
      </div>
      {error || conversation.runConnectionError ? <div className="errorBox">{error || conversation.runConnectionError}</div> : null}
      <form className="composer" onSubmit={submit}>
        <ProblemCatalog disabled={isRunning} onGeometryContextChange={onGeometryContextChange} onPromptChange={setInput} />
        {conversation.geometryContext ? (
          <div className="attachedGeometryNotice"><span>Attached geometry</span><strong>{conversation.geometryContext.name}</strong></div>
        ) : null}
        <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="Describe the engineering/PDE problem..." rows={4} />
        <button disabled={isRunning || !input.trim()} type="submit">{isRunning ? "Running..." : "Send"}</button>
      </form>
    </div>
  );
}

function TurnView({ turn }: { turn: ChatTurn }) {
  if (turn.role === "progress") return <ProgressLog steps={turn.progressSteps || []} />;
  return <article className={`turn ${turn.role}`}><strong>{turn.role === "user" ? "You" : "aes-agent"}</strong><pre>{turn.content}</pre></article>;
}

function ProgressLog({ steps }: { steps: ProgressStep[] }) {
  const failedStep = steps.find((step) => step.status === "error");
  return (
    <section className="progressLog">
      <strong>AES progress</strong>
      <ol>{steps.map((step) => (
        <li className={`progressStep ${step.status}`} key={step.id}><span>{step.label}</span><small>{step.detail}</small></li>
      ))}</ol>
      {failedStep ? <p className="warning">Request stopped: {failedStep.detail}</p> : null}
    </section>
  );
}

function createRunId() {
  // getRandomValues works on plain HTTP where randomUUID may be unavailable.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function titleFromPrompt(prompt: string) {
  const firstLine = prompt.split(/\r?\n/).find((line) => line.trim()) || "AES chat";
  const cleaned = firstLine.trim().replace(/\s+/g, " ");
  return cleaned.length > 56 ? `${cleaned.slice(0, 53)}...` : cleaned;
}
