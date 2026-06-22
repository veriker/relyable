"""anchor.py — pin the sealed reference so it can't be silently rewritten.

The memory binding's sealed-reference mode (mode 2) is only as strong as the
reference is immutable: it trusts whatever is at ``reference_path`` when the grader
runs. If the recall-time agent (or an injected step) can write to that directory,
the guarantee degrades silently. The reference anchor closes that gap — the same
SpecAnchor move ``relyable.verdicts`` uses on its config.

Workflow: build the reference separately, pin its digest ONCE (out-of-band, e.g.
``relyable-memory anchor ./sealed_reference`` -> a sha you store in CI / env), then
pass it to ``admit_note(..., reference_anchor=...)``. Before trusting anything the
gate re-hashes the reference tree and REFUSES on mismatch — so any later tampering
of the reference is caught, turning "pin it before recall" from a discipline into
an enforced property.

The digest is over the reference tree's file contents + relative paths, sorted and
deterministic; ``__pycache__`` / ``*.pyc`` are excluded (they are build artifacts,
not the reference). Stdlib only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class ReferenceAnchorMismatch(Exception):
    """Raised (or surfaced as a REJECT) when a pinned reference anchor was supplied
    and the reference tree's recomputed digest does not match it."""


def _reference_files(reference_path: Path) -> list[Path]:
    return sorted(
        p
        for p in reference_path.rglob("*")
        if p.is_file()
        and p.suffix != ".pyc"
        and "__pycache__" not in p.relative_to(reference_path).parts
    )


def compute_reference_anchor(reference_path: Path) -> str:
    """SHA-256 over the reference tree: each file's relative POSIX path + its bytes,
    in sorted order. Deterministic; ``__pycache__`` / ``*.pyc`` excluded. This is
    the commitment the trusted side pins out-of-band."""
    h = hashlib.sha256()
    h.update(b"relyable-reference\0")
    for f in _reference_files(reference_path):
        rel = f.relative_to(reference_path).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def verify_reference_anchor(computed: str, expected: str | None) -> None:
    """Raise ``ReferenceAnchorMismatch`` when an expected anchor was supplied and
    the recomputed digest does not match. A None expected anchor is advisory (no
    enforcement) — same posture as the verdicts config anchor."""
    if expected is not None and computed != expected:
        raise ReferenceAnchorMismatch(
            f"reference anchor mismatch: expected {expected[:16]}…, "
            f"recomputed {computed[:16]}… — the sealed reference changed"
        )
