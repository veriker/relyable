"""gate.py — the recall admission gate, standing on relyable.gate / veriker.

The memory binding's chokepoint. A recalled note is a CLAIM. Before the agent may
use it, the note must **re-derive** — not be trusted because it was remembered. A
note that does not re-derive is REFUSED. The grader decides HOW it re-derives:

  * **recompute** — the note is a cached computation; the grader re-runs it from
    the note's own inputs (no ``reference_path`` — the authority is determinism);
  * **sealed reference** — the note is a fact; the grader checks it against a
    sealed first-party reference passed via ``reference_path``.

    verdict = admit_note(note_id, payload, grader_src=g, reference_path=ref_dir)
    if verdict.verdict == ADMIT:
        use(payload)            # re-derived (recomputed, or matched the reference)
    else:
        ...                     # refused — re-derive it yourself

The decision is purely veriker's ``verify().ok`` over the grader's re-derivation;
the recalled payload never enters the decision as a trusted value. The grader is
pinned (byte-identical) into the bundle. In the sealed-reference mode the reference
is imported by the grader **via the gate-set PYTHONPATH (``reference_path``), never
from the bundle** — so a poisoned note that ships its own fake reference cannot
override the real one; that mode is no stronger than the reference it is given.

Evidence: ALE Exp H3 (powered, n=60/cell/tier) — the gate collapses corroborated
memory poisoning to ASR 0.000 while raw recall climbs, and its value is that it
does NOT depend on the social channel surfacing the truth. Exp M (n=50): verified-
good memory is a safe lift at zero wrapper cost; the same gate refuses poison.
Exp D/E/persistent-E: recover-to-baseline across real multi-session drift.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from relyable.gate import verify_attested_bundle

from .anchor import (
    ReferenceAnchorMismatch,
    compute_reference_anchor,
    verify_reference_anchor,
)
from .bundle import build_note_bundle

ADMIT = "ADMIT"
REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class RecallVerdict:
    """The re-derived verdict for one recalled note. ``verdict`` (ADMIT/REJECT) is
    veriker's ``verify().ok`` over the grader's re-derivation against the sealed
    reference. ``rederived`` is True only when the note affirmatively re-derived."""

    note_id: str
    verdict: str
    reason_code: str
    detail: str
    rederived: bool


def admit_note(
    note_id: str,
    payload: object,
    *,
    grader_src: Path,
    reference_path: Path | None = None,
    reference_anchor: str | None = None,
    permit_execution: bool = True,
    pack_filename: str | None = None,
    kind: str = "recalled_note",
    work_dir: Path | None = None,
) -> RecallVerdict:
    """Admit one recalled note through veriker.

    ``payload`` is the recalled value (any JSON-able object); it is rendered as the
    digest-bound candidate and is never trusted as an input to the decision.
    ``grader_src`` is the consumer's trusted grader (it re-derives the note against
    the sealed reference). ``reference_path`` is the directory holding the sealed
    first-party reference module(s) the grader imports — set on PYTHONPATH around
    the verify call, verifier-side, never bundle-supplied. ``reference_anchor``, if
    given, pins that reference: the gate recomputes the reference tree's digest and
    REFUSES (fail-closed, before any verify) on mismatch — so a reference tampered
    after it was pinned is caught (see ``relyable.memory.anchor``). ``permit_execution``
    mirrors veriker (default True: run the grader to re-derive; False = could-not-
    conclude, refused).
    """
    # Reference-anchor enforcement, fail-closed BEFORE building/verifying anything.
    if reference_anchor is not None:
        if reference_path is None:
            return RecallVerdict(
                note_id,
                REJECT,
                "REFERENCE_ANCHOR_NO_REFERENCE",
                "reference_anchor supplied without a reference_path to pin",
                rederived=False,
            )
        try:
            verify_reference_anchor(
                compute_reference_anchor(reference_path), reference_anchor
            )
        except ReferenceAnchorMismatch as e:
            return RecallVerdict(
                note_id, REJECT, "REFERENCE_ANCHOR_MISMATCH", str(e), rederived=False
            )

    if work_dir is not None:
        return _admit_in(
            Path(work_dir),
            note_id,
            payload,
            grader_src=grader_src,
            reference_path=reference_path,
            permit_execution=permit_execution,
            pack_filename=pack_filename,
            kind=kind,
        )
    with tempfile.TemporaryDirectory(prefix="relyable-recall-") as td:
        return _admit_in(
            Path(td),
            note_id,
            payload,
            grader_src=grader_src,
            reference_path=reference_path,
            permit_execution=permit_execution,
            pack_filename=pack_filename,
            kind=kind,
        )


def _admit_in(
    work_dir: Path,
    note_id: str,
    payload: object,
    *,
    grader_src: Path,
    reference_path: Path | None,
    permit_execution: bool,
    pack_filename: str | None,
    kind: str,
) -> RecallVerdict:
    bundle_dir = build_note_bundle(
        work_dir / note_id,
        note_id=note_id,
        payload=payload,
        grader_src=grader_src,
        kind=kind,
        pack_filename=pack_filename,
    )
    res = verify_attested_bundle(
        bundle_dir,
        grader_src=grader_src,
        pack_filename=pack_filename,
        permit_execution=permit_execution,
        env_pythonpath=str(reference_path) if reference_path is not None else None,
    )
    if not res.grader_ok:
        # Grader absent / not the consumer's trusted copy: refuse, fail-closed.
        return RecallVerdict(
            note_id,
            REJECT,
            res.grader_reason_code or "NO_GRADER",
            res.detail,
            rederived=False,
        )
    if res.ok:
        return RecallVerdict(
            note_id, ADMIT, "RE_DERIVED", "re-derived against sealed reference", True
        )
    # could-not-conclude (permit_execution=False) or active contradiction: refuse.
    code = res.first_reason_code or (
        "VERIFIER_INCOMPLETE" if res.is_error else "REJECT"
    )
    return RecallVerdict(note_id, REJECT, code, res.detail, rederived=False)
