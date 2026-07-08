"""verdict-as-grader (T1) — grade a skill by running the consumer's OWN suite.

These drive the generated grader through the FULL relyable path: build a real
veriker bundle around a candidate, pin the generated grader, and re-derive via
``rederive`` (permit_execution=True). The fixture is a tiny project that already
has a pytest suite; the grader drops the candidate into place and runs that suite.
The agent never authored the suite — it is the consumer's pre-existing ground
truth, which is the whole point of the T1 rung.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from relyable.skills import build_skill_bundle, rederive
from relyable.skills.verdict_grader import make_verdict_grader, write_verdict_grader

TARGET = "skill_under_test.py"
# Absolute interpreter so the nested suite runs under this venv (which has pytest),
# regardless of how veriker launches the grader pack.
TEST_CMD = [sys.executable, "-m", "pytest", "-q"]

GOOD = "def add(a, b):\n    return a + b\n"
WRONG = "def add(a, b):\n    return a - b\n"  # passes import, fails the assertions
MISSING = "def subtract(a, b):\n    return a - b\n"  # no `add` -> suite import error
SYNTAX = "def add(a, b)\n    return a + b\n"  # SyntaxError -> grader fails closed


@pytest.fixture
def project(tmp_path) -> Path:
    """A consumer project that ALREADY has a suite for the skill's contract."""
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "conftest.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n",
        encoding="utf-8",
    )
    # The target the suite imports — a placeholder the candidate overwrites.
    (root / TARGET).write_text(
        "def add(a, b):\n    raise NotImplementedError\n", "utf-8"
    )
    (root / "tests" / "test_contract.py").write_text(
        "from skill_under_test import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n"
        "def test_zero():\n    assert add(0, 0) == 0\n",
        encoding="utf-8",
    )
    return root


def _grader(tmp_path, project, *, isolate=True) -> Path:
    return write_verdict_grader(
        tmp_path / "verdict_grader.py",
        project_root=str(project),
        target_path=TARGET,
        test_cmd=TEST_CMD,
        isolate=isolate,
    )


def _admit(tmp_path, project, body, *, isolate=True):
    grader = _grader(tmp_path, project, isolate=isolate)
    bundle = build_skill_bundle(
        tmp_path / "bundle",
        skill_id="add",
        kind="arith",
        body=body,
        claimed_verdict="VALIDATED",
        grader_src=grader,
    )
    return rederive(bundle, grader_src=grader, permit_execution=True)


def test_correct_candidate_admitted(tmp_path, project):
    v = _admit(tmp_path, project, GOOD)
    assert v.verdict == "ADMIT"
    assert v.reason_code == "RE_DERIVED"


def test_wrong_candidate_rejected(tmp_path, project):
    """The candidate imports fine but fails the consumer's assertions -> the suite
    exits non-zero -> veriker returns a re-derivation mismatch -> REJECT."""
    v = _admit(tmp_path, project, WRONG)
    assert v.verdict == "REJECT"
    assert v.rederived_label == "REJECTED"


def test_missing_contract_rejected(tmp_path, project):
    """No `add` symbol -> the suite errors on import -> REJECT."""
    v = _admit(tmp_path, project, MISSING)
    assert v.verdict == "REJECT"


def test_syntactically_broken_candidate_rejected(tmp_path, project):
    v = _admit(tmp_path, project, SYNTAX)
    assert v.verdict == "REJECT"


def test_isolate_does_not_mutate_live_tree(tmp_path, project):
    """With isolate=True (default) the candidate runs in a throwaway copy, so the
    consumer's real target file is never touched — even by an admitted skill."""
    before = (project / TARGET).read_text(encoding="utf-8")
    v = _admit(tmp_path, project, GOOD)
    assert v.verdict == "ADMIT"
    assert (project / TARGET).read_text(encoding="utf-8") == before


def test_in_place_mode_restores_target(tmp_path, project):
    """With isolate=False the grader snapshots-restores the target file, so the live
    tree is back to its original bytes after the run regardless of outcome."""
    before = (project / TARGET).read_text(encoding="utf-8")
    v = _admit(tmp_path, project, WRONG, isolate=False)
    assert v.verdict == "REJECT"
    assert (project / TARGET).read_text(encoding="utf-8") == before


def test_test_cmd_is_consumer_authority_not_meta(tmp_path, project):
    """A producer cannot redirect the suite: the test command is baked into the
    grader as a literal, not read from the (producer-supplied) bundle meta. A bundle
    carrying a meta that names a bogus 'exit 0' command still runs the real suite."""
    grader = _grader(tmp_path, project)
    bundle = build_skill_bundle(
        tmp_path / "bundle",
        skill_id="add",
        kind="arith",
        body=WRONG,
        claimed_verdict="VALIDATED",
        grader_src=grader,
    )
    # Inject a hostile meta key naming a pass-everything command (post-build; the
    # manifest still binds meta.json's digest, but the grader ignores meta entirely).
    import json

    meta_path = bundle / "skill" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["test_cmd"] = ["true"]
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    # Re-point the digest so the bundle is internally consistent (the attack is
    # "honest bundle, hostile meta field", not a tamper of the candidate).
    from relyable.gate import file_digest

    man_path = bundle / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["files"]["skill/meta.json"] = file_digest(meta_path)
    man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")

    v = rederive(bundle, grader_src=grader, permit_execution=True)
    assert v.verdict == "REJECT"  # the real suite ran and the WRONG body failed it


def test_make_and_write_agree(tmp_path, project):
    src = make_verdict_grader(
        project_root=str(project), target_path=TARGET, test_cmd=TEST_CMD
    )
    written = _grader(tmp_path, project).read_text(encoding="utf-8")
    assert src == written
    assert "GENERATED by relyable.skills.verdict_grader" in src
    assert "import relyable" not in src and "import veriker" not in src  # stdlib only


def test_rejects_absolute_or_escaping_target():
    for bad in ("/etc/passwd", "../escape.py", ""):
        with pytest.raises(ValueError):
            make_verdict_grader(project_root="/x", target_path=bad, test_cmd=["true"])
