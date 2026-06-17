#!/usr/bin/env python3
"""exec_skill_grader.py — a worked re-derivation GRADER for NATIVE skills.

Companion to ``interval_grader.py``, but for skills packaged with
``relyable.adapters._skillpack.pack_native_skill``: instead of importing a single
``skill/candidate.py``, it RUNS the skill's own entrypoint (declared in
skill/meta.json's ``invocation``) as a subprocess and checks its output against the
consumer's held-out goldens.

WHY THIS IS NOT "the producer grading its own homework": the skills binding installs
THIS exact file (the consumer's trusted copy) into every bundle's re_derive/ — the
producer's bundle supplies only the skill body. The GOLDENS below are consumer-
distribution, pinned here, never bundle-supplied. The ``invocation`` from meta.json
is only a hint (which file to run); a lying entrypoint cannot pass — it must actually
reproduce the goldens. Per the auditor-independence contract: NO veriker import,
stdlib only.

Re-derivation steps:
  1. Read skill/meta.json -> {kind, invocation}.
  2. Look up GOLDENS[kind]; fail-closed if the kind has no goldens.
  3. Build the runner command from invocation (allowlisted runner only).
  4. For each held-out cell: run the entrypoint on the cell input, compare output
     exactly to the golden. Exit 0 iff every cell matches, else 1 with a reason.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# --- consumer-distribution authority (pinned HERE, never bundle-supplied) ------
# One entry per skill "kind". Each cell is (input_text, expected_output_text).
# A real consumer replaces these with their own held-out goldens.
GOLDENS: dict[str, list[tuple[str, str]]] = {
    # CSV (header + rows) on stdin -> JSON array of objects on stdout (compact).
    "csvjson": [
        (
            "name,age\nada,36\nlin,42\n",
            '[{"name": "ada", "age": "36"}, {"name": "lin", "age": "42"}]',
        ),
        ("x\n1\n", '[{"x": "1"}]'),
    ],
    # Text on stdin -> the number of non-empty lines on stdout.
    "linecount": [
        ("a\nb\nc\n", "3"),
        ("only one line\n", "1"),
    ],
}

# Runners the grader will shell out to (must match _skillpack.RUNNERS).
_RUNNER_CMD = {"python": [sys.executable], "sh": ["sh"], "node": ["node"]}


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def _norm(s: str) -> str:
    """Normalize trailing whitespace/newlines so a skill that prints a trailing
    newline is not penalized; internal content must still match exactly."""
    return s.replace("\r\n", "\n").rstrip("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    args = ap.parse_args()
    bundle = Path(args.bundle_dir)

    try:
        meta = json.loads((bundle / "skill" / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"meta_unreadable: {e}")

    kind = meta.get("kind")
    cells = GOLDENS.get(kind)
    if not cells:  # fail-closed: unknown kind never all([])->pass
        return _fail(f"no_goldens_for_kind: {kind!r}")

    inv = meta.get("invocation") or {}
    entrypoint = inv.get("entrypoint")
    runner = inv.get("runner")
    if not entrypoint or runner not in _RUNNER_CMD:
        return _fail(f"bad_invocation: entrypoint={entrypoint!r} runner={runner!r}")
    ep_path = (bundle / "skill" / entrypoint).resolve()
    # Containment: the entrypoint must live inside the bundle's skill/ tree.
    if (bundle / "skill").resolve() not in ep_path.parents or not ep_path.is_file():
        return _fail(f"entrypoint_not_in_bundle: {entrypoint!r}")

    cmd = _RUNNER_CMD[runner] + [str(ep_path)]
    input_mode = inv.get("input_mode", "stdin")

    for i, (cell_in, golden_out) in enumerate(cells):
        run_cmd = cmd + ([cell_in] if input_mode == "argv" else [])
        stdin_data = cell_in if input_mode == "stdin" else None
        try:
            res = subprocess.run(
                run_cmd,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return _fail(f"cell{i}: timeout")
        except OSError as e:  # e.g. runner binary missing
            return _fail(f"cell{i}: runner_unavailable: {e}")
        if res.returncode != 0:
            return _fail(
                f"cell{i}: entrypoint_exit_{res.returncode}: {res.stderr[:200]}"
            )
        if _norm(res.stdout) != _norm(golden_out):
            return _fail(f"cell{i}: mismatch (got {res.stdout[:120]!r})")
    return 0  # every held-out cell reproduced -> RE_DERIVED


if __name__ == "__main__":
    sys.exit(main())
