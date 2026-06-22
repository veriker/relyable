"""property_grader (B1) — the T2 property-grader generator.

Two jobs here:
  1. BYTE-IDENTITY GUARD — the B1 refactor moved D's T0/T2 templates onto
     property_grader without changing a byte of what `relyable init` emits. The
     snapshots in tests/fixtures/scaffold_t{0,2}_*.snapshot.py were captured from
     the pre-refactor scaffold output; both the refactored scaffold AND
     make_property_grader(..., placeholders=True) must reproduce them exactly.
  2. The concrete (placeholders=False) graders compile, are stdlib-only, run as
     `python grader --bundle-dir B`, and enforce their property. determinism has no
     concrete mode (it is not provable); idempotence/round_trip have no placeholder
     template (concrete-only).
"""

from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path

import pytest

from relyable.skills.property_grader import (
    PROVABLE_KINDS,
    make_property_grader,
    property_predicate_source,
)
from relyable.skills.scaffold import Detection, make_scaffold_source

_FIXTURES = Path(__file__).parent / "fixtures"


def _stub(rung: str, fn: str = "f") -> Detection:
    return Detection(
        rung=rung, reason="", caveat="", auto_fillable=False, params={"contract_fn": fn}
    )


# --- byte-identity guard ----------------------------------------------------


@pytest.mark.parametrize(
    ("rung", "fn", "snapshot"),
    [
        ("T0", "double", "scaffold_t0_determinism.snapshot.py"),
        ("T2", "build", "scaffold_t2_schema.snapshot.py"),
    ],
)
def test_scaffold_output_byte_identical_to_pre_refactor(rung, fn, snapshot):
    expected = (_FIXTURES / snapshot).read_text(encoding="utf-8")
    assert make_scaffold_source(_stub(rung, fn)) == expected


def test_placeholders_mode_matches_scaffold():
    """make_property_grader(placeholders=True) IS what scaffold emits — the single
    source. (Guards against scaffold and property_grader drifting apart.)"""
    assert make_property_grader(
        "determinism", contract_fn="double", placeholders=True
    ) == make_scaffold_source(_stub("T0", "double"))
    assert make_property_grader(
        "schema_conformance", contract_fn="build", placeholders=True
    ) == make_scaffold_source(_stub("T2", "build"))


def test_empty_contract_fn_placeholder_fallback():
    src = make_property_grader("determinism", contract_fn="", placeholders=True)
    assert "CONTRACT_FN = 'REPLACE_WITH_CONTRACT_FN'" in src


# --- mode/kind guards -------------------------------------------------------


def test_determinism_has_no_concrete_mode():
    with pytest.raises(ValueError, match="not a provable property"):
        make_property_grader("determinism", contract_fn="f", placeholders=False)


@pytest.mark.parametrize("kind", ["idempotence", "round_trip"])
def test_concrete_only_kinds_have_no_placeholder(kind):
    with pytest.raises(ValueError, match="concrete-only"):
        make_property_grader(kind, contract_fn="f", placeholders=True)


def test_unknown_kind_rejected():
    with pytest.raises(ValueError, match="unknown property kind"):
        make_property_grader("telepathy", contract_fn="f")


def test_provable_set_excludes_determinism():
    assert "determinism" not in PROVABLE_KINDS
    assert set(PROVABLE_KINDS) == {"schema_conformance", "idempotence", "round_trip"}


def test_predicate_source_is_single_source():
    for kind in PROVABLE_KINDS:
        src = property_predicate_source(kind)
        assert "def property_holds(" in src
    assert "_conforms" in property_predicate_source("schema_conformance")


# --- concrete graders compile, stdlib-only, enforce the property ------------


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("round_trip", {"inverse": "decode", "inputs": [("hi",)]}),
        ("idempotence", {"inputs": [([3, 1, 2],)]}),
        ("schema_conformance", {"schema": {"type": "object"}, "inputs": [(5,)]}),
    ],
)
def test_concrete_compiles_and_stdlib_only(tmp_path, kind, params):
    src = make_property_grader(kind, contract_fn="forward", params=params)
    dest = tmp_path / "g.py"
    dest.write_text(src, encoding="utf-8")
    assert compileall.compile_file(str(dest), quiet=1)
    assert "import relyable" not in src and "import veriker" not in src
    assert "[SKILL_REDER_FAIL]" in src
    # the honest catch must be on the concrete grader surface (verbatim)
    assert "kills-mutants proves NON-VACUOUS, not correct-spec" in src


def _run_grader(tmp_path: Path, src: str, candidate_body: str, name: str):
    g = tmp_path / f"{name}.py"
    g.write_text(src, encoding="utf-8")
    bdir = tmp_path / f"bundle_{name}"
    (bdir / "skill").mkdir(parents=True)
    (bdir / "skill" / "candidate.py").write_text(candidate_body, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(g), "--bundle-dir", str(bdir)],
        capture_output=True,
        text=True,
    )


def test_round_trip_grader_admits_faithful_rejects_lossy(tmp_path):
    src = make_property_grader(
        "round_trip",
        contract_fn="encode",
        params={"inverse": "decode", "inputs": [("hello",), ("world",)]},
    )
    good = "def encode(s):\n    return s[::-1]\ndef decode(s):\n    return s[::-1]\n"
    lossy = "def encode(s):\n    return s.upper()\ndef decode(s):\n    return s\n"
    assert _run_grader(tmp_path, src, good, "rt_good").returncode == 0
    bad = _run_grader(tmp_path, src, lossy, "rt_bad")
    assert bad.returncode == 1 and "property violated" in bad.stderr


def test_idempotence_grader_admits_fixed_point_rejects_not(tmp_path):
    src = make_property_grader(
        "idempotence", contract_fn="norm", params={"inputs": [([3, 1, 2],)]}
    )
    assert (
        _run_grader(
            tmp_path, src, "def norm(x):\n    return sorted(x)\n", "id_g"
        ).returncode
        == 0
    )
    bad = _run_grader(tmp_path, src, "def norm(x):\n    return x[::-1]\n", "id_b")
    assert bad.returncode == 1


def test_schema_grader_admits_conforming_rejects_violation(tmp_path):
    src = make_property_grader(
        "schema_conformance",
        contract_fn="build",
        params={"schema": {"type": "object", "required": ["x"]}, "inputs": [(5,)]},
    )
    assert (
        _run_grader(
            tmp_path, src, "def build(n):\n    return {'x': n}\n", "sc_g"
        ).returncode
        == 0
    )
    bad = _run_grader(tmp_path, src, "def build(n):\n    return {'y': n}\n", "sc_b")
    assert bad.returncode == 1


def test_concrete_empty_inputs_fails_closed(tmp_path):
    src = make_property_grader("idempotence", contract_fn="f", params={"inputs": []})
    res = _run_grader(tmp_path, src, "def f(x):\n    return x\n", "empty")
    assert res.returncode == 1 and "no SAMPLE_INPUTS" in res.stderr
