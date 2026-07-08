"""recall_gate.py — gate a batch of recalled OpenClaw notes through relyable.memory.

The Python side of the OpenClaw adapter. OpenClaw's ``before_prompt_build`` hook
(in a TS plugin) proposes recalled notes to inject as ``<relevant-memories>``; this
gate re-derives each one and returns only those that hold, so the plugin injects
only re-deriving notes (and injects nothing — returns ``undefined`` — when none
survive). It adds no trust logic: it loops ``relyable.memory.admit_note`` over the
batch.

A candidate is ``{"note_id": str, "payload": <json>}``. ``payload`` is the recalled
value; it is never trusted as a value — the grader re-derives it (recompute mode)
or checks it against the sealed reference (sealed-reference mode). See
``DISCOVERY.md`` for the hook and the structured-note scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from relyable.memory import ADMIT, admit_note

from .config import RecallGateConfig


@dataclass(frozen=True, slots=True)
class NoteGateResult:
    """One recalled note's verdict. ``admitted`` is True iff it re-derived."""

    note_id: str
    verdict: str
    reason_code: str
    detail: str
    rederived: bool

    @property
    def admitted(self) -> bool:
        return self.verdict == ADMIT


def gate_recalled_note(
    note_id: str,
    payload: object,
    config: RecallGateConfig,
) -> NoteGateResult:
    """Re-derive one recalled note. ADMIT iff it re-derives against the grader
    (recompute) or the sealed reference; otherwise REJECT (refused)."""
    v = admit_note(
        note_id,
        payload,
        grader_src=config.grader_src,
        reference_path=config.reference_path,
        reference_anchor=config.reference_anchor,
        permit_execution=config.permit_execution,
        pack_filename=config.pack_filename,
    )
    return NoteGateResult(
        note_id=v.note_id,
        verdict=v.verdict,
        reason_code=v.reason_code,
        detail=v.detail,
        rederived=v.rederived,
    )


def gate_recalled_notes(
    candidates: list[dict],
    config: RecallGateConfig,
) -> list[NoteGateResult]:
    """Gate a batch of candidate recalled notes. Returns one result per candidate
    (admitted and refused alike) for the audit trail. A candidate missing a
    ``note_id`` is refused, not skipped (fail-closed: a malformed recall does not
    silently vanish into an injected-anyway state)."""
    out: list[NoteGateResult] = []
    for i, cand in enumerate(candidates):
        note_id = str(cand.get("note_id") or f"note_{i}")
        if "payload" not in cand:
            out.append(
                NoteGateResult(
                    note_id,
                    "REJECT",
                    "MALFORMED_CANDIDATE",
                    "candidate has no 'payload' to re-derive",
                    rederived=False,
                )
            )
            continue
        out.append(gate_recalled_note(note_id, cand["payload"], config))
    return out


def admitted_note_ids(results: list[NoteGateResult]) -> list[str]:
    """The note_ids the plugin may inject: those that re-derived."""
    return [r.note_id for r in results if r.admitted]
