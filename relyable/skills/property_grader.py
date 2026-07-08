"""property_grader.py — the T2 (author-proposed property) grader generator.

A code skill rarely ships held-out goldens (the ``interval_grader`` T1 shape), but
its author CAN propose a structural PROPERTY the output must satisfy — round-trip,
idempotence, schema-conformance. A property an author proposes is only a trust root
once proven NON-VACUOUS: a property no broken candidate can fail asserts nothing.

HONEST CATCH (the one that must appear on every B surface): kills-mutants proves
NON-VACUOUS, not correct-spec. It's an anti-vacuity gate, not a correctness oracle
(the property is anchored to the candidate-at-proposal-time as pseudo-ground-truth).
T2 stays genuinely weaker than T1.

This module is the single source of two things:

  * ``make_property_grader(kind, ...)`` — emits a stdlib-only grader (no relyable /
    veriker import; auditor-independence) in two modes:
      - ``placeholders=True``  : the FILL-ME *confirm-by-hand* templates that
        ``relyable init`` (scaffold.py) scaffolds for the T0 (determinism) and T2
        (schema-conformance) rungs. These are byte-identical to what D shipped.
      - ``placeholders=False`` : a *concrete* grader with agent-supplied literals
        baked in, the form B's ``prove`` certifies and pins.
  * ``property_predicate_source(kind)`` — the per-kind predicate function source,
    embedded in BOTH the concrete grader and B's synthesized anti-vacuity test, so
    "what B proves" is exactly "what the grader checks".

Kinds: ``determinism``, ``schema_conformance``, ``idempotence``, ``round_trip``.
``determinism`` is a confirm-by-hand template ONLY — it is NOT provable (it
near-universally survives mutation, since a wrong-but-deterministic mutant still
satisfies ``f(x) == f(x)``), so it has no concrete mode.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# D's confirm-by-hand templates (T0 determinism / T2 schema-conformance).
# MOVED here UNCHANGED from scaffold.py: placeholders=True must stay byte-identical
# to what `relyable init` already shipped. Do not edit these constants.
# ---------------------------------------------------------------------------

_T0_PREAMBLE = '''#!/usr/bin/env python3
"""SCAFFOLDED by relyable init — T0 determinism grader (CONFIRM before use).

Proves only that the candidate is REPRODUCIBLE: it runs CONTRACT_FN twice on each
fixed input and requires identical output. It does NOT prove correctness — a
wrong-but-deterministic candidate passes. Fill SAMPLE_INPUTS with representative
calls, then confirm this is the criterion you want (or graduate to a property
grader once an anti-vacuity proof is available). Stdlib only; no relyable/veriker
import (auditor-independence).
"""
'''

_T0_BODY = """
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
"""

_T2_PREAMBLE = '''#!/usr/bin/env python3
"""SCAFFOLDED by relyable init — T2 schema-conformance grader (CONFIRM before use).

