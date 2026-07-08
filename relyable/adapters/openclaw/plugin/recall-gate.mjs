// recall-gate.mjs — the OpenClaw recall gate logic (SDK-free, so it is testable
// without an OpenClaw install).
//
// `wireRecallGate(api, config)` registers the real `before_prompt_build` hook on
// the passed OpenClaw plugin api; `index.mjs` wraps it with `definePluginEntry`
// for production, and the Node test calls it with a faithful fake api. The handler
// collects the recalled notes it would inject, spawns the Python gate
// (`relyable-openclaw-recall`), and returns `{ prependContext }` of only the
// re-deriving notes — or `undefined` to inject nothing when none survive, the same
// admit/refuse contract the bundled `memory-lancedb` extension uses on this hook.
//
// The gate adds no trust logic: the Python side loops relyable.memory.admit_note.

import { spawn } from "node:child_process";

const MEMORY_OPEN = "<relevant-memories>";
const MEMORY_CLOSE = "</relevant-memories>";
const TRUTHY = new Set(["1", "true", "yes", "on"]);

// Build the JS gate config from the environment OpenClaw sets for the plugin. The
// grader (and, for sealed-reference mode, the reference) is the consumer's trust
// root — host config, never shipped. Throws if the grader is unset (fail closed).
export function configFromEnv(env = process.env) {
  const graderSrc = env.RELYABLE_OPENCLAW_GRADER;
  if (!graderSrc) {
    throw new Error(
      "RELYABLE_OPENCLAW_GRADER is required: the consumer's trusted recall grader " +
        "is the gate's trust root and has no default.",
    );
  }
  return {
    graderSrc,
    referencePath: env.RELYABLE_OPENCLAW_REFERENCE || undefined,
    referenceAnchor: env.RELYABLE_OPENCLAW_REFERENCE_ANCHOR || undefined,
    packFilename: env.RELYABLE_OPENCLAW_PACK_FILENAME || undefined,
    noRun: TRUTHY.has((env.RELYABLE_OPENCLAW_NO_RUN || "").toLowerCase()),
    pythonBin: env.RELYABLE_OPENCLAW_PYTHON || undefined,
  };
}

// Default: read structured candidate notes from `event.relyableCandidates`
// ([{ note_id, payload }]). In a real deploy you instead pass the post-recall
// results (memory-lancedb's `cleanResults`) here — see DISCOVERY.md. Returns [].
export function extractCandidates(event) {
  const c = event && event.relyableCandidates;
  return Array.isArray(c) ? c : [];
}

// Render the admitted notes into the <relevant-memories> block OpenClaw injects.
export function formatAdmittedContext(admittedNotes) {
  const body = admittedNotes
    .map((n) => `- ${n.note_id}: ${JSON.stringify(n.payload)}`)
    .join("\n");
  return `${MEMORY_OPEN}\n${body}\n${MEMORY_CLOSE}`;
}

// Spawn the Python batch gate. Returns the parsed { results, admitted } object.
// `config` -> environment the CLI reads (RecallGateConfig.from_env). Rejects on a
// non-JSON / spawn failure so the caller fails closed (injects nothing).
export function gateNotes(candidates, config) {
  const env = { ...process.env };
  env.RELYABLE_OPENCLAW_GRADER = config.graderSrc;
  if (config.referencePath) env.RELYABLE_OPENCLAW_REFERENCE = config.referencePath;
  if (config.referenceAnchor)
    env.RELYABLE_OPENCLAW_REFERENCE_ANCHOR = config.referenceAnchor;
  if (config.packFilename)
    env.RELYABLE_OPENCLAW_PACK_FILENAME = config.packFilename;
  if (config.noRun) env.RELYABLE_OPENCLAW_NO_RUN = "1";

  const python = config.pythonBin || "python";
  const args = config.cliArgs || ["-m", "relyable.adapters.openclaw.cli"];

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
          new Error(`recall-gate: bad gate output: ${e.message}; stderr: ${err}`),
        );
      }
    });
    proc.stdin.end(JSON.stringify({ candidates }));
  });
}

// Register the recall gate on OpenClaw's before_prompt_build hook.
export function wireRecallGate(api, config) {
  api.on("before_prompt_build", async (event) => {
    const candidates = extractCandidates(event);
    if (candidates.length === 0) return undefined; // nothing to gate

    let gated;
    try {
      gated = await gateNotes(candidates, config);
    } catch {
      return undefined; // fail closed: gate unavailable -> inject nothing
    }

    const admittedIds = new Set(gated.admitted || []);
    const admittedNotes = candidates.filter((n) => admittedIds.has(n.note_id));
    if (admittedNotes.length === 0) return undefined; // refuse: none re-derived

    return { prependContext: formatAdmittedContext(admittedNotes) };
  });
}
