"""relyable init (D) — detect the cheapest grader rung and scaffold it.

Two layers of coverage:
  1. detect_rung picks the right rung (T1 > T2 > T0 > T5) from a skill + repo.
  2. the scaffolded graders actually WORK end-to-end: a T1 scaffold admits a good
     candidate and rejects a wrong one through the full veriker path; a FILLED
     T0/T2/T5 template admits/rejects correctly; and — the honesty property — an
     UNFILLED template fails closed (never spuriously admits).
"""

from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path

import pytest

from relyable.skills import build_skill_bundle, rederive
from relyable.skills.scaffold import (
    detect_rung,
    make_scaffold_source,
    scaffold_grader,
)

# --- detection -------------------------------------------------------------


@pytest.fixture
def pytest_project(tmp_path) -> Path:
    """A repo with a pre-existing suite covering an in-repo skill module (T1)."""
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
    )
    (root / "conftest.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n",
        encoding="utf-8",
    )
    (root / "skill.py").write_text("def add(a, b):\n    return a + b\n", "utf-8")
    (root / "tests" / "test_contract.py").write_text(
        "from skill import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    return root


def test_detect_t1_pytest_layout(pytest_project):
    d = detect_rung(pytest_project / "skill.py")
    assert d.rung == "T1"
    assert d.auto_fillable is True
    assert d.params["target_path"] == "skill.py"
    assert d.params["test_cmd"][:3] == [sys.executable, "-m", "pytest"]


def test_detect_t2_schema(tmp_path):
    skill = tmp_path / "shape.py"
    skill.write_text(
        "SCHEMA = {'type': 'object', 'required': ['x']}\n\n"
        "def build(n):\n    return {'x': n}\n",
        encoding="utf-8",
    )
    d = detect_rung(skill)
    assert d.rung == "T2"
    assert d.auto_fillable is False
    assert d.params["contract_fn"] == "build"


def test_detect_t0_deterministic(tmp_path):
    skill = tmp_path / "pure.py"
    skill.write_text("def double(n):\n    return n * 2\n", encoding="utf-8")
    d = detect_rung(skill)
    assert d.rung == "T0"
    assert d.auto_fillable is False
    assert d.params["contract_fn"] == "double"


def test_nondeterministic_fn_is_not_t0(tmp_path):
    skill = tmp_path / "rng.py"
    skill.write_text(
        "import random\n\ndef roll():\n    return random.random()\n", "utf-8"
    )
    d = detect_rung(skill)
    assert d.rung == "T5"  # random import rules out T0; no schema/suite -> T5


def test_detect_t5_nothing(tmp_path):
    skill = tmp_path / "prose.py"
    skill.write_text("X = 1\n", encoding="utf-8")  # no contract fn, no schema, no suite
    d = detect_rung(skill)
    assert d.rung == "T5"


def test_t1_beats_schema(tmp_path):
    """A pre-existing suite wins even when a schema is also present."""
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_x.py").write_text(
        "def test_ok():\n    assert True\n", "utf-8"
    )
    skill = root / "skill.py"
    skill.write_text(
        "SCHEMA = {'type': 'object'}\n\ndef f(n):\n    return {'n': n}\n", "utf-8"
    )
    assert detect_rung(skill).rung == "T1"


# --- generated graders are valid + stdlib-only -----------------------------


def _stub_detection(rung, contract_fn="f"):
    from relyable.skills.scaffold import Detection

    return Detection(
        rung=rung,
        reason="",
        caveat="",
        auto_fillable=False,
        params={"contract_fn": contract_fn},
    )


@pytest.mark.parametrize("rung", ["T0", "T2", "T5"])
def test_template_compiles_and_is_stdlib_only(tmp_path, rung):
    src = make_scaffold_source(_stub_detection(rung))
    dest = tmp_path / "grader.py"
    dest.write_text(src, encoding="utf-8")
    assert compileall.compile_file(str(dest), quiet=1)
    assert "import relyable" not in src and "import veriker" not in src
    assert "FILL ME" in src and "[SKILL_REDER_FAIL]" in src


# --- T1 scaffold works end-to-end through veriker --------------------------


def test_t1_scaffold_admits_good_rejects_wrong(tmp_path, pytest_project):
    grader = tmp_path / "g.py"
    result = scaffold_grader(pytest_project / "skill.py", grader)
    assert result.rung == "T1" and result.auto_fillable

    def _verdict(body):
        bundle = build_skill_bundle(
            tmp_path / f"b_{hash(body) & 0xFFF}",
            skill_id="add",
            kind="arith",
            body=body,
            claimed_verdict="VALIDATED",
            grader_src=grader,
        )
        return rederive(bundle, grader_src=grader, permit_execution=True)

    assert _verdict("def add(a, b):\n    return a + b\n").verdict == "ADMIT"
    assert _verdict("def add(a, b):\n    return a - b\n").verdict == "REJECT"


