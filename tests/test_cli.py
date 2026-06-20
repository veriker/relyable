"""test_cli.py — the CI surface: run / baseline / anchor exit codes + JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from relyable.verdicts.cli import main

_TOML = """
[test]
command = ["{py}", "-m", "pytest", "-q", "--junitxml=report.xml"]
report_path = "report.xml"
[baseline]
path = ".honesty/baseline.json"
[ratchets]
no_shrink = true
no_new_skip = true
"""

_TESTS = "def test_a():\n    assert True\ndef test_b():\n    assert True\n"


def _project(tmp_path: Path, body: str = _TESTS) -> Path:
    (tmp_path / "honesty.toml").write_text(
        _TOML.format(py=sys.executable), encoding="utf-8"
    )
    (tmp_path / "test_suite.py").write_text(body, encoding="utf-8")
    return tmp_path


def _argv(ws: Path, *rest: str) -> list[str]:
    return ["--config", str(ws / "honesty.toml"), "--workspace", str(ws), *rest]


def test_baseline_then_run_passes(tmp_path, capsys):
    ws = _project(tmp_path)
    assert main(_argv(ws, "baseline")) == 0
    out = capsys.readouterr().out
    assert "baseline written" in out and "HONESTY_ANCHOR" in out
    assert main(_argv(ws, "run")) == 0


def test_run_json_shape(tmp_path, capsys):
    ws = _project(tmp_path)
    main(_argv(ws, "baseline"))
    capsys.readouterr()
    rc = main(_argv(ws, "run", "--json"))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["verdict"]["green"] is True
    assert {r["name"] for r in payload["ratchets"]} == {"no_shrink", "no_new_skip"}


def test_run_fails_on_shrink(tmp_path, capsys):
    ws = _project(tmp_path)
    main(_argv(ws, "baseline"))
    (ws / "test_suite.py").write_text(
        "def test_a():\n    assert True\n", encoding="utf-8"
    )
    assert main(_argv(ws, "run")) == 1


def test_baseline_refuses_red_suite(tmp_path, capsys):
    ws = _project(tmp_path, "def test_a():\n    assert False\n")
    assert main(_argv(ws, "baseline")) == 1
    assert "refusing to baseline" in capsys.readouterr().err


def test_anchor_command_matches_run_enforcement(tmp_path, capsys):
    ws = _project(tmp_path)
    main(_argv(ws, "baseline"))
    capsys.readouterr()
    assert main(_argv(ws, "anchor")) == 0
    anchor = capsys.readouterr().out.strip()
    assert len(anchor) == 64  # sha256 hex
    # Correct anchor -> pass.
    assert main(_argv(ws, "run", "--anchor", anchor)) == 0
    # Tamper the config -> anchor enforcement fails the run.
    cfg = (ws / "honesty.toml").read_text()
    (ws / "honesty.toml").write_text(
        cfg.replace("no_shrink = true", "no_shrink = false")
    )
    assert main(_argv(ws, "run", "--anchor", anchor)) == 1
