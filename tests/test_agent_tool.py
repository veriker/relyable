"""test_agent_tool.py — the harness-agnostic agent tool: never raises into the
agent, and the `claim` never asserts passing tests it didn't observe."""

from __future__ import annotations

import sys
from pathlib import Path

from relyable.verdicts import agent_tool
from relyable.verdicts.baseline import from_verdict, write_baseline
from relyable.verdicts.config import compute_anchor, load_config
from relyable.verdicts.gate import evaluate

_TOML = """
[test]
command = ["{py}", "-m", "pytest", "-q", "--junitxml=report.xml"]
report_path = "report.xml"
[baseline]
path = ".honesty/baseline.json"
[ratchets]
no_shrink = true
"""


def _project(tmp_path: Path, body: str) -> Path:
    (tmp_path / "honesty.toml").write_text(
        _TOML.format(py=sys.executable), encoding="utf-8"
    )
    (tmp_path / "test_suite.py").write_text(body, encoding="utf-8")
    return tmp_path


def _baseline(ws: Path) -> None:
    cfg = load_config(ws / "honesty.toml")
    r = evaluate(ws, cfg)
    write_baseline(
        ws / ".honesty" / "baseline.json", from_verdict(r.run.verdict, created_at="t")
    )


def test_green_claim_is_pass(tmp_path):
    ws = _project(tmp_path, "def test_a():\n    assert True\n")
    _baseline(ws)
    out = agent_tool.run_tests(ws, ws / "honesty.toml")
    assert out["ok"] is True
    assert "PASS" in out["claim"] and "[gate-verified]" in out["claim"]


def test_failing_claim_never_says_pass(tmp_path):
    ws = _project(tmp_path, "def test_a():\n    assert False\n")
    out = agent_tool.run_tests(ws, ws / "honesty.toml")
    assert out["ok"] is False
    assert "FAIL" in out["claim"]
    assert "all pass" not in out["claim"].lower()


def test_bad_config_returns_structured_not_raises(tmp_path):
    out = agent_tool.run_tests(tmp_path, tmp_path / "nope.toml")
    assert out["ok"] is False and out["error"] == "config_error"
    assert "not known to pass" in out["claim"]


def test_anchor_mismatch_surfaced_as_refusal(tmp_path):
    ws = _project(tmp_path, "def test_a():\n    assert True\n")
    _baseline(ws)
    cfg = load_config(ws / "honesty.toml")
    good = compute_anchor(cfg.config_path, (ws / cfg.baseline_path).resolve())
    (ws / "honesty.toml").write_text(
        _TOML.format(py=sys.executable).replace("no_shrink = true", "no_shrink = false")
    )
    out = agent_tool.run_tests(ws, ws / "honesty.toml", expected_anchor=good)
    assert out["ok"] is False and out["error"] == "anchor_mismatch"
    assert "weakened" in out["claim"].lower() or "REFUSED" in out["claim"]


def test_gamed_suite_claim_flags_ratchets(tmp_path):
    ws = _project(
        tmp_path, "def test_a():\n    assert True\ndef test_b():\n    assert True\n"
    )
    _baseline(ws)
    (ws / "test_suite.py").write_text(
        "def test_a():\n    assert True\n", encoding="utf-8"
    )
    out = agent_tool.run_tests(ws, ws / "honesty.toml")
    assert out["ok"] is False
    assert "ratchets failed" in out["claim"] and "no_shrink" in out["claim"]