Checks that the candidate's output CONFORMS to a schema over sample inputs. This is
an AUTHOR-PROPOSED property, so it is trustworthy ONLY once proven NON-VACUOUS — a
property no broken candidate can fail asserts nothing. The intended companion is an
anti-vacuity gate (mutate the candidate; the property must KILL the mutants). Until
that runs, treat this as a PROPOSAL: fill SAMPLE_INPUTS and review _conforms (a
minimal JSON-Schema-subset check is stubbed — swap in jsonschema/pydantic if your
consumer already uses one). Stdlib only; no relyable/veriker import.
"""
'''

_T2_BODY = '''
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
'''

# Kinds that have a confirm-by-hand (placeholders=True) template. determinism maps
# to the T0 template, schema_conformance to the T2 template; idempotence/round_trip
# are concrete-only (no FILL-ME scaffold — they are proposed with literals).
_PLACEHOLDER_TEMPLATES = {
    "determinism": (_T0_PREAMBLE, _T0_BODY),
    "schema_conformance": (_T2_PREAMBLE, _T2_BODY),
}


def _placeholder_header(kind: str, contract_fn: str) -> str:
    """Replicate scaffold.py's ``_header`` for the T0/T2 rungs, byte-for-byte, so a
    placeholders=True grader is identical to what ``relyable init`` shipped."""
    fn = contract_fn or "REPLACE_WITH_CONTRACT_FN"
    lines = [f"CONTRACT_FN = {fn!r}\n"]
    if kind == "schema_conformance":
        lines.append("# FILL ME: the schema the candidate's output must conform to.\n")
        lines.append("SCHEMA: dict = {}\n")
    lines.append(
        "# FILL ME: representative calls; each item is the args tuple for one call,\n"
        '# e.g. [("input one",), (42, 7)].\n'
    )
    lines.append("SAMPLE_INPUTS: list = []\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# per-kind property predicate (single source of truth: grader + anti-vacuity test)
# ---------------------------------------------------------------------------

# Each constant defines ``property_holds(fn, inverse, schema, call_args) -> bool``
# (uniform signature; a kind ignores the args it does not need). schema_conformance
# also defines ``_conforms``. Embedded verbatim in BOTH the concrete grader and B's
# synthesized test so the mutation run proves exactly the predicate the grader runs.

_PRED_DETERMINISM = '''
def property_holds(fn, inverse, schema, call_args):
    """Determinism: f(x) == f(x). Near-universally survives mutation (a
    wrong-but-deterministic mutant still passes), so it is NOT in the provable set."""
    return fn(*call_args) == fn(*call_args)
'''

_PRED_SCHEMA = '''
def _conforms(obj, schema):
    """Minimal JSON-Schema-subset structural check (type / required / properties)."""
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
    return True


def property_holds(fn, inverse, schema, call_args):
    """Schema-conformance: the candidate's output structurally conforms to SCHEMA.
    PARTIAL — mutants that keep the output's shape survive (listed on the cert)."""
    return _conforms(fn(*call_args), schema)
'''

_PRED_IDEMPOTENCE = '''
def property_holds(fn, inverse, schema, call_args):
    """Idempotence: f(f(x)) == f(x). PARTIAL — mutants that preserve the fixed point
    survive (listed on the cert)."""
    once = fn(*call_args)
    return fn(once) == once
'''

_PRED_ROUND_TRIP = '''
def property_holds(fn, inverse, schema, call_args):
    """Round-trip: inverse(forward(x)) == x. forward = the contract fn, inverse = its
    declared inverse. STRONG — a faithful round-trip kills nearly every mutant."""
    encoded = fn(*call_args)
    original = call_args[0] if len(call_args) == 1 else list(call_args)
    return inverse(encoded) == original
