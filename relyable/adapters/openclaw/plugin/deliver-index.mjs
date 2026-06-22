// deliver-index.mjs — the OpenClaw plugin entry for the relyable deliver-edge gate.
//
// The output-edge sibling of index.mjs. This is the only SDK-coupled file for the
// deliver gate: it wraps the SDK-free `wireDeliverGate` from deliver-gate.mjs with
// `definePluginEntry` from OpenClaw's plugin SDK. `kind` is intentionally omitted —
// it is OPTIONAL in the SDK (verified: a register-only entry is
// `definePluginEntry({ id, register() {} })`; `kind` declares a *capability*
// (memory/provider/channel/...), which a hook-only deliver gate does not provide).
// All gate behaviour lives in deliver-gate.mjs, covered by deliver-gate.test.mjs
// without an OpenClaw install.

import { definePluginEntry } from "openclaw/plugin-sdk";

import { configFromEnv, wireDeliverGate } from "./deliver-gate.mjs";

export default definePluginEntry({
  id: "relyable-deliver-gate",
  name: "relyable deliver gate",
  description:
    "Re-derive outbound output at message_sending; suppress (cancel) any " +
    "deliverable that does not re-derive instead of delivering fabricated output.",
  register(api) {
    wireDeliverGate(api, configFromEnv());
  },
});
