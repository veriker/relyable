# OpenClaw memory adapter — extension-surface discovery

*Captured 2026-06-15 before writing adapter code. Concrete claims are pinned to
primary sources verified this session (GitHub raw + live `gh`). The plugin entry
shape and the `before_prompt_build` event fields were read from the real
`extensions/memory-lancedb/index.ts`; nothing here is invented.*

> **Correction (2026-06-16, verified at HEAD `2f222cd`, OpenClaw `2026.6.8`):** the
> bundled recall extension was **renamed/restructured** since the 2026-06-15 capture
> — there is no longer a `memory-lancedb` extension (`ls extensions/` shows
> `active-memory`). The `before_prompt_build` recall registration now lives at
> **`extensions/active-memory/index.ts:3563-3565`**, with the *same*
> `api.on("before_prompt_build", …)` admit/refuse contract. The verbatim block below
> is the 2026-06-15 `memory-lancedb` capture, kept as-is (it was accurate then); only
> the file path moved, not the contract. Issue #59130's title still says
> "memory-lancedb" because it predates the rename. The companion output-edge seam is
> in `../../../DELIVER_EDGE_DISCOVERY.md` (the `message_sending` deliver gate).*

## Verdict

**DETERMINABLE — a real, stable RECALL hook exists.** Wire the gate at
`before_prompt_build`. The **promote / "Dreaming"** edge has **no plugin hook** (CLI
+ cron only) — gating it would require forking core, so it is out of scope for this
adapter (documented below).

## The recall hook: `before_prompt_build` (verified from real source)

OpenClaw (`github.com/openclaw/openclaw`, TypeScript) plugins register typed
lifecycle hooks via `api.on(hookName, handler)`. The bundled `memory-lancedb`
extension registers exactly this hook for auto-recall. Verified verbatim from
`extensions/memory-lancedb/index.ts` (raw.githubusercontent.com, `main`,
fetched this session):

```ts
import { definePluginEntry, type OpenClawPluginApi } from "./api.js";

export default definePluginEntry({
  id: "memory-lancedb",
  name: "Memory (LanceDB)",
  description: "LanceDB-backed long-term memory with auto-recall/capture",
  kind: "memory" as const,
  configSchema: memoryConfigSchema,
  register(api: OpenClawPluginApi) {
    api.on("before_prompt_build", async (event) => {
      const currentCfg = resolveCurrentHookConfig();
      if (!currentCfg.autoRecall) { return undefined; }
      const recallQuery = normalizeRecallQuery(
        extractLatestUserText(Array.isArray(event.messages) ? event.messages : [])
          ?? event.prompt,
        currentCfg.recallMaxChars);
      // ... db.search(...) -> cleanResults ...
      return { prependContext: context };   // context = <relevant-memories>...</...>
    });
  },
});
```

Load-bearing facts for the adapter:
- **Admit** by returning `{ prependContext: <string> }`; **refuse** by returning
  `undefined`. Our plugin uses exactly this contract: inject only re-deriving notes,
  return `undefined` when none survive.
- The hook reads user text from `event.messages` (falling back to `event.prompt`).
- The plugin entry is `export default definePluginEntry({ id, name, description,
  kind, register })`. The extension imports `definePluginEntry` / `OpenClawPluginApi`
  from a local `./api.js` barrel; a standalone plugin imports them from the published
  SDK `openclaw/plugin-sdk` (our `index.mjs` does this).
- memory-lancedb also registers `agent_end` (auto-capture; **30 s** hook timeout per
  `docs/plugins/hooks.md`) and `session_end`. Our gate uses only `before_prompt_build`.

## Where the gate goes (and the honest scope)

