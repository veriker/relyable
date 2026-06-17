"""test_mutation.py — the mutation ratchet.

Two layers, mirroring how test_runner.py separates parse-from-fixture and
drive-the-real-tool:

  * parser legs run against RECORDED reports (a real mutmut 3.6 `results --all
    true` capture and a faithful Stryker mutation-testing-elements JSON), so they
    need no engine installed;
  * the ratchet's compare + fail-closed logic is driven through a fake adapter,
    so it is deterministic without an engine;
  * ONE integration leg drives REAL mutmut on a tiny project (skipped when mutmut
    is absent) and proves a deleted-assertion suite leaves a survivor.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from relyable.verdicts.config import GateConfig
from relyable.verdicts.ratchets import RatchetContext
from relyable.verdicts.ratchets import mutation as mut
from relyable.verdicts.ratchets.mutation import (
    MutationEngineError,
    MutationReport,
    parse_mutmut_results,
    parse_stryker_json,
)
from relyable.verdicts.verdict import TestVerdict

_FIXTURES = Path(__file__).parent / "fixtures"


def _config(**params) -> GateConfig:
    return GateConfig(
        command=("true",),
        report_path="report.xml",
        baseline_path=".honesty/baseline.json",
        ratchets={"mutation": {"enabled": True, **params}},
        config_path=Path("honesty.toml"),
    )


def _ctx(workspace: Path, config: GateConfig) -> RatchetContext:
    return RatchetContext(
        workspace=workspace,
        verdict=TestVerdict.from_cases(()),
        baseline=None,
        config=config,
    )


# ---------------------------------------------------------------------------
# parsers (recorded fixtures)
# ---------------------------------------------------------------------------


def test_parse_mutmut_results_fixture():
    report = parse_mutmut_results((_FIXTURES / "mutmut_results.txt").read_text())
    assert report.total == 3
    assert report.killed == 1
    assert report.survived == 2
    assert report.surviving == (
        "target.x_is_positive__mutmut_1",
        "target.x_is_positive__mutmut_2",
    )


def test_parse_mutmut_results_ignores_noise():
    text = (
        "UserWarning: The config paths_to_mutate is deprecated\n"
        "    target.x__mutmut_1: killed\n"
        "    target.x__mutmut_2: no tests\n"  # space form -> survivor
        "random banner line without a colon status\n"
    )
    report = parse_mutmut_results(text)
    assert report.total == 2
    assert report.killed == 1
    assert report.survived == 1  # "no tests" classified as survivor


def test_parse_stryker_json_fixture():
    report = parse_stryker_json(
        (_FIXTURES / "stryker_mutation_report.json").read_bytes()
    )
    # Killed + Timeout = detected(2); Survived + NoCoverage = survivors(2);
    # CompileError excluded from total.
    assert report.killed == 2
    assert report.survived == 2
    assert report.total == 4
    assert any(
        "Survived".lower() in s.lower() or "math.js" in s for s in report.surviving
    )


def test_parse_stryker_json_malformed_fails_closed():
    with pytest.raises(MutationEngineError):
        parse_stryker_json("{ not json")
    with pytest.raises(MutationEngineError):
        parse_stryker_json('{"no": "files"}')


# ---------------------------------------------------------------------------
# ratchet compare + fail-closed (fake adapter)
# ---------------------------------------------------------------------------


class _FakeAdapter:
    def __init__(self, report=None, exc=None):
        self._report = report
        self._exc = exc

    def run(self, workspace, *, paths, timeout, params):
        if self._exc is not None:
            raise self._exc
        return self._report


def _with_fake(monkeypatch, name, adapter):
    engines = dict(mut._ENGINES)
    engines[name] = lambda: adapter
    monkeypatch.setattr(mut, "_ENGINES", engines)


def test_ratchet_passes_when_survivors_within_floor(tmp_path, monkeypatch):
    _with_fake(
        monkeypatch,
        "fake",
        _FakeAdapter(MutationReport(killed=10, survived=0, total=10)),
    )
    res = mut.Mutation().check(_ctx(tmp_path, _config(engine="fake", max_survivors=0)))
    assert res.ok, res.detail


def test_ratchet_fails_when_survivors_exceed_floor(tmp_path, monkeypatch):
    _with_fake(
        monkeypatch,
        "fake",
        _FakeAdapter(
            MutationReport(killed=8, survived=2, total=10, surviving=("m1", "m2"))
        ),
    )
    res = mut.Mutation().check(_ctx(tmp_path, _config(engine="fake", max_survivors=0)))
    assert not res.ok
    assert "m1" in res.detail and "survived" in res.detail


def test_ratchet_engine_error_fails_closed(tmp_path, monkeypatch):
    _with_fake(
        monkeypatch,
        "fake",
        _FakeAdapter(exc=MutationEngineError("mutmut not found on PATH")),
    )
    res = mut.Mutation().check(_ctx(tmp_path, _config(engine="fake")))
    assert not res.ok and not res.inactive
    assert "failed" in res.detail


def test_ratchet_unknown_engine_fails_closed(tmp_path):
    res = mut.Mutation().check(_ctx(tmp_path, _config(engine="nonesuch")))
    assert not res.ok and not res.inactive
    assert "unknown mutation engine" in res.detail


# ---------------------------------------------------------------------------
# integration: drive REAL mutmut (skipped if absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("mutmut") is None, reason="mutmut not installed")
def test_mutmut_integration_survivor_detected(tmp_path):
    """A weak suite (asserts only the True branch) must leave a `>`->`>=` /
    constant mutant alive — the ratchet must report a survivor."""
    (tmp_path / "target.py").write_text(
        textwrap.dedent(
            """\
            def is_positive(x):
                return x > 0
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "test_target.py").write_text(
        textwrap.dedent(
            """\
            from target import is_positive

            def test_is_positive():
                assert is_positive(5) is True
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "setup.cfg").write_text(
        "[mutmut]\nsource_paths=target.py\n", encoding="utf-8"
    )
    # mutmut shells pytest; make sure it finds this interpreter's pytest.
    res = mut.Mutation().check(
        _ctx(tmp_path, _config(engine="mutmut", max_survivors=0, timeout_seconds=300))
    )
    assert not res.ok, res.detail
    assert "survived" in res.detail


@pytest.mark.skipif(shutil.which("mutmut") is None, reason="mutmut not installed")
def test_mutmut_adapter_reports_total(tmp_path):
    """Direct adapter check: a real mutmut run yields total > 0 and a parseable
    report (guards against silent zero-mutant degeneration)."""
    (tmp_path / "target.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "test_target.py").write_text(
        "from target import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (tmp_path / "setup.cfg").write_text(
        "[mutmut]\nsource_paths=target.py\n", encoding="utf-8"
    )
    report = mut.MutmutAdapter().run(tmp_path, paths=[], timeout=300, params={})
    assert report.total > 0
    assert report.killed + report.survived <= report.total
