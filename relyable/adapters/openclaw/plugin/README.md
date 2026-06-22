# relyable-openclaw-gates — OpenClaw plugins

Two plugin entries that **admit only what re-derives** — one on each edge of an
OpenClaw session. Both are thin shims with no trust logic: the TS handler spawns a
Python gate that re-derives through relyable → veriker. The grader (and, for
sealed-reference mode, the reference) is **your** trust root — host config, never
shipped here.

| Entry | Hook | What it gates | Upstream ask |
|---|---|---|---|
| `index.mjs` (recall) | `before_prompt_build` | injects only recalled notes that still re-derive (refuse stale/poisoned recall) | [`#59130`](https://github.com/openclaw/openclaw/issues/59130) |
| `deliver-index.mjs` (deliver) | `message_sending` | suppresses outbound output that does not re-derive (refuse fabricated "I did X") | [`#49876`](https://github.com/openclaw/openclaw/issues/49876) |

Register each as its own plugin pointing at its entry module. The two use separate
env namespaces (`RELYABLE_OPENCLAW_*` vs `RELYABLE_OPENCLAW_DELIVER_*`), so one
install can run both with different graders.

## Layout

Recall (input edge):
- `index.mjs` — SDK-coupled entry (`definePluginEntry`); wraps `wireRecallGate`.
- `recall-gate.mjs` — SDK-free logic; registers `before_prompt_build`, spawns
  `relyable.adapters.openclaw.cli`.
- `recall-gate.test.mjs` — integration proof (`node --test`).

Deliver (output edge):
- `deliver-index.mjs` — SDK-coupled entry; wraps `wireDeliverGate` (no `kind` — a
  hook-only gate declares no capability).
- `deliver-gate.mjs` — SDK-free logic; registers `message_sending`, spawns
  `relyable.adapters.openclaw.deliver_cli`.
- `deliver-gate.test.mjs` — integration proof (`node --test`).

## Config (environment)

Recall gate:

| Env var | Meaning |
|---|---|
| `RELYABLE_OPENCLAW_GRADER` | **required** — path to your trusted recall grader |
| `RELYABLE_OPENCLAW_REFERENCE` | sealed first-party reference dir (sealed-reference mode; omit for recompute mode) |
| `RELYABLE_OPENCLAW_REFERENCE_ANCHOR` | pin the reference digest; refuse on mismatch |
| `RELYABLE_OPENCLAW_NO_RUN` | truthy ⇒ `permit_execution=False` (refuse all; kill-switch) |
| `RELYABLE_OPENCLAW_PYTHON` | python interpreter (default `python`) |

Deliver gate — same shape, `RELYABLE_OPENCLAW_DELIVER_` prefix
(`..._DELIVER_GRADER` **required**, `..._DELIVER_REFERENCE`,
`..._DELIVER_REFERENCE_ANCHOR`, `..._DELIVER_NO_RUN`, `..._DELIVER_PYTHON`).

## How they gate

- **Recall**: the handler collects the recalled notes it would inject
  (`{note_id, payload}`), runs each through the gate, and returns `{ prependContext }`
  of only the re-deriving notes — or `undefined` (inject nothing) when none survive.
  See `../DISCOVERY.md`.
- **Deliver**: `message_sending` carries only `{ to, content, metadata }`, so the
  integrator attaches the structured claim + its inputs as
  `event.relyableDeliverable` (`{ deliverable_id, payload }`). The handler re-derives
  it and returns `undefined` to deliver as-is, or `{ cancel: true, cancelReason }` to
  suppress. Bare output with no `relyableDeliverable` is passed through (the text-only
  scope boundary); gate-unavailable fails **closed** (cancels). See
  `../../../DELIVER_EDGE_DISCOVERY.md` for the verified seam + caveats (no reliable
  `runId` on the outbound path — use `sessionKey`; ledger-aware gating wants the
  `before_agent_finalize` edge instead).

## Test

```sh
node --test          # needs the relyable Python package importable
```
