"""cli.py — the recall-admission surface. ``relyable-memory check | anchor``.

Re-derive one recalled note against a sealed reference; exit 0 iff it re-derives:

    relyable-memory check --note-id pkg --note '{"package":"acme-http","version":"1.4.2"}' \
        --grader ./recall_grader.py --reference ./sealed/

    relyable-memory check ... --reference ./sealed/ --reference-anchor $REF_ANCHOR --json

Pin a sealed reference so later tampering is caught:

    relyable-memory anchor ./sealed/        # prints the digest to store in CI / env

``--note`` is the recalled payload as JSON. ``--reference`` is the directory of the
sealed first-party reference the grader imports (set on PYTHONPATH, never bundle-
supplied). ``--reference-anchor`` pins it: the gate refuses if the reference's
digest changed. ``--no-run`` sets permit_execution=False (won't run the grader; the
note is refused). Exit code is non-zero if the note is refused, so a poisoned
recall stops the pipeline. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .anchor import compute_reference_anchor
from .gate import ADMIT, admit_note


def _cmd_check(args: argparse.Namespace) -> int:
    grader = Path(args.grader)
    if not grader.is_file():
        print(f"grader not a file: {grader}", file=sys.stderr)
        return 2
    reference = Path(args.reference) if args.reference else None
    if reference is not None and not reference.is_dir():
        print(f"reference not a directory: {reference}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(args.note)
    except ValueError as e:
        print(f"--note is not valid JSON: {e}", file=sys.stderr)
        return 2

    v = admit_note(
        args.note_id,
        payload,
        grader_src=grader,
        reference_path=reference,
        reference_anchor=args.reference_anchor,
        permit_execution=not args.no_run,
        pack_filename=args.pack_filename,
    )

    if args.json:
        print(json.dumps(asdict(v), indent=2))
    else:
        print(f"{v.verdict}  {v.note_id}  [{v.reason_code}]  {v.detail}")
    return 0 if v.verdict == ADMIT else 1


def _cmd_anchor(args: argparse.Namespace) -> int:
    reference = Path(args.reference)
    if not reference.is_dir():
        print(f"reference not a directory: {reference}", file=sys.stderr)
        return 2
    print(compute_reference_anchor(reference))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="relyable-memory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="re-derive one recalled note against a reference")
    p.add_argument("--note-id", dest="note_id", required=True)
    p.add_argument("--note", required=True, help="the recalled payload as JSON")
    p.add_argument(
        "--grader", required=True, help="path to the consumer's trusted recall grader"
    )
    p.add_argument(
        "--reference",
        default=None,
        help="dir of the sealed first-party reference the grader imports",
    )
    p.add_argument(
        "--reference-anchor",
        dest="reference_anchor",
        default=None,
        help="pinned reference digest (from `anchor`); refuse if the reference changed",
    )
    p.add_argument(
        "--no-run",
        action="store_true",
        help="permit_execution=False (do not run the grader; note is refused)",
    )
    p.add_argument(
        "--pack-filename",
        dest="pack_filename",
        default=None,
        help="grader filename inside the bundle (defaults to the grader's name)",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=_cmd_check)

    p_anchor = sub.add_parser("anchor", help="print the digest to pin a reference dir")
    p_anchor.add_argument("reference", help="dir of the sealed first-party reference")
    p_anchor.set_defaults(func=_cmd_anchor)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
