"""relyable-skills prove (B3) — the opt-in anti-vacuity CLI surface.

Always-run legs (no mutmut): spec resolution, determinism refusal, usage errors,
and that --help documents the spec. Two live legs (skipped without mutmut): a
round_trip spec certifies + writes the grader; a vacuous schema spec exits non-zero
with survivors and writes NO grader.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from relyable.skills.cli import _resolve_prove_spec, main


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


# --- spec resolution (pure, no mutmut) -------------------------------------


def test_resolve_round_trip_forward_inverse():
    kind, cf, params = _resolve_prove_spec(
        {"contract_fn": {"forward": "enc", "inverse": "dec"}, "inputs": [["a"]]},
        "round_trip",
    )
    assert kind == "round_trip" and cf == "enc" and params["inverse"] == "dec"


def test_resolve_schema_needs_contract_fn():
    with pytest.raises(ValueError, match="contract_fn"):
        _resolve_prove_spec({"kind": "schema_conformance", "inputs": [[1]]}, None)


def test_resolve_empty_inputs_rejected():
    with pytest.raises(ValueError, match="inputs"):
        _resolve_prove_spec(
            {"kind": "idempotence", "contract_fn": "f", "inputs": []}, None
        )


def test_resolve_kind_conflict_rejected():
    with pytest.raises(ValueError, match="conflicts"):
        _resolve_prove_spec(
            {"kind": "idempotence", "contract_fn": "f", "inputs": [[1]]}, "round_trip"
        )


# --- CLI usage / refusal (no mutmut) ---------------------------------------


def test_prove_determinism_refused(tmp_path, capsys):
    skill = _write(tmp_path / "s.py", "def f(n):\n    return n\n")
    spec = _write(
        tmp_path / "spec.json",
        json.dumps({"kind": "determinism", "contract_fn": "f", "inputs": [[1]]}),
    )
    rc = main(
        [
            "prove",
            str(skill),
            "--spec",
            str(spec),
            "--grader-out",
            str(tmp_path / "g.py"),
        ]
    )
    assert rc == 2
    assert "not a provable property" in capsys.readouterr().err
    assert not (tmp_path / "g.py").exists()


def test_prove_bad_spec_exits_two(tmp_path, capsys):
    skill = _write(tmp_path / "s.py", "def f(n):\n    return n\n")
    spec = _write(tmp_path / "spec.json", json.dumps({"inputs": []}))
    rc = main(
        [
            "prove",
            str(skill),
            "--kind",
            "idempotence",
            "--spec",
            str(spec),
            "--grader-out",
            str(tmp_path / "g.py"),
        ]
    )
    assert rc == 2 and "refused" in capsys.readouterr().err


def test_prove_missing_skill_exits_two(tmp_path, capsys):
    spec = _write(
        tmp_path / "spec.json",
        json.dumps({"kind": "idempotence", "contract_fn": "f", "inputs": [[1]]}),
    )
    rc = main(
        [
            "prove",
            str(tmp_path / "nope.py"),
            "--spec",
            str(spec),
            "--grader-out",
            str(tmp_path / "g.py"),
        ]
    )
    assert rc == 2


def test_prove_help_documents_spec(capsys):
    with pytest.raises(SystemExit):
        main(["prove", "--help"])
    assert "spec.json" in capsys.readouterr().out


# --- live: real mutmut (skipped if absent) ---------------------------------


@pytest.mark.skipif(shutil.which("mutmut") is None, reason="mutmut not installed")
def test_prove_round_trip_certifies_and_writes_grader(tmp_path, capsys):
    skill = _write(
        tmp_path / "codec.py",
        "def encode(n):\n    return n + 1\n\n\ndef decode(n):\n    return n - 1\n",
    )
    spec = _write(
        tmp_path / "spec.json",
        json.dumps(
            {
                "kind": "round_trip",
                "contract_fn": {"forward": "encode", "inverse": "decode"},
                "inputs": [[3], [7], [100]],
            }
        ),
    )
    grader = tmp_path / "codec_grader.py"
    rc = main(
        [
            "prove",
            str(skill),
            "--spec",
            str(spec),
            "--grader-out",
            str(grader),
            "--json",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True and out["killed"] == out["total"] and out["total"] > 0
    assert out["grader"] == str(grader) and grader.is_file()
    assert "kills-mutants proves NON-VACUOUS" in out["honest_catch"]


@pytest.mark.skipif(shutil.which("mutmut") is None, reason="mutmut not installed")
def test_prove_vacuous_property_exits_nonzero_no_grader(tmp_path, capsys):
    skill = _write(
        tmp_path / "shape.py", 'def build(n):\n    return {"x": n + 1, "y": n * 2}\n'
    )
    spec = _write(
        tmp_path / "spec.json",
        json.dumps(
            {
                "kind": "schema_conformance",
                "contract_fn": "build",
                "schema": {"type": "object"},
                "inputs": [[1], [5], [9]],
            }
        ),
    )
    grader = tmp_path / "shape_grader.py"
    rc = main(["prove", str(skill), "--spec", str(spec), "--grader-out", str(grader)])
    assert rc == 1
    assert "VACUOUS" in capsys.readouterr().out
    assert not grader.exists()  # a vacuous property yields no pinnable grader
