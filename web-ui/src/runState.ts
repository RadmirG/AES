import type { BackendRun, Conversation, ProgressStep } from "./types";

export function applyRunSnapshot(conversation: Conversation, run: BackendRun): Conversation {
  const pending = conversation.pendingRun;
  if (!pending || pending.id !== run.id) return conversation;
  const terminal = ["completed", "failed", "interrupted"].includes(run.status);
  const steps: ProgressStep[] = run.progress.length ? run.progress : [{
    id: "accepted", label: "Request accepted by AES",
    detail: run.status === "queued" ? "Waiting for an execution worker." : "AES execution is starting.",
    status: "active",
  }];
  const finalSteps: ProgressStep[] = terminal
    ? [...steps.map((step): ProgressStep => ({
      ...step,
      status: step.status === "active" ? (run.response ? "done" : "error") : step.status,
      detail: step.status === "active" && !run.response ? (run.error || "Execution stopped.") : step.detail,
    })), {
      id: "result", label: run.response ? "Final response saved" : "Execution interrupted or failed",
      detail: run.error || "The response and artifact links are saved on the server.",
      status: run.response ? "done" : "error",
    }]
    : steps;
  let turns = conversation.turns.map((turn) =>
    turn.role === "progress" && turn.content === pending.progressTurnId
      ? { ...turn, progressSteps: finalSteps } : turn,
  );
  const assistantText = run.response?.choices?.[0]?.message?.content || "";
  if (terminal && run.response && !turns.some((turn) => turn.role === "assistant" && turn.runId === run.id)) {
    turns = [...turns, { role: "assistant", content: assistantText, runId: run.id, createdAt: run.updated_at }];
  }
  return {
    ...conversation,
    turns,
    updatedAt: run.updated_at,
    pendingRun: terminal ? undefined : pending,
    runConnectionError: "",
    result: terminal && run.response ? {
      assistantText, aesResult: run.response.aes_result, geometryContext: pending.geometryContext,
    } : conversation.result,
  };
}

export function failRunSubmission(conversation: Conversation, runId: string, message: string): Conversation {
  const pending = conversation.pendingRun;
  if (!pending || pending.id !== runId) return conversation;
  return {
    ...conversation,
    pendingRun: undefined,
    runConnectionError: message,
    turns: conversation.turns.map((turn) => turn.content === pending.progressTurnId ? {
      ...turn, progressSteps: [{ id: "rejected", label: "Request was not accepted", detail: message, status: "error" }],
    } : turn),
  };
}
