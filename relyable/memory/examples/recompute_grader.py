#!/usr/bin/env python3
"""recompute_grader.py — a worked RECOMPUTE grader for relyable.memory.

The turnkey memory case, needing **no external reference**. The recalled note is a
CACHED COMPUTATION; before the agent reuses it, the grader RE-RUNS the computation
from the note's own inputs and admits only if the cached result reproduces. The
authority is **determinism** — there is nothing to curate or seal, and
``reference_path`` is not needed. (Use the sealed-reference grader instead when the
note is a *fact about the world* the agent can't recompute.)

Note shape:
    RECALLED = {"items": [<numbers>], "result": {"count": .., "sum": .., "max": ..}}

Exit 0 iff ``recompute(items) == result``; exit 1 otherwise — a stale or poisoned
cache whose result no longer matches its inputs.

The recalled note is the bundle's candidate body, exec'd here and NEVER trusted as
a value: only ``items`` feeds the recomputation; the cached ``result`` is compared
against, never used. Replace ``_recompute`` with your own pure function to make a
real recompute grader. stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _fail(msg: str) -> int:
    print(f"[RECOMPUTE_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def _recompute(items: list) -> dict:
    """The pure computation we are caching. Re-run from the note's inputs; the
    note's stored result is compared against this, never trusted."""
    return {
        "count": len(items),
        "sum": sum(items),
        "max": max(items) if items else None,
    }


def _recalled(snippet: str):
    """Exec the candidate body and read its ``RECALLED`` binding. Gated, never
    trusted as a value."""
    ns: dict = {}
    try:
        exec(snippet, ns)  # noqa: S102 — candidate from memory; gated, never trusted
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"candidate_exec_fail: {type(e).__name__}: {e}") from e
    return ns.get("RECALLED")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    bundle = Path(ap.parse_args().bundle_dir)

    try:
        snippet = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    except OSError as e:
        return _fail(f"candidate_unreadable: {e}")
    try:
        note = _recalled(snippet)
    except ValueError as e:
        return _fail(str(e))

    if not isinstance(note, dict):
        return _fail("recalled_note_not_a_dict")
    items = note.get("items")
    cached = note.get("result")
    if not isinstance(items, list) or not all(
        isinstance(x, (int, float)) for x in items
    ):
        return _fail("recalled_note_items_not_a_number_list")
    if not isinstance(cached, dict):
        return _fail("recalled_note_missing_result")

    # The re-derivation: admit ONLY if recomputing from the note's own inputs
    # reproduces its cached result.
    recomputed = _recompute(items)
    if recomputed == cached:
        return 0
    return _fail(f"cache_not_re_derivable: recomputed {recomputed} != cached {cached}")


if __name__ == "__main__":
    sys.exit(main())
