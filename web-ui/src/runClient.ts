import type { BackendRun, PendingRun } from "./types";

export class RunRequestError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function recoverRun(baseUrl: string, pending: PendingRun, signal: AbortSignal): Promise<BackendRun> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timeout = setTimeout(abort, 30_000);
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  try {
    return await requestSnapshot(baseUrl, pending, controller.signal);
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", abort);
  }
}

async function requestSnapshot(baseUrl: string, pending: PendingRun, signal: AbortSignal): Promise<BackendRun> {
  const options = { credentials: "include" as const, cache: "no-store" as const, signal };
  let response = await fetch(`${baseUrl}/api/runs/${encodeURIComponent(pending.id)}`, options);
  if (response.status === 404) {
    // A refresh can happen before submission or before its acknowledgement.
    // The saved ID makes either retry safe even if another tab submits it too.
    response = await fetch(`${baseUrl}/api/runs`, {
      ...options, method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pending.request),
    });
  }
  if (!response.ok) {
    let message = `AES connection returned HTTP ${response.status}.`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch { /* A proxy may return a non-JSON response. */ }
    throw new RunRequestError(message, response.status);
  }
  const run = await response.json() as BackendRun;
  if (run.id !== pending.id || run.conversation_id !== pending.request.conversation_id) {
    throw new Error("AES returned a different run; waiting to reconnect to the saved request.");
  }
  return run;
}