'''

_PREDICATES = {
    "determinism": _PRED_DETERMINISM,
    "schema_conformance": _PRED_SCHEMA,
    "idempotence": _PRED_IDEMPOTENCE,
    "round_trip": _PRED_ROUND_TRIP,
}

#: Kinds B's anti-vacuity gate can certify. ``determinism`` is excluded by design.
PROVABLE_KINDS = ("schema_conformance", "idempotence", "round_trip")


def property_predicate_source(kind: str) -> str:
    """Return the source of ``property_holds`` (+ any helper) for ``kind``. This is
    the single source shared by the concrete grader and the anti-vacuity test."""
    try:
        return _PREDICATES[kind]
    except KeyError:
        raise ValueError(
            f"unknown property kind {kind!r}; known: {sorted(_PREDICATES)}"
        ) from None


# ---------------------------------------------------------------------------
# concrete (placeholders=False) grader — agent-supplied literals baked in
# ---------------------------------------------------------------------------

_CONCRETE_PREAMBLE = '''#!/usr/bin/env python3
"""GENERATED by relyable.skills.property_grader — a CONCRETE property grader.

Re-derives a candidate by checking an author-proposed PROPERTY (KIND below) over
baked sample inputs. The same predicate, the same inputs, are what B's anti-vacuity
gate mutated the reference candidate against — so a pinned certificate attests this
property is NON-VACUOUS for that reference.

HONEST CATCH: kills-mutants proves NON-VACUOUS, not correct-spec. It's an
anti-vacuity gate, not a correctness oracle (the property is anchored to the
candidate-at-proposal-time as pseudo-ground-truth). T2 stays genuinely weaker than
T1. Stdlib only; no relyable/veriker import (auditor-independence).
"""
'''

_CONCRETE_BODY = """
import argparse
import ast
import json
import sys
from pathlib import Path


def _copy(x):
    return json.loads(json.dumps(x))


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
        return _fail("no SAMPLE_INPUTS baked into this grader")

    ns: dict = {}
    try:
        exec(body, ns)  # noqa: S102 — bundle-code-exec; veriker's gated lane
    except Exception as e:  # noqa: BLE001
        return _fail(f"import_fail: {type(e).__name__}: {e}")
    fn = ns.get(CONTRACT_FN)
    if not callable(fn):
        return _fail(f"no_contract_fn: {CONTRACT_FN!r}")
    inverse = ns.get(INVERSE_FN) if INVERSE_FN else None
    if INVERSE_FN and not callable(inverse):
        return _fail(f"no_inverse_fn: {INVERSE_FN!r}")

    for i, call_args in enumerate(SAMPLE_INPUTS):
        try:
            ok = property_holds(fn, inverse, SCHEMA, [_copy(x) for x in call_args])
        except Exception as e:  # noqa: BLE001
            return _fail(f"input[{i}] runtime_fail: {type(e).__name__}: {e}")
        if not ok:
            return _fail(f"input[{i}] property violated (kind={KIND})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""

# A tiny _fail shared by the concrete body; defined separately so it sits ABOVE the
# embedded predicate source (which may reference nothing else).
_CONCRETE_FAIL = """

def _fail(msg: str) -> int:
    import sys
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1
"""


def _concrete_header(kind: str, contract_fn: str, params: dict) -> str:
    inverse = str(params.get("inverse", "")) if kind == "round_trip" else ""
    schema = params.get("schema", {})
    sample_inputs = list(params.get("inputs", params.get("sample_inputs", [])))
    return (
        "KIND = %r\n"
        "CONTRACT_FN = %r\n"
        "INVERSE_FN = %r\n"
        "SCHEMA = %r\n"
        "SAMPLE_INPUTS = %r\n"
    ) % (str(kind), str(contract_fn), inverse, schema, sample_inputs)


def make_property_grader(
    kind: str,
    *,
    contract_fn: str,
    params: dict | None = None,
    placeholders: bool = False,
) -> str:
    """Return the SOURCE of a stdlib-only property grader for ``kind``.

    ``placeholders=True`` returns D's confirm-by-hand FILL-ME template (only for
    ``determinism`` / ``schema_conformance``), byte-identical to what ``relyable
    init`` ships. ``placeholders=False`` bakes the agent-supplied literals in
    ``params`` (``inputs`` / ``schema`` / ``inverse``) into a concrete grader — the
    form B's ``prove`` certifies. ``determinism`` has no concrete mode (it is not
    provable; see the honest catch in the module docstring)."""
    params = params or {}
    if kind not in _PREDICATES:
        raise ValueError(
            f"unknown property kind {kind!r}; known: {sorted(_PREDICATES)}"
        )
    if placeholders:
        tmpl = _PLACEHOLDER_TEMPLATES.get(kind)
        if tmpl is None:
            raise ValueError(
                f"no confirm-by-hand template for kind {kind!r}; placeholders mode is "
                "only for determinism / schema_conformance (idempotence / round_trip "
                "are concrete-only)"
            )
        preamble, body = tmpl
        return preamble + _placeholder_header(kind, contract_fn) + body

    if kind == "determinism":
        raise ValueError(
            "determinism is not a provable property — it near-universally survives "
            "mutation (a wrong-but-deterministic mutant still passes f(x)==f(x)); it "
            "stays a confirm-by-hand T0 template (use placeholders=True)"
        )
    header = _concrete_header(kind, contract_fn, params)
    return (
        _CONCRETE_PREAMBLE
        + header
        + _CONCRETE_FAIL
        + property_predicate_source(kind)
        + _CONCRETE_BODY
    )
