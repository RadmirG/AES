import assert from "node:assert/strict";
import { test } from "node:test";
import { applyRunSnapshot } from "../src/runState.ts";
import { recoverRun } from "../src/runClient.ts";
import { loadStoredConversations, saveStoredConversations } from "../src/storage.ts";

const id = "b758c346-77b0-46d2-902b-ddbd947cbd19";
function conversation() {
  return {
    id: "chat-1", title: "Laplace", createdAt: "2026-09-08", updatedAt: "2026-09-08",
    turns: [{ role: "user", content: "Solve Laplace" }, { role: "progress", content: id, progressSteps: [{ id: "start", status: "active" }] }],
    pendingRun: { id, progressTurnId: id, geometryContext: { name: "L shape" }, request: {
      run_id: id, conversation_id: "chat-1", backend_model: "gemma4:31b", messages: [{ role: "user", content: "Solve Laplace" }],
    } },
  };
}
function snapshot(status = "running") {
  return { id, conversation_id: "chat-1", status, updated_at: "2026-09-08T12:00:00Z", progress: [{
    id: "interpret_typed_specs", label: "Interpret typed specs", detail: "Running", status: "active",
  }] };
}
function localStorageMock() {
  const data = new Map();
  globalThis.window = { localStorage: {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value),
  } };
}

test("refresh restores a pending run and keeps its progress active", () => {
  localStorageMock();
  saveStoredConversations("engineer", [conversation()], true);
  const [restored] = loadStoredConversations("engineer");
  assert.equal(restored.pendingRun.id, id);
  assert.equal(restored.turns[1].progressSteps[0].status, "active");
  assert.equal(applyRunSnapshot(restored, snapshot()).turns[1].progressSteps[0].label, "Interpret typed specs");
});

test("recovered result restores geometry and artifacts and appends the answer once", () => {
  const run = { ...snapshot("completed"), response: { choices: [{ message: { content: "Solved" } }], aes_result: { agent_status: "ok" } } };
  const recovered = applyRunSnapshot(conversation(), run);
  assert.equal(recovered.pendingRun, undefined);
  assert.equal(recovered.result.geometryContext.name, "L shape");
  assert.equal(recovered.result.aesResult.agent_status, "ok");
  assert.equal(applyRunSnapshot(recovered, run).turns.filter((turn) => turn.role === "assistant").length, 1);
});

test("different run cannot overwrite current conversation", () => {
  const current = conversation();
  assert.equal(applyRunSnapshot(current, { ...snapshot(), id: "different" }), current);
});

test("worker interruption clears pending state and leaves a recorded error", () => {
  const recovered = applyRunSnapshot(conversation(), { ...snapshot("interrupted"), error: "Worker stopped" });
  assert.equal(recovered.pendingRun, undefined);
  assert.ok(recovered.turns[1].progressSteps.some((step) => step.status === "error"));
  assert.equal(recovered.turns.some((turn) => turn.role === "assistant"), false);
});

test("refresh after accepted submission only fetches the existing result", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (...args) => { calls.push(args); return Response.json(snapshot()); });
  const recovered = await recoverRun("", conversation().pendingRun, new AbortController().signal);
  assert.equal(recovered.id, id);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], `/api/runs/${id}`);
});

test("lost acknowledgement retries the same persisted request ID", async (t) => {
  const calls = [];
  let accepted = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push([url, options]);
    if (options.method === "POST") {
      accepted = true;
      throw new TypeError("Connection lost after server accepted request");
    }
    return accepted ? Response.json(snapshot()) : new Response("", { status: 404 });
  });
  const pending = conversation().pendingRun;
  await assert.rejects(recoverRun("", pending, new AbortController().signal));
  assert.equal(JSON.parse(calls[1][1].body).run_id, id);
  assert.equal((await recoverRun("", pending, new AbortController().signal)).status, "running");
  assert.equal(calls.filter(([, options]) => options.method === "POST").length, 1);
});

test("local storage failure prevents accepting a new pending request", () => {
  localStorageMock();
  window.localStorage.setItem = () => { throw new Error("Quota exceeded"); };
  assert.throws(() => saveStoredConversations("engineer", [conversation()], true), /could not save the request ID/);
});

test("expired authentication never resubmits the solve", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({ detail: "Authentication required" }, { status: 401 }));
  await assert.rejects(recoverRun("", conversation().pendingRun, new AbortController().signal), /Authentication required/);
  assert.equal(fetch.mock.callCount(), 1);
});
