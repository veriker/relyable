"""test_admission_gate.py — the lifted relyable.gate over a real veriker bundle.

Mirrors the l11 attested-registry behavior on a tiny self-contained grader:
  * a re-deriving candidate is ADMITTED (verdict.ok), and
  * a poisoned bundle is REFUSED — both the grader-swap (the gate's distinctive
    digest-pin: the producer cannot ship a lying grader) and a wrong candidate
    (real re-derivation mismatch through veriker's gated pack lane).

Importing relyable.gate resolves the veriker verify surface through the declared
veriker dependency.
"""

from __future__ import annotations

from pathlib import Path

from relyable.gate import (
    GRADER_MISMATCH,
    build_attested_bundle,
    verify_attested_bundle,
)

# A tiny verifier-distribution grader: read the candidate, exec it (the gated
# bundle-code-exec lane), and exit 0 iff `double(x) == 2*x` on held-out inputs.
_GRADER_BODY = """#!/usr/bin/env python3
import argparse, ast, json, sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    args = ap.parse_args()
    bundle = Path(args.bundle_dir)
    body = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    try:
        ast.parse(body)
    except SyntaxError as e:
        print(f"[REDER_FAIL] parse: {e}", file=sys.stderr)
        return 1
    ns: dict = {}
    try:
        exec(body, ns)  # noqa: S102 - bundle-code-exec; veriker's gated lane
    except Exception as e:  # noqa: BLE001
        print(f"[REDER_FAIL] import: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    fn = ns.get("double")
    if not callable(fn):
        print("[REDER_FAIL] no double()", file=sys.stderr)
        return 1
    for x, want in ((2, 4), (5, 10), (0, 0), (-3, -6)):
        try:
            got = fn(x)
        except Exception as e:  # noqa: BLE001
            print(f"[REDER_FAIL] double({x}) raised {e}", file=sys.stderr)
            return 1
        if got != want:
            print(f"[REDER_FAIL] double({x})={got} != {want}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""

_META = {"skill_id": "double", "kind": "double"}
_CORRECT = "def double(x):\n    return x * 2\n"
_WRONG = "def double(x):\n    return x + 2\n"  # double(5)=7 != 10


def _grader_src(tmp_path: Path) -> Path:
    src = tmp_path / "double_pack.py"
    src.write_text(_GRADER_BODY, encoding="utf-8")
    return src


def test_admits_a_rederiving_bundle(tmp_path):
    grader_src = _grader_src(tmp_path)
    bundle = build_attested_bundle(
        tmp_path / "good",
        candidate_body=_CORRECT,
        meta=_META,
        grader_src=grader_src,
        bundle_id="relyable-gate-admit",
    )
    res = verify_attested_bundle(bundle, grader_src=grader_src, permit_execution=True)
    assert res.grader_ok
    assert res.ok, res.detail


def test_refuses_a_poisoned_grader(tmp_path):
    """The gate pins the bundle's grader to the trusted copy: a swapped (lying)
    grader fails the digest-pin BEFORE any verify().ok is trusted."""
    grader_src = _grader_src(tmp_path)
    bundle = build_attested_bundle(
        tmp_path / "poisoned",
        candidate_body=_WRONG,  # would fail anyway, but the swap is caught first
        meta=_META,
        grader_src=grader_src,
        bundle_id="relyable-gate-poison",
    )
    # Producer swaps in a lying exit(0) grader after assembly.
    (bundle / "re_derive" / "double_pack.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    res = verify_attested_bundle(bundle, grader_src=grader_src, permit_execution=True)
    assert not res.grader_ok
    assert res.grader_reason_code == GRADER_MISMATCH
    assert not res.ok


def test_refuses_a_wrong_candidate(tmp_path):
    """A genuine re-derivation mismatch (correct grader, wrong candidate) is not
    admitted — the candidate is graded inside veriker's gated pack lane."""
    grader_src = _grader_src(tmp_path)
    bundle = build_attested_bundle(
        tmp_path / "wrong",
        candidate_body=_WRONG,
        meta=_META,
        grader_src=grader_src,
        bundle_id="relyable-gate-wrong",
    )
    res = verify_attested_bundle(bundle, grader_src=grader_src, permit_execution=True)
    assert res.grader_ok  # grader pinned fine
    assert not res.ok, res.detail  # but the candidate did not re-derive
