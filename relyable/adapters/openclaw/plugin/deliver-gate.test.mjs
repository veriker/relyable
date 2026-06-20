// deliver-gate.test.mjs — integration proof for the OpenClaw deliver-edge gate.
//
// NOT mocked-only: it registers the gate on a FAITHFUL fake of OpenClaw's plugin
// api (`api.on(name, handler)` — the exact registration shape OpenClaw plugins
// use), fires the captured `message_sending` handler with a recorded event, and the
// handler REALLY spawns the Python gate (relyable.adapters.openclaw.deliver_cli),
// which re-derives the deliverable through relyable -> veriker. So the whole
// TS -> subprocess -> Python -> re-derivation path runs for real; only the OpenClaw
// runtime around `api.on` is substituted, kept identical to the upstream contract.
//
// The grader is the worked recompute grader (the deliver edge re-derives a claim
// the same way memory re-derives a recalled value — the shared relyable primitive),
// so a deliverable whose result reproduces from its inputs is delivered, and one
// whose result no longer matches is suppressed.
//
// Run: node --test  (from this directory; needs the relyable Python package
// importable, i.e. python -m relyable... resolvable from the product root).

import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { test } from "node:test";

import {
  configFromEnv,
  extractDeliverable,
  gateDeliverables,
  wireDeliverGate,
} from "./deliver-gate.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
// plugin -> openclaw -> adapters -> relyable(pkg) -> relyable(product root)
const PRODUCT_ROOT = resolve(HERE, "../../../../");
const GRADER = resolve(PRODUCT_ROOT, "relyable/memory/examples/recompute_grader.py");

// recompute-mode deliverables: the delivered result re-derives from items, or not.
const GOOD = {
  deliverable_id: "brief",
  payload: { items: [3, 1, 2], result: { count: 3, sum: 6, max: 3 } },
};
const FABRICATED = {
  deliverable_id: "fake-brief",
  payload: { items: [3, 1, 2], result: { count: 3, sum: 99, max: 3 } },
};

const CONFIG = {
  graderSrc: GRADER,
  pythonBin: process.env.RELYABLE_OPENCLAW_DELIVER_PYTHON || "python",
  cwd: PRODUCT_ROOT,
};

// A faithful fake of OpenClaw's plugin api: captures handlers by hook name, the
// same `api.on(hookName, handler)` shape OpenClaw plugins register against.
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

test("registers the message_sending hook", () => {
  const api = fakeApi();
  wireDeliverGate(api, CONFIG);
  assert.ok(api.registered("message_sending"));
});

test("extractDeliverable reads relyableDeliverable, ignores bare messages", () => {
  assert.equal(extractDeliverable({ content: "hi" }), null);
  const d = extractDeliverable({ relyableDeliverable: GOOD });
  assert.deepEqual(d, { deliverable_id: "brief", payload: GOOD.payload });
});

test("gateDeliverables admits a re-deriving deliverable, suppresses a fabricated one", async () => {
  const gated = await gateDeliverables([GOOD, FABRICATED], CONFIG);
  assert.deepEqual(gated.admitted, ["brief"]);
  assert.deepEqual(gated.cancelled, ["fake-brief"]);
  const byId = Object.fromEntries(gated.results.map((r) => [r.deliverable_id, r]));
  assert.equal(byId.brief.verdict, "ADMIT");
  assert.equal(byId["fake-brief"].verdict, "REJECT");
});

test("handler delivers (no cancel) when the deliverable re-derives", async () => {
  const api = fakeApi();
  wireDeliverGate(api, CONFIG);
  const result = await api.fire("message_sending", {
    to: "user",
    content: "count=3 sum=6 max=3",
    relyableDeliverable: GOOD,
  });
  assert.equal(result, undefined); // deliver as-is
});

test("handler cancels when the deliverable does not re-derive", async () => {
  const api = fakeApi();
  wireDeliverGate(api, CONFIG);
  const result = await api.fire("message_sending", {
    to: "user",
    content: "count=3 sum=99 max=3",
    relyableDeliverable: FABRICATED,
  });
  assert.ok(result && result.cancel === true);
  assert.match(result.cancelReason, /did not re-derive/);
});

test("handler passes through bare output with no checkable claim", async () => {
  const api = fakeApi();
  wireDeliverGate(api, CONFIG);
  const result = await api.fire("message_sending", { to: "user", content: "hello" });
  assert.equal(result, undefined); // no relyableDeliverable -> nothing to re-derive
});

test("handler fails closed (cancels) when the gate is unavailable", async () => {
  const api = fakeApi();
  wireDeliverGate(api, {
    ...CONFIG,
    pythonBin: "definitely-not-a-real-python-binary-xyz",
  });
  const result = await api.fire("message_sending", {
    to: "user",
    content: "x",
    relyableDeliverable: GOOD,
  });
  assert.ok(result && result.cancel === true);
  assert.match(result.cancelReason, /failed closed/);
});

test("configFromEnv requires a deliver grader (fail closed)", () => {
  assert.throws(
    () => configFromEnv({}),
    /RELYABLE_OPENCLAW_DELIVER_GRADER is required/,
  );
});
