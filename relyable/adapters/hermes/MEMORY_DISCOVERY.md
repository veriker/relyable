# Hermes memory adapter — extension-surface discovery

*Captured 2026-06-16 before writing adapter code. Concrete claims are pinned to
primary sources verified this session (live `gh api` against `NousResearch/hermes-agent`,
`main`). Nothing here is invented; where a fact was not verified it is marked.*

## Verdict

**DETERMINABLE — a real, stable RECALL surface exists: the `MemoryProvider` ABC.**
Wire the gate as a relyable-backed `MemoryProvider` whose `prefetch(query)` recalls
structured notes, re-derives each, and injects only survivors. This is the direct
analogue of the OpenClaw memory adapter (`before_prompt_build`). The write/promote
side (`sync_turn` / `on_session_end` / `queue_prefetch`) is out of scope — recall is
the load-bearing seam, exactly as OpenClaw's "Dreaming" promote-edge was.

## The recall surface: `agent/memory_provider.py::MemoryProvider`

Verified from the real source (`gh api repos/NousResearch/hermes-agent/contents/agent/memory_provider.py`, `main`):

- `MemoryProvider(ABC)` — "pluggable memory providers give the agent persistent
  recall across sessions." Providers ship in `plugins/memory/<name>/` and activate
  via the `memory.provider` config key; **`MemoryManager` enforces a one-external-
  provider limit** ("to prevent tool schema bloat and conflicting memory backends").
- The recall method (the chokepoint):
  ```python
  def prefetch(self, query: str, *, session_id: str = "") -> str:
      """Recall relevant context for the upcoming turn. Called before each API call.
      Return formatted text to inject as context, or empty string if nothing relevant."""
  ```
- `MemoryManager.prefetch_all(user_message)` runs it pre-turn; `build_memory_context_block(raw_context)`
  wraps the returned string in a `<memory-context>` fence (and **warns + strips** if a
  provider returns pre-wrapped text — so a provider must return UNWRAPPED text).
- **Abstract methods** a concrete provider MUST implement: `name` (property),
  `is_available`, `initialize`, `get_tool_schemas`. `prefetch`, `sync_turn`,
  `handle_tool_call`, `shutdown`, `system_prompt_block`, `on_session_end`, … have
  defaults.

## The load-bearing constraint: `prefetch` returns a STRING

`prefetch -> str` returns pre-formatted text, NOT structured `{note_id, payload}`.
relyable re-derives STRUCTURED notes, so it cannot gate an arbitrary provider's prose
blob from outside. Two honest wirings follow:

1. **relyable-backed `MemoryProvider`** (what this adapter ships): relyable owns the
   structured note store, recalls + gates via `relyable.memory.admit_note`, and
   formats only survivors into the prefetch string. It controls the structured->string
   boundary. Activated via `memory.provider`; replaces the external provider slot
   (one-external-provider limit). Native Python — relyable imports in-process, no
   subprocess shim (contrast OpenClaw, which is TypeScript).
2. **Per-provider splice**: source-edit a specific provider (`plugins/memory/hindsight`,
   `…/byterover`) to gate its structured recall results before it stringifies — the
   analogue of splicing into memory-lancedb's `cleanResults`. Per-provider, not generic.

A transparent decorator over another provider does NOT work (only sees the string).

## Why the skills DISCOVERY missed this

The Hermes skills DISCOVERY inspected `hermes_cli/plugins.py::VALID_HOOKS` and found
no memory hook. Correct — but memory has its OWN provider-ABC surface
(`agent/memory_provider.py` + `MemoryManager`, wired in `run_agent.py`), separate
from the plugin-hook system. So unlike skills (no hook → source-edit into
`_security_scan_skill`), memory has a first-class extension point.

## Scope (honest)

Re-derives STRUCTURED notes: a cached computation (recompute mode, no reference) or a
fact checkable against a sealed first-party reference (sealed-reference mode,
`reference_path`). Free-text semantic memory with no checkable claim is out of scope
(relyable covers the correctness/staleness axis). The retriever in this adapter's
`_recall` is a naive deterministic keyword match — a real deployment swaps in the
consumer's retrieval; the GATE is the contribution, not the retriever.

## Not verified this session (flag before relying)

- Exact `MemoryManager.prefetch_all` aggregation order across multiple providers and
  whether a provider exception is swallowed vs. propagated (read the body before
  relying on multi-provider composition; this adapter assumes it is the sole external
  provider, per the one-provider limit).
- Whether `memory.provider` accepts an out-of-tree provider path or requires the
  provider to live under `plugins/memory/<name>/` — re-pin against the integrator's
  Hermes version before packaging for distribution.
- Line numbers drift; re-pin against the integrator's pinned Hermes version.

## Primary sources

- MemoryProvider ABC: https://github.com/NousResearch/hermes-agent/blob/main/agent/memory_provider.py
- MemoryManager (prefetch_all / build_memory_context_block): https://github.com/NousResearch/hermes-agent/blob/main/agent/memory_manager.py
- Provider plugins: https://github.com/NousResearch/hermes-agent/tree/main/plugins/memory (byterover, hindsight, holographic)
- Skills-side discovery (the other surface): ./DISCOVERY.md
