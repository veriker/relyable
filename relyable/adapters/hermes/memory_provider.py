"""memory_provider.py — relyable as a Hermes MemoryProvider (recall gate).

Mirror of the OpenClaw memory adapter onto Hermes. Hermes recalls stored notes
into each turn via the `MemoryProvider` ABC (`agent/memory_provider.py`):
`prefetch(query) -> str` is "recall relevant context for the upcoming turn,"
the direct analogue of OpenClaw's `before_prompt_build` recall hook. This provider
re-derives each recalled note through `relyable.memory.admit_note` and injects ONLY
the notes that hold — a stale/poisoned note is dropped, never trusted because it
was remembered.

WHY A PROVIDER (not a decorator): Hermes's `prefetch` returns a pre-formatted
STRING, and `MemoryManager` enforces a one-external-provider limit. A transparent
decorator over another provider would only see that string — nothing structured to
re-derive. So relyable OWNS the structured note store here and controls the
structured->string boundary: it recalls `{note_id, payload}` notes, gates them, and
formats only survivors. (Gating a different provider's structured results instead is
a per-provider source-edit — see MEMORY_DISCOVERY.md.)

SCOPE (honest, same as OpenClaw): re-derives STRUCTURED notes — a cached
computation (recompute mode) or a fact checkable against a sealed first-party
reference (sealed-reference mode). Free-text semantic memory with no checkable claim
is out of scope. The recall/write side beyond `prefetch` (sync_turn / on_session_end
/ promotion) is out of scope for this gate — recall is the load-bearing seam.

Hermes-free by design: relyable does not depend on Hermes. If `agent.memory_provider`
is importable (running inside Hermes) we subclass its ABC so this registers as a real
provider; otherwise we fall back to a plain base so the class is testable standalone.
The method surface matches the ABC either way.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from relyable.memory import ADMIT, RecallVerdict, admit_note

try:  # real Hermes ABC when running inside the harness; plain base otherwise
    from agent.memory_provider import MemoryProvider as _Base  # type: ignore
except ImportError:  # standalone / test
    _Base = object  # type: ignore


class RelyableMemoryProvider(_Base):  # type: ignore[misc,valid-type]
    """A Hermes MemoryProvider that gates recall through relyable.memory.

    Holds a structured note store (`notes`: a list of {note_id, payload, kind?,
    keywords?}). `prefetch` recalls the notes matching the turn's query, re-derives
    each through the consumer's grader, and returns ONLY the survivors formatted for
    injection (empty string when none hold). The grader is the consumer's trust root
    and has no default — recompute mode needs no reference; sealed-reference mode
    needs `reference_path`."""

    def __init__(
        self,
        notes: List[Dict[str, Any]] | None = None,
        *,
        grader_src: Path,
        reference_path: Path | None = None,
        reference_anchor: str | None = None,
        permit_execution: bool = True,
        pack_filename: str | None = None,
    ) -> None:
        self._notes: List[Dict[str, Any]] = list(notes or [])
        self._grader_src = Path(grader_src)
        self._reference_path = reference_path
        self._reference_anchor = reference_anchor
        self._permit_execution = permit_execution
        self._pack_filename = pack_filename
        self._session_id = ""

    # -- MemoryProvider ABC: required surface ---------------------------------

    @property
    def name(self) -> str:
        return "relyable"

    def is_available(self) -> bool:
        """Ready iff the consumer's trusted grader exists. A provider with no trust
        root must not silently admit, so this is the activation gate."""
        return self._grader_src.is_file()

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        # No model-facing tools: this provider only gates auto-recall.
        return []

    # -- The recall gate (the load-bearing override) --------------------------

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall + re-derive: inject only notes that hold. Empty string when none
        survive (Hermes injects nothing). Returns UNWRAPPED text — Hermes's
        `build_memory_context_block` adds the <memory-context> fence."""
        survivors, _ = self.gate_recall(query)
        return self._format(survivors)

    def gate_recall(
        self, query: str
    ) -> tuple[List[Dict[str, Any]], List[RecallVerdict]]:
        """Core: recall candidates for `query`, re-derive each. Returns (survivors,
        all-verdicts) — verdicts (admitted and refused alike) are the audit trail."""
        survivors: List[Dict[str, Any]] = []
        verdicts: List[RecallVerdict] = []
        for note in self._recall(query):
            v = admit_note(
                note["note_id"],
                note["payload"],
                grader_src=self._grader_src,
                reference_path=self._reference_path,
                reference_anchor=self._reference_anchor,
                permit_execution=self._permit_execution,
                pack_filename=self._pack_filename,
                kind=note.get("kind", "recalled_note"),
            )
            verdicts.append(v)
            if v.verdict == ADMIT:
                survivors.append(note)
        return survivors, verdicts

    # -- helpers --------------------------------------------------------------

    def _recall(self, query: str) -> List[Dict[str, Any]]:
        """Naive deterministic recall: a note matches when the query shares a token
        with its declared `keywords` or appears in its note_id/payload text. An empty
        query recalls nothing (mirrors auto-recall being off). A real deployment
        swaps this for the consumer's retrieval (vector/keyword) — the GATE is the
        contribution, not the retriever."""
        tokens = {t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3}
        if not tokens:
            return []
        out: List[Dict[str, Any]] = []
        for note in self._notes:
            if "note_id" not in note or "payload" not in note:
                continue  # malformed note never recalled (fail-closed)
            kws = {str(k).lower() for k in note.get("keywords", [])}
            hay = (str(note["note_id"]) + " " + json.dumps(note["payload"])).lower()
            if (tokens & kws) or any(t in hay for t in tokens):
                out.append(note)
        return out

    @staticmethod
    def _format(notes: List[Dict[str, Any]]) -> str:
        if not notes:
            return ""
        return "\n".join(
            f"- {n['note_id']}: {json.dumps(n['payload'], sort_keys=True)}"
            for n in notes
        )

    # -- optional ABC hooks: keep no-op so a plain base is also valid ----------

    def system_prompt_block(self) -> str:
        return ""

    def sync_turn(self, *args: Any, **kwargs: Any) -> None:
        # Write side is out of scope for the recall gate (see module docstring).
        return None

    def shutdown(self) -> None:
        return None

    # -- construction from Hermes config env ----------------------------------

    @classmethod
    def from_env(cls, env: Dict[str, str] | None = None) -> "RelyableMemoryProvider":
        """Build from RELYABLE_HERMES_MEMORY_* env vars:
        RELYABLE_HERMES_MEMORY_GRADER            (required) consumer's trusted grader.
        RELYABLE_HERMES_MEMORY_NOTES             (required) path to a JSON list of
                                                 {note_id, payload, kind?, keywords?}.
        RELYABLE_HERMES_MEMORY_REFERENCE         (optional) sealed-reference dir.
        RELYABLE_HERMES_MEMORY_REFERENCE_ANCHOR  (optional) pin for the reference.
        RELYABLE_HERMES_MEMORY_PERMIT_EXECUTION  (optional) "0" disables (refuses all).
        """
        e = env if env is not None else dict(os.environ)
        grader = e.get("RELYABLE_HERMES_MEMORY_GRADER")
        if not grader:
            raise ValueError(
                "RELYABLE_HERMES_MEMORY_GRADER is required (the consumer's trusted "
                "grader is the gate's trust root and has no default)"
            )
        notes_path = e.get("RELYABLE_HERMES_MEMORY_NOTES")
        notes: List[Dict[str, Any]] = []
        if notes_path:
            notes = json.loads(Path(notes_path).read_text(encoding="utf-8"))
        ref = e.get("RELYABLE_HERMES_MEMORY_REFERENCE")
        return cls(
            notes,
            grader_src=Path(grader),
            reference_path=Path(ref) if ref else None,
            reference_anchor=e.get("RELYABLE_HERMES_MEMORY_REFERENCE_ANCHOR") or None,
            permit_execution=(e.get("RELYABLE_HERMES_MEMORY_PERMIT_EXECUTION") or "1")
            != "0",
        )
