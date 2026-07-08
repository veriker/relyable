"""relyable-skills CLI — exit-code + JSON contract over the fault matrix."""

from __future__ import annotations

import json
from pathlib import Path

import skills_fixtures as fixtures
from skills_fixtures import GRADER_SRC

from relyable.skills.cli import main


def _clean_registry(tmp_path) -> Path:
    """A registry of only re-deriving skills."""
    d = tmp_path / "reg"
    d.mkdir()
    for sid, kind, body in [
        ("merge_good", "merge", fixtures.MERGE_GOOD),
        ("parse_good", "parse", fixtures.PARSE_GOOD),
    ]:
        fixtures.build_skill_bundle(
            d / sid,
            skill_id=sid,
            kind=kind,
            body=body,
            claimed_verdict="VALIDATED",
            grader_src=GRADER_SRC,
        )
    return d


def test_cli_all_usable_exits_zero(tmp_path, capsys):
    d = _clean_registry(tmp_path)
    rc = main(["admit", str(d), "--grader", str(GRADER_SRC), "--run", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert set(out["usable"]) == {"merge_good", "parse_good"}


def test_cli_poisoned_registry_exits_nonzero(tmp_path, capsys):
    d = tmp_path / "poison"
    fixtures.build_poisoned_bundles(d)
    rc = main(["admit", str(d), "--grader", str(GRADER_SRC), "--run"])
    capsys.readouterr()
    assert rc == 1


def test_cli_wont_run_admits_nothing(tmp_path, capsys):
    d = _clean_registry(tmp_path)
    rc = main(["admit", str(d), "--grader", str(GRADER_SRC), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1  # nothing affirmatively re-derived -> fail-closed
    assert out["usable"] == []


def test_cli_bad_paths_exit_two(tmp_path, capsys):
    rc = main(["admit", str(tmp_path / "nope"), "--grader", str(GRADER_SRC)])
    capsys.readouterr()
    assert rc == 2
