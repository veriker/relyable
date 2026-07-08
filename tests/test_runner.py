"""test_runner.py — the chokepoint, exercised against a REAL pytest run.

These tests stand up a tiny project in a temp dir and drive the runner exactly
as the gate would: a configured command writes a JUnit report, the runner reads
it. They prove the load-bearing anti-gaming behaviors: the agent's claim is
irrelevant, a stale report cannot ride green, flakiness is absorbed by the
gate-owned retry, and every could-not-conclude path fails closed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from relyable.verdicts.runner import run_suite

_REPORT = "report.xml"


def _pytest_cmd() -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", f"--junitxml={_REPORT}"]


def _write(ws: Path, name: str, body: str) -> None:
    (ws / name).write_text(body, encoding="utf-8")


def test_green_suite_runs_and_is_ok(tmp_path):
    _write(tmp_path, "test_ok.py", "def test_a():\n    assert 1 == 1\n")
    res = run_suite(tmp_path, _pytest_cmd(), _REPORT)
    assert res.ok
    assert res.verdict is not None and res.verdict.green
    assert res.verdict.passed == 1


def test_failing_suite_is_not_ok(tmp_path):
    _write(tmp_path, "test_bad.py", "def test_a():\n    assert 1 == 2\n")
    res = run_suite(tmp_path, _pytest_cmd(), _REPORT)
    assert not res.ok
    assert res.conclusive  # it DID conclude — conclusively red
    assert res.verdict is not None and res.verdict.failed == 1


def test_stale_report_cannot_ride_green(tmp_path):
    """Leave a green report in the tree but run a no-op command. The runner
    deletes the report first, so the no-op produces nothing -> fail closed."""
    _write(
        tmp_path,
        _REPORT,
        '<testsuite tests="1" failures="0" name="stale">'
        '<testcase classname="x" name="t"/></testsuite>',
    )
    noop = [sys.executable, "-c", "pass"]  # never writes the report
    res = run_suite(tmp_path, noop, _REPORT)
    assert not res.ok
    assert not res.conclusive
    assert "no report produced" in res.reason


def test_flaky_test_absorbed_by_reruns(tmp_path):
    """A test that fails on the first run and passes after, using a marker file
    to flip. With max_reruns>=1 the gate's best-of-N merge reports it passed and
    flags it flaky; with 0 reruns it would be red."""
    _write(
        tmp_path,
        "test_flaky.py",
        "from pathlib import Path\n"
        "def test_flaky():\n"
        "    m = Path('marker')\n"
        "    if not m.exists():\n"
        "        m.write_text('seen')\n"
        "        assert False, 'first run fails'\n"
        "    assert True\n",
    )
    strict = run_suite(tmp_path, _pytest_cmd(), _REPORT, max_reruns=0)
    assert not strict.ok  # strict: the first-run failure stands

    # reset marker for the rerun-tolerant attempt
    (tmp_path / "marker").unlink(missing_ok=True)
    tolerant = run_suite(tmp_path, _pytest_cmd(), _REPORT, max_reruns=2)
    assert tolerant.ok
    assert tolerant.flaky_ids  # reported as flaky, not silently swallowed


def test_malformed_report_fails_closed(tmp_path):
    """A command that writes garbage to the report path -> could-not-conclude."""
    _write(
        tmp_path,
        "conftest.py",
        "import pathlib\n"
        "def pytest_sessionfinish(session):\n"
        "    pathlib.Path('report.xml').write_text('NOT XML')\n",
    )
    _write(tmp_path, "test_ok.py", "def test_a():\n    assert True\n")
    res = run_suite(tmp_path, _pytest_cmd(), _REPORT)
    assert not res.ok
    assert not res.conclusive


def test_report_path_escape_refused(tmp_path):
    res = run_suite(tmp_path, [sys.executable, "-c", "pass"], "../escape.xml")
    assert not res.ok and not res.conclusive
    assert "outside the workspace" in res.reason
