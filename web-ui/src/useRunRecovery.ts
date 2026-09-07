import { useEffect, useRef } from "react";
import { aesApiBaseUrl } from "./config";
import { recoverRun, RunRequestError } from "./runClient";
import { applyRunSnapshot, failRunSubmission } from "./runState";
import type { Conversation } from "./types";

export function useRunRecovery(
  userId: string | undefined,
  conversations: Conversation[],
  update: (id: string, transform: (conversation: Conversation) => Conversation) => void,
) {
  const latest = useRef({ conversations, update });
  latest.current = { conversations, update };
  const pendingIds = conversations.flatMap((c) => c.pendingRun ? [c.pendingRun.id] : []).sort().join(",");

  useEffect(() => {
    if (!userId || !pendingIds) return;
    const controller = new AbortController();
    let timer: number | undefined;
    async function poll() {
      const pending = latest.current.conversations.filter((c) => c.pendingRun);
      await Promise.all(pending.map(async (conversation) => {
        const run = conversation.pendingRun!;
        try {
          const snapshot = await recoverRun(aesApiBaseUrl, run, controller.signal);
          if (!controller.signal.aborted) {
            latest.current.update(conversation.id, (current) => applyRunSnapshot(current, snapshot));
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          const rejected = error instanceof RunRequestError && [400, 409, 413, 422].includes(error.status);
          const message = (error as Error).message;
          latest.current.update(conversation.id, (current) => {
            if (current.pendingRun?.id !== run.id) return current;
            if (rejected) return failRunSubmission(current, run.id, message);
            return { ...current, runConnectionError: error instanceof RunRequestError && error.status === 401
              ? "Your login expired. Sign in again to recover this run."
              : `Reconnecting to AES. Your request will not be duplicated. ${message}` };
          });
        }
      }));
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), 2000);
    }
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [userId, pendingIds]);
}
