// deliver-gate.mjs — the OpenClaw deliver-edge gate logic (SDK-free, so it is
// testable without an OpenClaw install).
//
// `wireDeliverGate(api, config)` registers OpenClaw's `message_sending` hook — the
// post-generation, pre-send chokepoint that all delivery surfaces (interactive,
// cron `announce`, subagent) funnel through and that supports `{cancel: true}`
// suppression (verified seam — see ../../../DELIVER_EDGE_DISCOVERY.md). The handler
// re-derives the outbound deliverable by spawning the Python gate
// (`relyable.adapters.openclaw.deliver_cli`) and CANCELS the send if it does not
// re-derive — the fail-closed posture openclaw/openclaw#49876 asks for. `index`-
// style wrapping (definePluginEntry) lives in deliver-index.mjs; the Node test
// calls this with a faithful fake api.
//
// The gate adds no trust logic: the Python side re-derives via relyable.

import { spawn } from "node:child_process";

const TRUTHY = new Set(["1", "true", "yes", "on"]);

// Build the JS gate config from the environment OpenClaw sets for the plugin. The
// grader (and, for sealed-reference mode, the reference) is the consumer's trust
// root — host config, never shipped. Throws if the grader is unset (fail closed).
// Separate env namespace (RELYABLE_OPENCLAW_DELIVER_*) from the recall gate so one
// install can run both with different graders.
export function configFromEnv(env = process.env) {
  const graderSrc = env.RELYABLE_OPENCLAW_DELIVER_GRADER;
  if (!graderSrc) {
    throw new Error(
      "RELYABLE_OPENCLAW_DELIVER_GRADER is required: the consumer's trusted deliver " +
        "grader is the gate's trust root and has no default.",
    );
  }
  return {
    graderSrc,
    referencePath: env.RELYABLE_OPENCLAW_DELIVER_REFERENCE || undefined,
    referenceAnchor: env.RELYABLE_OPENCLAW_DELIVER_REFERENCE_ANCHOR || undefined,
    packFilename: env.RELYABLE_OPENCLAW_DELIVER_PACK_FILENAME || undefined,
    noRun: TRUTHY.has((env.RELYABLE_OPENCLAW_DELIVER_NO_RUN || "").toLowerCase()),
    pythonBin: env.RELYABLE_OPENCLAW_DELIVER_PYTHON || undefined,
  };
}

// Extract the structured deliverable to re-derive from a message_sending event.
// `message_sending` carries only { to, content, metadata } (see the discovery
// note's text-only caveat): a free-text output with no checkable claim has nothing
// to re-derive. The integrator attaches the claim + its inputs as
// `event.relyableDeliverable` ({ deliverable_id, payload }) — analogous to how the
// recall gate reads `event.relyableCandidates`. Returns null when none is present.
export function extractDeliverable(event) {
  const d = event && event.relyableDeliverable;
  if (!d || typeof d !== "object" || !("payload" in d)) return null;
  return { deliverable_id: d.deliverable_id || "outbound", payload: d.payload };
}

// Spawn the Python batch gate. Returns the parsed { results, admitted, cancelled }
// object. `config` -> environment the CLI reads (DeliverGateConfig.from_env).
// Rejects on a non-JSON / spawn failure so the caller fails closed (cancels send).
export function gateDeliverables(candidates, config) {
  const env = { ...process.env };
  env.RELYABLE_OPENCLAW_DELIVER_GRADER = config.graderSrc;
  if (config.referencePath)
    env.RELYABLE_OPENCLAW_DELIVER_REFERENCE = config.referencePath;
  if (config.referenceAnchor)
    env.RELYABLE_OPENCLAW_DELIVER_REFERENCE_ANCHOR = config.referenceAnchor;
  if (config.packFilename)
    env.RELYABLE_OPENCLAW_DELIVER_PACK_FILENAME = config.packFilename;
  if (config.noRun) env.RELYABLE_OPENCLAW_DELIVER_NO_RUN = "1";

  const python = config.pythonBin || "python";
  const args = config.cliArgs || ["-m", "relyable.adapters.openclaw.deliver_cli"];

  return new Promise((resolve, reject) => {
    const proc = spawn(python, args, { env, cwd: config.cwd });
    let out = "";
    let err = "";
    proc.stdout.on("data", (d) => (out += d));
    proc.stderr.on("data", (d) => (err += d));
    proc.on("error", reject);
    proc.on("close", () => {
      // Exit code is admit/refuse signalling, not failure — parse stdout either
      // way; only a missing/garbled payload is a hard error (fail closed).
      try {
        resolve(JSON.parse(out));
      } catch (e) {
        reject(
          new Error(`deliver-gate: bad gate output: ${e.message}; stderr: ${err}`),
        );
      }
    });
    proc.stdin.end(JSON.stringify({ candidates }));
  });
}

// Register the deliver gate on OpenClaw's message_sending hook. Returns a result
// per the hook contract: `undefined` (no change) to deliver as-is, or
// `{ cancel: true, cancelReason }` to suppress the send.
export function wireDeliverGate(api, config) {
  api.on("message_sending", async (event) => {
    const deliverable = extractDeliverable(event);
    // No checkable claim attached -> nothing to re-derive; deliver as-is. This is
    // the documented text-only scope boundary, not a fail-open: gating a structured
    // claim is opt-in via event.relyableDeliverable.
    if (!deliverable) return undefined;

    let gated;
    try {
      gated = await gateDeliverables([deliverable], config);
    } catch {
      // Gate unavailable -> fail closed: suppress rather than deliver unverified.
      return {
        cancel: true,
        cancelReason: "relyable: deliver gate unavailable (failed closed)",
      };
    }

    const cancelled = new Set(gated.cancelled || []);
    if (!cancelled.has(deliverable.deliverable_id)) return undefined; // re-derived

    const r = (gated.results || []).find(
      (x) => x.deliverable_id === deliverable.deliverable_id,
    );
    const code = (r && r.reason_code) || "NOT_REDERIVED";
    return {
      cancel: true,
      cancelReason: `relyable: output did not re-derive [${code}]`,
    };
  });
}
