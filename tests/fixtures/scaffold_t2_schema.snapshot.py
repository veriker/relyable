#!/usr/bin/env python3
"""SCAFFOLDED by relyable init — T2 schema-conformance grader (CONFIRM before use).

Checks that the candidate's output CONFORMS to a schema over sample inputs. This is
an AUTHOR-PROPOSED property, so it is trustworthy ONLY once proven NON-VACUOUS — a
property no broken candidate can fail asserts nothing. The intended companion is an
anti-vacuity gate (mutate the candidate; the property must KILL the mutants). Until
that runs, treat this as a PROPOSAL: fill SAMPLE_INPUTS and review _conforms (a
minimal JSON-Schema-subset check is stubbed — swap in jsonschema/pydantic if your
consumer already uses one). Stdlib only; no relyable/veriker import.
"""
CONTRACT_FN = 'build'
# FILL ME: the schema the candidate's output must conform to.
SCHEMA: dict = {}
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


def _conforms(obj, schema: dict) -> bool:
    """Minimal JSON-Schema-subset structural check (type / required / properties).
    REPLACE with your consumer's real validator if it has one."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            return False
        for key in schema.get("required", []):
            if key not in obj:
                return False
        for key, sub in schema.get("properties", {}).items():
            if key in obj and not _conforms(obj[key], sub):
                return False
        return True
    if t == "array":
        if not isinstance(obj, list):
            return False
        item = schema.get("items")
        return item is None or all(_conforms(x, item) for x in obj)
    _PY = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
    if t in _PY:
        return isinstance(obj, _PY[t]) and not (t != "boolean" and isinstance(obj, bool))
    return True  # unconstrained type -> nothing to check


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
    if not SCHEMA:
        return _fail("empty SCHEMA — fill the scaffold before using this grader")

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
            got = fn(*[json.loads(json.dumps(x)) for x in call_args])
        except Exception as e:  # noqa: BLE001
            return _fail(f"input[{i}] runtime_fail: {type(e).__name__}: {e}")
        if not _conforms(got, SCHEMA):
            return _fail(f"input[{i}] output does not conform to SCHEMA: {got!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
