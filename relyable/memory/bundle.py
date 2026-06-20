"""bundle.py — assemble a real veriker bundle around a recalled note.

The recalled note is the CLAIM: a payload the agent pulled from memory plus an
id. This binding renders the payload as a digest-bound candidate body
(``RECALLED = <payload>``) and assembles it into a real veriker audit bundle so
veriker's verifier can re-derive it against the sealed reference. The grader is
ALWAYS installed from the consumer's own trusted copy (``grader_src``); the bundle
supplies only the recalled payload + meta.

Thin wrapper over ``relyable.gate.build_attested_bundle``.
"""

from __future__ import annotations

from pathlib import Path

from relyable.gate import build_attested_bundle


def render_candidate(payload: object) -> str:
    """Render a recalled payload as the digest-bound candidate body. The grader
    execs this and reads ``RECALLED``; the value is gated, never trusted. ``repr``
    keeps JSON-able payloads (dict/list/str/int/float/bool/None) as valid Python
    literals."""
    return f"RECALLED = {payload!r}\n"


def build_note_bundle(
    dest: Path,
    *,
    note_id: str,
    payload: object,
    grader_src: Path,
    kind: str = "recalled_note",
    pack_filename: str | None = None,
) -> Path:
    """Write a real veriker bundle for one recalled note at ``dest``. Returns
    ``dest``."""
    return build_attested_bundle(
        dest,
        candidate_body=render_candidate(payload),
        meta={"skill_id": note_id, "kind": kind},
        grader_src=grader_src,
        pack_filename=pack_filename,
        bundle_id=f"relyable-note-{note_id}",
    )
