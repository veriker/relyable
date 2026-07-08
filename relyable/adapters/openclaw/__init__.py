"""relyable.adapters.openclaw — wire relyable into OpenClaw's input + output edges.

OpenClaw is TypeScript/Node; relyable is Python. The adapter gates both edges, each
as two faithful parts across the language boundary:

  * **recall (input edge)** — the TS plugin registers OpenClaw's
    ``before_prompt_build`` hook, collects the recalled notes it would inject, and
    spawns the Python gate; it returns ``{prependContext}`` of only the re-deriving
    notes, or ``undefined`` to inject nothing when none survive (the admit/refuse
    contract the bundled recall extension uses). Python side: ``recall_gate.py``
    loops ``relyable.memory.admit_note`` (spawned as ``relyable-openclaw-recall``).
  * **deliver (output edge)** — the TS plugin registers OpenClaw's
    ``message_sending`` hook (fires post-generation, pre-send, supports
    ``{cancel: true}``), and suppresses any outbound deliverable that does not
    re-derive — the ``openclaw/openclaw#49876`` fail-closed ask. Python side:
    ``deliver_gate.py`` (spawned as ``relyable-openclaw-deliver``).

It adds no trust logic; the grader (and, for sealed-reference mode, the reference)
are host config (``RecallGateConfig`` / ``DeliverGateConfig``), never shipped. See
``DISCOVERY.md`` (recall hook + subprocess boundary) and
``../../../DELIVER_EDGE_DISCOVERY.md`` (the verified ``message_sending`` seam).
"""

from __future__ import annotations

from .config import DeliverGateConfig, RecallGateConfig
from .deliver_gate import (
    DeliverGateResult,
    admitted_deliverable_ids,
    cancelled_deliverable_ids,
    gate_deliverable,
    gate_deliverables,
)
from .recall_gate import (
    NoteGateResult,
    admitted_note_ids,
    gate_recalled_note,
    gate_recalled_notes,
)

__all__ = [
    "DeliverGateConfig",
    "DeliverGateResult",
    "NoteGateResult",
    "RecallGateConfig",
    "admitted_deliverable_ids",
    "admitted_note_ids",
    "cancelled_deliverable_ids",
    "gate_deliverable",
    "gate_deliverables",
    "gate_recalled_note",
    "gate_recalled_notes",
]
