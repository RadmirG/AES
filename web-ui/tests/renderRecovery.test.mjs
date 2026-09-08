import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import React from "react";
import { renderToString } from "react-dom/server";
import { act, create } from "react-test-renderer";
import { loadComponent } from "./loadComponent.mjs";
import { isGeometrySpec, isPdeSpec } from "../src/viewContracts.ts";
import { loadStoredConversations, saveStoredConversations } from "../src/storage.ts";
import { applyRunSnapshot } from "../src/runState.ts";

const { GeometryExplorer } = loadComponent("src/components/GeometryExplorer.tsx", {
  "./GeometryVtkViewer": { GeometryVtkViewer: () => React.createElement("span", null, "VTK geometry") },
  "./VtkResultViewer": { VtkResultViewer: () => React.createElement("span", null, "VTK result") },
});
const { EquationSummary } = loadComponent("src/components/EquationSummary.tsx");
const { PanelErrorBoundary } = loadComponent("src/components/PanelErrorBoundary.tsx");
const geometryView = (value) => React.createElement(GeometryExplorer, {
  isRunning: false, resultGeometry: value, onGeometryContextChange: () => {}, solutionManifest: null,
});

test("every shipped geometry satisfies the browser view contract", () => {
  const index = JSON.parse(readFileSync("../examples/geometries/index.json", "utf8"));
  for (const entry of index) {
    const geometry = JSON.parse(readFileSync(`../examples/geometries/${entry.spec}`, "utf8"));
    assert.equal(isGeometrySpec(geometry), true, entry.id);
  }
});

test("empty or malformed geometry does not crash the result viewer", () => {
  for (const geometry of [null, {}, [], { regions: null }, { regions: [null] }, { source: {} }]) {
    assert.equal(isGeometrySpec(geometry), false);
    const html = renderToString(geometryView(geometry));
    assert.ok(html.includes("Scientific viewport"));
    if (geometry !== null) assert.ok(html.includes("No usable geometry"));
  }
});

test("incomplete PDE data shows a message instead of calling missing equation or time fields", () => {
  for (const spec of [{}, { equation: null }, { equation: { family: "custom" }, time: {} }]) {
    assert.equal(isPdeSpec(spec), false);
    const html = renderToString(React.createElement(EquationSummary, {
      aesResult: { pde_spec: spec, agent_status: "needs_clarification" }, status: "stored",
    }));
    assert.ok(html.includes("No usable formulation"));
    assert.ok(!html.includes("Solved formulation"));
  }
});

test("valid stationary and transient formulation data still render their equations", () => {
  for (const family of ["stationary_diffusion", "transient_diffusion"]) {
    const spec = {
      spatial_dimension: 3,
      equation: { family, unknown: "u", strong_form: "heat equation",
        diffusion: { kind: "constant", value: "1" }, source: { kind: "constant", value: "0" } },
      boundary_conditions: [{ name: "fixed", type: "dirichlet", region: "base_bottom", value: { kind: "constant", value: "100" } }],
      initial_condition: family === "transient_diffusion" ? { value: { kind: "constant", value: "20" } } : null,
      time: family === "transient_diffusion" ? { t0: 0, t_end: 1, dt: 0.01, scheme: "backward_euler" } : null,
    };
    assert.equal(isPdeSpec(spec), true);
    const html = renderToString(React.createElement(EquationSummary, {
      aesResult: { pde_spec: spec, agent_status: "ok" }, status: "completed",
    }));
    assert.ok(html.includes("Solved formulation"));
    assert.ok(html.includes("katex"));
    assert.ok(!html.includes("No usable formulation"));
  }
});

test("old saved empty-geometry results survive refresh and durable-run recovery without deleting chat", () => {
  const data = new Map();
  globalThis.window = { localStorage: { getItem: (key) => data.get(key), setItem: (key, value) => data.set(key, value) } };
  const chat = { id: "chat", title: "Projectile", createdAt: "2026-09-08", updatedAt: "2026-09-08",
    turns: [{ role: "user", content: "Projectile request" }], pendingRun: { id: "run", progressTurnId: "progress" } };
  const recovered = applyRunSnapshot(chat, { id: "run", status: "completed", updated_at: chat.updatedAt, progress: [],
    response: { choices: [{ message: { content: "Clarification" } }], aes_result: { geometry_spec: {}, agent_status: "needs_clarification" } } });
  saveStoredConversations("engineer", [recovered], true);
  const [restored] = loadStoredConversations("engineer");
  assert.equal(restored.turns[0].content, "Projectile request");
  assert.equal(restored.turns[1].content, "Clarification");
  assert.ok(renderToString(geometryView(restored.result.aesResult.geometry_spec)).includes("No usable geometry"));
});

test("a failing results panel leaves chat mounted, supports retry, and resets for another conversation", (t) => {
  t.mock.method(console, "error", () => {});
  let broken = true;
  function Viewer() { if (broken) throw new Error("test render failure"); return React.createElement("p", null, "Result restored"); }
  const tree = (id) => React.createElement(React.Fragment, null,
    React.createElement("button", { id: "chat" }, "Chat remains usable"),
    React.createElement(PanelErrorBoundary, { name: "Results", resetKeys: [id] }, React.createElement(Viewer)));
  let renderer;
  act(() => { renderer = create(tree("chat-1")); });
  assert.equal(renderer.root.findByProps({ id: "chat" }).children[0], "Chat remains usable");
  assert.ok(renderer.root.findByProps({ role: "alert" }));
  broken = false;
  act(() => renderer.root.findAllByType("button").find((button) => button.children[0] === "Retry this view").props.onClick());
  assert.ok(JSON.stringify(renderer.toJSON()).includes("Result restored"));
  broken = true;
  act(() => renderer.update(tree("chat-1")));
  assert.ok(renderer.root.findByProps({ role: "alert" }));
  broken = false;
  act(() => renderer.update(tree("chat-2")));
  assert.ok(JSON.stringify(renderer.toJSON()).includes("Result restored"));
  act(() => renderer.unmount());
});

test("proxy re-resolves Docker services and preserves full API and artifact request URIs", () => {
  const config = readFileSync("nginx.conf", "utf8");
  assert.match(config, /resolver 127\.0\.0\.11 valid=5s/);
  assert.equal((config.match(/proxy_pass \$aes_backend\$request_uri;/g) || []).length, 3);
});
