#!/usr/bin/env python3
"""SCAFFOLDED by relyable init — T0 determinism grader (CONFIRM before use).

Proves only that the candidate is REPRODUCIBLE: it runs CONTRACT_FN twice on each
fixed input and requires identical output. It does NOT prove correctness — a
wrong-but-deterministic candidate passes. Fill SAMPLE_INPUTS with representative
calls, then confirm this is the criterion you want (or graduate to a property
grader once an anti-vacuity proof is available). Stdlib only; no relyable/veriker
import (auditor-independence).
"""
CONTRACT_FN = 'double'
# FILL ME: representative calls; each item is the args tuple for one call,
# e.g. [("input one",), (42, 7)].
SAMPLE_INPUTS: list = []

import argparse
import ast
import json
import sys
from pathlib import Path


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    bundle = Path(ap.parse_args().bundle_dir)

    try:
        body = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    except OSError as e:
        return _fail(f"candidate_unreadable: {e}")
    try:
        ast.parse(body)
    except SyntaxError as e:
        return _fail(f"parse_fail: {e}")
    if not SAMPLE_INPUTS:
        return _fail("no SAMPLE_INPUTS — fill the scaffold before using this grader")

    ns: dict = {}
    try:
        exec(body, ns)  # noqa: S102 — bundle-code-exec; veriker's gated lane
    except Exception as e:  # noqa: BLE001
        return _fail(f"import_fail: {type(e).__name__}: {e}")
    fn = ns.get(CONTRACT_FN)
    if not callable(fn):
        return _fail(f"no_contract_fn: {CONTRACT_FN!r}")

    for i, call_args in enumerate(SAMPLE_INPUTS):
        try:
            # Fresh copies per call so the fn cannot couple the two runs via a
            # mutated shared argument.
            a = fn(*[json.loads(json.dumps(x)) for x in call_args])
            b = fn(*[json.loads(json.dumps(x)) for x in call_args])
        except Exception as e:  # noqa: BLE001
            return _fail(f"input[{i}] runtime_fail: {type(e).__name__}: {e}")
        if a != b:
            return _fail(f"input[{i}] nondeterministic: {a!r} != {b!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
