"""test_diff_coverage.py — the added-line coverage ratchet against a REAL git repo.

The parsing legs (Cobertura + unified diff) run on fixtures; the integration legs
stand up an actual git repo in a temp dir (git is available), commit a base, add
lines, and prove the load-bearing behaviors:

  * an added line with no coverage FAILS the floor,
  * an added line that is covered PASSES,
  * a missing coverage report FAILS CLOSED (not inactive),
  * a non-git workspace FAILS CLOSED.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from relyable.verdicts.config import GateConfig
from relyable.verdicts.ratchets import RatchetContext
from relyable.verdicts.ratchets.diff_coverage import (
    DiffCoverage,
    _match_coverage,
    _parse_cobertura,
    _parse_unified_diff,
)
from relyable.verdicts.verdict import TestVerdict


def _config(**diff_params) -> GateConfig:
    return GateConfig(
        command=("true",),
        report_path="report.xml",
        baseline_path=".honesty/baseline.json",
        ratchets={"diff_coverage": {"enabled": True, **diff_params}},
        config_path=Path("honesty.toml"),
    )


def _ctx(workspace: Path, config: GateConfig) -> RatchetContext:
    return RatchetContext(
        workspace=workspace,
        verdict=TestVerdict.from_cases(()),
        baseline=None,
        config=config,
    )


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(workspace), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(workspace: Path) -> None:
    _git(workspace, "init", "-q", "-b", "main")
    _git(workspace, "config", "user.email", "t@example.com")
    _git(workspace, "config", "user.name", "t")
    _git(workspace, "config", "commit.gpgsign", "false")


def _commit_all(workspace: Path, message: str) -> None:
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", message)


def _cobertura(lines: dict[str, dict[int, int]]) -> str:
    """Build a minimal Cobertura XML. `lines` maps filename -> {line: hits}."""
    classes = []
    for fname, line_hits in lines.items():
        line_xml = "".join(
            f'<line number="{n}" hits="{h}"/>' for n, h in sorted(line_hits.items())
        )
        classes.append(f'<class filename="{fname}"><lines>{line_xml}</lines></class>')
    body = "".join(classes)
    return (
        '<?xml version="1.0" ?>'
        '<coverage line-rate="0.5" version="1.0">'
        f'<packages><package name="p"><classes>{body}</classes></package></packages>'
        "</coverage>"
    )


# ---------------------------------------------------------------------------
# unit: Cobertura parsing
# ---------------------------------------------------------------------------


def test_parse_cobertura_covered_and_coverable(tmp_path):
    xml = _cobertura({"pkg/foo.py": {1: 3, 2: 0, 5: 1}})
    p = tmp_path / "coverage.xml"
    p.write_text(xml, encoding="utf-8")
    parsed = _parse_cobertura(p)
    fc = parsed["pkg/foo.py"]
    assert fc.coverable == frozenset({1, 2, 5})
    assert fc.covered == frozenset({1, 5})


def test_parse_cobertura_refuses_doctype(tmp_path):
    p = tmp_path / "coverage.xml"
    p.write_text("<!DOCTYPE coverage>" + _cobertura({"a.py": {1: 1}}), encoding="utf-8")
    try:
        _parse_cobertura(p)
    except Exception as exc:  # noqa: BLE001
        assert "DOCTYPE" in str(exc)
    else:
        raise AssertionError("expected a parse error on DOCTYPE")


# ---------------------------------------------------------------------------
# unit: diff parsing + path matching
# ---------------------------------------------------------------------------


def test_parse_unified_diff_added_lines():
    diff = (
        "diff --git a/pkg/foo.py b/pkg/foo.py\n"
        "--- a/pkg/foo.py\n"
        "+++ b/pkg/foo.py\n"
        "@@ -10,0 +11,2 @@\n"
        "+new line a\n"
        "+new line b\n"
        "@@ -20,1 +22,1 @@\n"
        "-old\n"
        "+changed\n"
    )
    added = _parse_unified_diff(diff)
    assert added == {"pkg/foo.py": {11, 12, 22}}


def test_match_coverage_suffix():
    cov = ["relyable/foo.py", "relyable/bar.py"]
    assert _match_coverage("src/x/relyable/foo.py", cov) == "relyable/foo.py"
    assert _match_coverage("totally/unrelated.py", cov) is None


# ---------------------------------------------------------------------------
# integration: real git repo
# ---------------------------------------------------------------------------


def test_uncovered_added_line_fails(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "mod.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    # add two lines; cover neither
    (tmp_path / "mod.py").write_text(
        "def a():\n    return 1\ndef b():\n    return 2\n", encoding="utf-8"
    )
    (tmp_path / "coverage.xml").write_text(
        _cobertura({"mod.py": {1: 1, 2: 1, 3: 0, 4: 0}}), encoding="utf-8"
    )
    res = DiffCoverage().check(_ctx(tmp_path, _config(min_percent=90, base_ref="HEAD")))
    assert not res.ok
    assert "mod.py:3" in res.detail or "mod.py:4" in res.detail


def test_covered_added_line_passes(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "mod.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    (tmp_path / "mod.py").write_text(
        "def a():\n    return 1\ndef b():\n    return 2\n", encoding="utf-8"
    )
    (tmp_path / "coverage.xml").write_text(
        _cobertura({"mod.py": {1: 1, 2: 1, 3: 1, 4: 1}}), encoding="utf-8"
    )
    res = DiffCoverage().check(_ctx(tmp_path, _config(min_percent=90, base_ref="HEAD")))
    assert res.ok, res.detail


def test_missing_coverage_report_fails_closed(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    res = DiffCoverage().check(
        _ctx(tmp_path, _config(coverage_xml="nope.xml", base_ref="HEAD"))
    )
    assert not res.ok and not res.inactive
    assert "coverage report not found" in res.detail


def test_non_git_workspace_fails_closed(tmp_path):
    (tmp_path / "coverage.xml").write_text(
        _cobertura({"mod.py": {1: 1}}), encoding="utf-8"
    )
    res = DiffCoverage().check(_ctx(tmp_path, _config(base_ref="HEAD")))
    assert not res.ok and not res.inactive
    assert "git diff" in res.detail


def test_no_source_delta_passes(tmp_path):
    """A diff that adds only lines absent from the coverage report (e.g. a
    docs/non-source change) has no coverable delta and passes."""
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    _commit_all(tmp_path, "base")
    (tmp_path / "README.md").write_text("hello\nworld\n", encoding="utf-8")
    (tmp_path / "coverage.xml").write_text(
        _cobertura({"mod.py": {1: 1}}), encoding="utf-8"
    )
    res = DiffCoverage().check(_ctx(tmp_path, _config(base_ref="HEAD")))
    assert res.ok
    assert "no coverable lines added" in res.detail
