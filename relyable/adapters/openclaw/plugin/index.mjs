// index.mjs — the OpenClaw plugin entry for the relyable recall gate.
//
// This is the only SDK-coupled file: it wraps the SDK-free `wireRecallGate` from
// recall-gate.mjs with `definePluginEntry` from OpenClaw's plugin SDK. The bundled
// `memory-lancedb` extension uses the exact same shape:
//
//     import { definePluginEntry, type OpenClawPluginApi } from "./api.js";
//     export default definePluginEntry({ id, name, description, kind, register });
//
// (verified in extensions/memory-lancedb/index.ts — see DISCOVERY.md). We import
// `definePluginEntry` from the published SDK barrel `openclaw/plugin-sdk` rather
// than a bundled `./api.js`. All gate behaviour lives in recall-gate.mjs, which is
// covered by recall-gate.test.mjs without needing an OpenClaw install.

import { definePluginEntry } from "openclaw/plugin-sdk";

import { configFromEnv, wireRecallGate } from "./recall-gate.mjs";

export default definePluginEntry({
  id: "relyable-recall-gate",
  name: "relyable recall gate",
  description:
    "Re-derive recalled memory at before_prompt_build; inject only notes that " +
    "still re-derive (refuse stale/poisoned recall instead of trusting it).",
  kind: "memory",
  register(api) {
    wireRecallGate(api, configFromEnv());
  },
});