memory-lancedb computes recall results *inside* the handler (`db.search` →
`cleanResults`) then formats them with `formatRelevantMemoriesContext`. The natural
insertion is **between `cleanResults` and the format call**: gate the recalled
results, inject only those that re-derive. relyable re-derives **structured**
notes (`{note_id, payload}` — a cached computation, recompute mode; or a fact
checkable against a sealed reference, sealed-reference mode). Free-text semantic
memory with no checkable claim is out of scope for this gate (relyable covers the
correctness/staleness axis of issue #59130, not arbitrary prose).

Our standalone plugin (`plugin/`) demonstrates the same gate on the same hook via a
structured-note channel (`event.relyableCandidates`); a production integration may
instead splice `gateNotes(...)` into memory-lancedb's handler over its
`cleanResults`. Either way the hook, the admit/refuse return contract, and the
Python re-derivation are identical — and exercised for real by `recall-gate.test.mjs`.

## Language / process boundary (Python gate from a TS plugin)

- OpenClaw plugins **run in-process Node, not sandboxed** (`docs/plugins/architecture.md`:
  "Native OpenClaw plugins run in-process with the Gateway. They are not sandboxed.")
  — so they have full `node:child_process` access.
- `before_prompt_build` handlers are `async`, so the handler `await`s a subprocess
  to the Python gate. Our plugin spawns `python -m relyable.adapters.openclaw.cli`
  (stdin = candidate notes JSON, stdout = per-note verdicts JSON). **relyable stays
  Python** behind that boundary; nothing is reimplemented in TS.
- Keep the round-trip well under the hook timeout (recall has its own
  `DEFAULT_AUTO_RECALL_TIMEOUT_MS`; `agent_end` is hard-capped at 30 s).

## The promote / "Dreaming" edge has NO plugin hook (out of scope)

- "Dreaming" is an opt-in background **cron** that promotes short-term signals into
  `MEMORY.md`; it is **not** a plugin hook. `PluginHookHandlerMap` contains no
  memory-promotion / dreaming hook. Promotion is a **CLI** command (`openclaw memory
  promote [--apply]`), per `docs/cli/memory.md`.
- Gating promote would therefore mean forking core's promotion path or wrapping the
  `openclaw memory promote` CLI — neither is a stable extension point, so this
  adapter gates **recall** only. (Issue #83126 — "Dreaming promotes content but has
  no mechanism to retire stale rules" — is the promote-side demand witness; the
  recall gate is what a stable hook supports today.)

## Verified this session

- `extensions/memory-lancedb/index.ts` registers `before_prompt_build` returning
  `{prependContext}` / `undefined` (raw GitHub fetch, `main`).
- Issues `openclaw/openclaw#59130` (stale recall, no recency/provenance) and
  `#83126` (Dreaming promotes, never retires) exist (per the discovery pass).

## Not verified / re-confirm before relying

- Exact interface of `PluginHookBeforePromptBuildEvent` beyond `messages` / `prompt`,
  and whether `configSchema` is required vs optional on `definePluginEntry` (our
  `index.mjs` omits it and reads config from env, which avoids guessing the schema
  library). Re-pin against the integrator's OpenClaw version.
- Whether to register against `before_prompt_build` (current) vs the deprecated
  `before_agent_start` compat hook — use `before_prompt_build`.

## Primary sources

- Recall + capture impl (current path, HEAD `2f222cd`): https://github.com/openclaw/openclaw/blob/main/extensions/active-memory/index.ts
  (was `extensions/memory-lancedb/index.ts` at the 2026-06-15 capture — renamed; see Correction above)
- Hook list + timeouts: https://github.com/openclaw/openclaw/blob/main/docs/plugins/hooks.md
- Plugin architecture (in-process, not sandboxed): https://github.com/openclaw/openclaw/blob/main/docs/plugins/architecture.md
- Memory + Dreaming concepts: https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory.md , `.../docs/concepts/dreaming.md`
- Promote CLI: https://github.com/openclaw/openclaw/blob/main/docs/cli/memory.md
- Demand witnesses: https://github.com/openclaw/openclaw/issues/59130 , `.../issues/83126`
