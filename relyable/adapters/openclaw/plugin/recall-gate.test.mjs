// recall-gate.test.mjs — integration proof for the OpenClaw recall gate.
//
// NOT mocked-only: it registers the gate on a FAITHFUL fake of OpenClaw's plugin
// api (`api.on(name, handler)` — the exact registration the bundled memory-lancedb
// extension uses), fires the captured `before_prompt_build` handler with a recorded
// event, and the handler REALLY spawns the Python gate (relyable.adapters.openclaw
// .cli), which re-derives the notes through relyable.memory -> veriker. So the
// whole TS -> subprocess -> Python -> re-derivation path runs for real; only the
// OpenClaw runtime around `api.on` is substituted, and it is kept identical to the
// upstream contract.
//
// Run: node --test  (from this directory; needs the relyable Python package
// importable, i.e. python -m relyable... resolvable from the product root).

import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { test } from "node:test";

import {
  configFromEnv,
  gateNotes,
  wireRecallGate,
} from "./recall-gate.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
// plugin -> openclaw -> adapters -> relyable(pkg) -> relyable(product root)
const PRODUCT_ROOT = resolve(HERE, "../../../../");
const GRADER = resolve(PRODUCT_ROOT, "relyable/memory/examples/recompute_grader.py");

// recompute-mode notes: the cached result re-derives from items, or it does not.
const GOOD = { note_id: "agg", payload: { items: [3, 1, 2], result: { count: 3, sum: 6, max: 3 } } };
const STALE = { note_id: "stale", payload: { items: [3, 1, 2], result: { count: 3, sum: 99, max: 3 } } };

const CONFIG = {
  graderSrc: GRADER,
  pythonBin: process.env.RELYABLE_OPENCLAW_PYTHON || "python",
  cwd: PRODUCT_ROOT,
};

// A faithful fake of OpenClaw's plugin api: captures handlers by hook name, the
// same `api.on(hookName, handler)` shape memory-lancedb registers against.
function fakeApi() {
  const handlers = {};
  return {
    on(hook, handler) {
      handlers[hook] = handler;
    },
    fire(hook, event) {
      return handlers[hook](event);
    },
    registered(hook) {
      return typeof handlers[hook] === "function";
    },
  };
}

test("registers the before_prompt_build hook", () => {
  const api = fakeApi();
  wireRecallGate(api, CONFIG);
  assert.ok(api.registered("before_prompt_build"));
});

test("gateNotes admits a re-deriving note, refuses a stale one", async () => {
  const gated = await gateNotes([GOOD, STALE], CONFIG);
  assert.deepEqual(gated.admitted, ["agg"]);
  const byId = Object.fromEntries(gated.results.map((r) => [r.note_id, r]));
  assert.equal(byId.agg.verdict, "ADMIT");
  assert.equal(byId.stale.verdict, "REJECT");
});

test("handler injects only the re-deriving note", async () => {
  const api = fakeApi();
  wireRecallGate(api, CONFIG);
  const result = await api.fire("before_prompt_build", {
    prompt: "what is the latest aggregate?",
    messages: [],
    relyableCandidates: [GOOD, STALE],
  });
  assert.ok(result && typeof result.prependContext === "string");
  assert.match(result.prependContext, /<relevant-memories>/);
  assert.match(result.prependContext, /agg/);
  assert.doesNotMatch(result.prependContext, /stale/); // the stale note is dropped
});

test("handler refuses (returns undefined) when no note re-derives", async () => {
  const api = fakeApi();
  wireRecallGate(api, CONFIG);
  const result = await api.fire("before_prompt_build", {
    prompt: "x",
    messages: [],
    relyableCandidates: [STALE],
  });
  assert.equal(result, undefined); // inject nothing rather than a stale note
});

test("handler injects nothing when there are no candidates", async () => {
  const api = fakeApi();
  wireRecallGate(api, CONFIG);
  const result = await api.fire("before_prompt_build", {
    prompt: "hello",
    messages: [],
  });
  assert.equal(result, undefined);
});

test("configFromEnv requires a grader (fail closed)", () => {
  assert.throws(() => configFromEnv({}), /RELYABLE_OPENCLAW_GRADER is required/);
});