# --- filled vs unfilled templates ------------------------------------------


def _admit_with_grader(tmp_path, grader: Path, body: str, *, name: str):
    bundle = build_skill_bundle(
        tmp_path / f"bundle_{name}",
        skill_id=name,
        kind="k",
        body=body,
        claimed_verdict="VALIDATED",
        grader_src=grader,
    )
    return rederive(bundle, grader_src=grader, permit_execution=True)


def test_unfilled_t0_fails_closed(tmp_path):
    """An unfilled scaffold (empty SAMPLE_INPUTS) must REJECT — never a spurious
    admit just because the template exists."""
    grader = tmp_path / "g0.py"
    grader.write_text(make_scaffold_source(_stub_detection("T0", "double")), "utf-8")
    v = _admit_with_grader(
        tmp_path, grader, "def double(n):\n    return n * 2\n", name="u0"
    )
    assert v.verdict == "REJECT"


def test_filled_t0_admits_deterministic_rejects_rng(tmp_path):
    grader = tmp_path / "g0.py"
    src = make_scaffold_source(_stub_detection("T0", "double")).replace(
        "SAMPLE_INPUTS: list = []", "SAMPLE_INPUTS: list = [(3,), (10,)]"
    )
    grader.write_text(src, encoding="utf-8")
    ok = _admit_with_grader(
        tmp_path, grader, "def double(n):\n    return n * 2\n", name="d0"
    )
    assert ok.verdict == "ADMIT"
    rng = _admit_with_grader(
        tmp_path,
        grader,
        "import random\n\ndef double(n):\n    return n * 2 + random.random()\n",
        name="r0",
    )
    assert rng.verdict == "REJECT"


def test_filled_t2_admits_conforming_rejects_violation(tmp_path):
    grader = tmp_path / "g2.py"
    src = (
        make_scaffold_source(_stub_detection("T2", "build"))
        .replace(
            "SCHEMA: dict = {}", "SCHEMA: dict = {'type': 'object', 'required': ['x']}"
        )
        .replace("SAMPLE_INPUTS: list = []", "SAMPLE_INPUTS: list = [(5,)]")
    )
    grader.write_text(src, encoding="utf-8")
    ok = _admit_with_grader(
        tmp_path, grader, "def build(n):\n    return {'x': n}\n", name="c2"
    )
    assert ok.verdict == "ADMIT"
    bad = _admit_with_grader(
        tmp_path, grader, "def build(n):\n    return {'y': n}\n", name="v2"
    )
    assert bad.verdict == "REJECT"


def test_filled_t5_admits_matching_rejects_divergent(tmp_path):
    grader = tmp_path / "g5.py"
    src = (
        make_scaffold_source(_stub_detection("T5", "square"))
        .replace(
            'raise NotImplementedError("fill reference() before using this grader")',
            "return call_args[0] ** 2",
        )
        .replace("HOLDOUTS: list = []", "HOLDOUTS: list = [(4,), (9,)]")
    )
    grader.write_text(src, encoding="utf-8")
    ok = _admit_with_grader(
        tmp_path, grader, "def square(n):\n    return n * n\n", name="m5"
    )
    assert ok.verdict == "ADMIT"
    bad = _admit_with_grader(
        tmp_path, grader, "def square(n):\n    return n + n\n", name="x5"
    )
    assert bad.verdict == "REJECT"


# --- CLI ------------------------------------------------------------------


def test_cli_init_t1_with_smoke(tmp_path, pytest_project, capsys):
    from relyable.skills.cli import main

    out = tmp_path / "cli_grader.py"
    rc = main(["init", str(pytest_project / "skill.py"), "--out", str(out), "--smoke"])
    assert rc == 0
    assert out.is_file()
    captured = capsys.readouterr().out
    assert "rung T1" in captured and "smoke" in captured


def test_cli_init_json_template(tmp_path, capsys):
    from relyable.skills.cli import main

    skill = tmp_path / "pure.py"
    skill.write_text("def double(n):\n    return n * 2\n", encoding="utf-8")
    out = tmp_path / "g.py"
    rc = main(["init", str(skill), "--out", str(out), "--json"])
    assert rc == 0
    import json

    data = json.loads(capsys.readouterr().out)
    assert data["rung"] == "T0"
    assert data["auto_fillable"] is False


def test_generated_t1_grader_runs_directly(tmp_path, pytest_project):
    """The T1 grader is a self-contained CLI: `python grader --bundle-dir B`."""
    grader = tmp_path / "g.py"
    scaffold_grader(pytest_project / "skill.py", grader)
    bundle = build_skill_bundle(
        tmp_path / "bundle",
        skill_id="add",
        kind="arith",
        body="def add(a, b):\n    return a + b\n",
        claimed_verdict="VALIDATED",
        grader_src=grader,
    )
    proc = subprocess.run(
        [sys.executable, str(grader), "--bundle-dir", str(bundle)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
