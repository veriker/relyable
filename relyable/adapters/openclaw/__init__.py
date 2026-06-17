"""relyable.adapters.openclaw — wire relyable.memory into OpenClaw recall.

OpenClaw is TypeScript/Node; relyable is Python. The adapter is two faithful parts
across the language boundary:

  * the **TS plugin** (``plugin/``) registers OpenClaw's ``before_prompt_build``
    hook, collects the recalled notes it would inject, and spawns the Python gate;
    it returns ``{prependContext}`` of only the re-deriving notes, or ``undefined``
    to inject nothing when none survive — exactly the admit/refuse contract the
    ``memory-lancedb`` extension uses on that hook;
  * the **Python gate** (this package, spawned as ``relyable-openclaw-recall``)
    loops ``relyable.memory.admit_note`` over the batch.

It adds no trust logic; the grader (and, for sealed-reference mode, the reference)
are host config (``RecallGateConfig``), never shipped. See ``DISCOVERY.md`` for the
hook signature, the subprocess boundary, and why the promote/Dreaming edge has no
plugin hook.
"""

from __future__ import annotations

from .config import RecallGateConfig
from .recall_gate import (
    NoteGateResult,
    admitted_note_ids,
    gate_recalled_note,
    gate_recalled_notes,
)

__all__ = [
    "NoteGateResult",
    "RecallGateConfig",
    "admitted_note_ids",
    "gate_recalled_note",
    "gate_recalled_notes",
]
