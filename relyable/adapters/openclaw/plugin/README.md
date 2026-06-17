# relyable-recall-gate — OpenClaw plugin

Re-derive recalled memory at OpenClaw's `before_prompt_build` hook and inject only
notes that **still re-derive** — refuse stale/poisoned recall instead of trusting
it because it was remembered. Answers the staleness axis of
[`openclaw/openclaw#59130`](https://github.com/openclaw/openclaw/issues/59130).

This is a thin shim with no trust logic: the TS plugin spawns the Python gate
(`relyable.adapters.openclaw.cli`), which loops `relyable.memory.admit_note`. The
grader (and, for sealed-reference mode, the reference) is **your** trust root —
host config, never shipped here.

## Layout

- `index.mjs` — the SDK-coupled plugin entry (`definePluginEntry` from
  `openclaw/plugin-sdk`); wraps `wireRecallGate`.
- `recall-gate.mjs` — the SDK-free gate logic (`wireRecallGate`, `gateNotes`,
  `configFromEnv`); registers `before_prompt_build`, spawns the Python gate.
- `recall-gate.test.mjs` — integration proof (`node --test`): registers on a
  faithful fake api, fires the hook, really spawns the Python gate.

## Config (environment)

| Env var | Meaning |
|---|---|
| `RELYABLE_OPENCLAW_GRADER` | **required** — path to your trusted recall grader |
| `RELYABLE_OPENCLAW_REFERENCE` | sealed first-party reference dir (sealed-reference mode; omit for recompute mode) |
| `RELYABLE_OPENCLAW_REFERENCE_ANCHOR` | pin the reference digest; refuse on mismatch |
| `RELYABLE_OPENCLAW_NO_RUN` | truthy ⇒ `permit_execution=False` (refuse all; kill-switch) |
| `RELYABLE_OPENCLAW_PYTHON` | python interpreter (default `python`) |

## How it gates

The handler collects the recalled notes it would inject (`{note_id, payload}`),
runs each through the gate, and returns `{ prependContext }` of only the
re-deriving notes — or `undefined` (inject nothing) when none survive. See
`../DISCOVERY.md` for the exact hook, the in-process/unsandboxed Node boundary, the
structured-note scope, and why the promote/"Dreaming" edge is out of scope (no
plugin hook).

## Test

```sh
node --test          # needs the relyable Python package importable
```
