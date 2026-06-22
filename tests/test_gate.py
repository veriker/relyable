"""test_gate.py — end-to-end enforcement against a real pytest project.

Stands up a tiny repo + honesty.toml, establishes a baseline from a green run,
then proves the gate's decisions: clean change passes; the lie (a failing test)
fails; shrinking the suite fails (no_shrink); newly skipping fails
(no_new_skip); a tampered config fails the anchor.
"""

from __future__ import annotations

import sys
from pathlib import Path

from relyable.verdicts.baseline import from_verdict, write_baseline
from relyable.verdicts.config import ConfigAnchorMismatch, compute_anchor, load_config
from relyable.verdicts.gate import evaluate

_HONESTY_TOML = """
[test]
command = ["{py}", "-m", "pytest", "-q", "--junitxml=report.xml"]
report_path = "report.xml"
max_reruns = 0

[baseline]
path = ".honesty/baseline.json"

[ratchets]
no_shrink = true
no_new_skip = true
"""

_GOOD_TESTS = """
def test_add():
    assert 1 + 1 == 2

def test_sub():
    assert 3 - 1 == 2

def test_mul():
    assert 2 * 2 == 4
"""


def _project(tmp_path: Path, tests_body: str) -> Path:
    ws = tmp_path
    (ws / "honesty.toml").write_text(
        _HONESTY_TOML.format(py=sys.executable), encoding="utf-8"
    )
    (ws / "test_suite.py").write_text(tests_body, encoding="utf-8")
    return ws


def _establish_baseline(ws: Path) -> None:
    """Run once green and snapshot it as the baseline (the human action)."""
    config = load_config(ws / "honesty.toml")
    result = evaluate(ws, config)
    assert result.run.ok, result.render()
    baseline = from_verdict(result.run.verdict, created_at="2026-06-14T00:00:00Z")
    write_baseline(ws / ".honesty" / "baseline.json", baseline)


def test_clean_change_passes(tmp_path):
    ws = _project(tmp_path, _GOOD_TESTS)
    _establish_baseline(ws)
    config = load_config(ws / "honesty.toml")
    result = evaluate(ws, config)
    assert result.ok, result.render()
    assert result.baseline_present


def test_the_lie_fails(tmp_path):
    ws = _project(tmp_path, _GOOD_TESTS)
    _establish_baseline(ws)
    (ws / "test_suite.py").write_text(
        _GOOD_TESTS + "\ndef test_broken():\n    assert False\n", encoding="utf-8"
    )
    result = evaluate(ws, load_config(ws / "honesty.toml"))
    assert not result.ok
    assert any("not green" in r for r in result.reasons), result.render()


def test_shrinking_the_suite_fails(tmp_path):
    ws = _project(tmp_path, _GOOD_TESTS)
    _establish_baseline(ws)
    # Delete two tests — suite still "passes" but the floor dropped.
    (ws / "test_suite.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )
    result = evaluate(ws, load_config(ws / "honesty.toml"))
    assert not result.ok
    assert any("no_shrink" in r for r in result.reasons), result.render()


def test_swap_real_test_for_trivial_one_fails(tmp_path):
    """Count unchanged, but a previously-passing id disappeared — the passing-id
    subset check (stricter than a count) must catch it."""
    ws = _project(tmp_path, _GOOD_TESTS)
    _establish_baseline(ws)
    swapped = (
        "def test_add():\n    assert 1 + 1 == 2\n"
        "def test_sub():\n    assert 3 - 1 == 2\n"
        "def test_trivial():\n    assert True\n"  # replaces test_mul
    )
    (ws / "test_suite.py").write_text(swapped, encoding="utf-8")
    result = evaluate(ws, load_config(ws / "honesty.toml"))
    assert not result.ok
    assert any("no_shrink" in r for r in result.reasons), result.render()


def test_new_skip_fails(tmp_path):
    ws = _project(tmp_path, _GOOD_TESTS)
    _establish_baseline(ws)
    skipped = _GOOD_TESTS.replace(
        "def test_mul():\n    assert 2 * 2 == 4",
        "import pytest\n@pytest.mark.skip(reason='gaming')\ndef test_mul():\n    assert 2 * 2 == 4",
    )
    (ws / "test_suite.py").write_text(skipped, encoding="utf-8")
    result = evaluate(ws, load_config(ws / "honesty.toml"))
    assert not result.ok
    assert any("no_new_skip" in r for r in result.reasons), result.render()


def test_first_run_without_baseline_is_inactive_not_blocking(tmp_path):
    ws = _project(tmp_path, _GOOD_TESTS)
    result = evaluate(ws, load_config(ws / "honesty.toml"))
    assert result.ok  # green, ratchets inactive (no baseline yet)
    assert not result.baseline_present
    assert all(r.inactive for r in result.ratchets)


def test_anchor_mismatch_fails_closed(tmp_path):
    ws = _project(tmp_path, _GOOD_TESTS)
    _establish_baseline(ws)
    config = load_config(ws / "honesty.toml")
    good_anchor = compute_anchor(
        config.config_path, (ws / config.baseline_path).resolve()
    )
    # Agent weakens the gate: edit honesty.toml after the anchor was pinned.
    (ws / "honesty.toml").write_text(
        _HONESTY_TOML.format(py=sys.executable).replace(
            "no_shrink = true", "no_shrink = false"
        ),
        encoding="utf-8",
    )
    tampered = load_config(ws / "honesty.toml")
    try:
        evaluate(ws, tampered, expected_anchor=good_anchor)
    except ConfigAnchorMismatch:
        return
    raise AssertionError("anchor mismatch must fail closed when config is tampered")
