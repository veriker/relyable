"""test_audit_emit.py — the audit-bundle attestation layer.

audit_emit re-derives through the veriker substrate (a core dependency); the
importorskip below is a defensive guard for a broken install. Proves the Axis-2
round trip mirrors examples/agent_honesty_minimal:

  * a verdict emitted from a REAL green gate run verifies GREEN;
  * a direct emit round-trips GREEN;
  * a tampered claimed verdict (re-stamped so file-integrity passes) rides RED on
    REDERIVATION_MISMATCH — the verdict is re-parsed from the committed report,
    never read from the claim;
  * an inconclusive gate result refuses to emit.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

# audit_emit re-derives through veriker (a core dependency); guard a broken install.
audit_emit = pytest.importorskip(
    "relyable.verdicts.audit_emit",
    reason="veriker substrate (audit_bundle) not importable",
)

from relyable.verdicts.config import load_config  # noqa: E402
from relyable.verdicts.gate import GateResult, evaluate  # noqa: E402
from relyable.verdicts.runner import RunResult  # noqa: E402
from relyable.verdicts.verdict import parse_junit_xml  # noqa: E402

_CREATED_AT = "2026-06-14T00:00:00Z"

_REPORT = (
    '<testsuite name="s" tests="2">'
    '<testcase classname="t" name="a"/>'
    '<testcase classname="t" name="b"/>'
    "</testsuite>"
).encode("utf-8")


def _restamp(bundle_dir: Path) -> None:
    """Recompute every manifest SHA so file-integrity passes — isolating the
    re-derivation check as the thing that must catch the semantic lie."""
    mpath = bundle_dir / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    for rel in m.get("files", {}):
        m["files"][rel] = hashlib.sha256((bundle_dir / rel).read_bytes()).hexdigest()
    for name in m.get("spec_files", {}):
        m["spec_files"][name] = hashlib.sha256(
            (bundle_dir / "spec" / name).read_bytes()
        ).hexdigest()
    mpath.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")


def _failure_codes(result) -> list[str]:
    return [f.reason_code for f in result.failures]


# ---------------------------------------------------------------------------
# Round-trips
# ---------------------------------------------------------------------------


def test_emit_bundle_round_trips_green(tmp_path):
    verdict = parse_junit_xml(_REPORT)
    bundle = audit_emit.emit_bundle(
        tmp_path / "b", report_xml=_REPORT, verdict=verdict, created_at=_CREATED_AT
    )
    result = audit_emit.verify_bundle(bundle)
    assert result.ok, _failure_codes(result)


def test_emit_from_green_gate_run_verifies_green(tmp_path):
    """The realest path: a green gate run produces report.xml, and the bundle
    emitted from that GateResult verifies GREEN."""
    (tmp_path / "test_ok.py").write_text(
        "def test_a():\n    assert 1 == 1\n\ndef test_b():\n    assert 2 == 2\n",
        encoding="utf-8",
    )
    (tmp_path / "honesty.toml").write_text(
        "[test]\n"
        f'command = ["{sys.executable}", "-m", "pytest", "-q", "--junitxml=report.xml"]\n'
        'report_path = "report.xml"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path / "honesty.toml")
    result = evaluate(tmp_path, config)
    assert result.ok, result.render()

    bundle = audit_emit.emit_from_gate_result(
        tmp_path / "bundle",
        workspace=tmp_path,
        config=config,
        result=result,
        created_at=_CREATED_AT,
    )
    vres = audit_emit.verify_bundle(bundle)
    assert vres.ok, _failure_codes(vres)


# ---------------------------------------------------------------------------
# Tamper rides RED
# ---------------------------------------------------------------------------


def test_tampered_verdict_rides_red(tmp_path):
    verdict = parse_junit_xml(_REPORT)
    bundle = audit_emit.emit_bundle(
        tmp_path / "b", report_xml=_REPORT, verdict=verdict, created_at=_CREATED_AT
    )
    claim = bundle / "outputs" / "test_verdict.json"
    doc = json.loads(claim.read_text(encoding="utf-8"))
    doc["value"]["passed"] = 99  # the lie: claim more passes than the report shows
    claim.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    _restamp(bundle)

    result = audit_emit.verify_bundle(bundle)
    assert not result.ok
    assert "REDERIVATION_MISMATCH" in _failure_codes(result)


# ---------------------------------------------------------------------------
# Refuse to attest a run that did not conclude
# ---------------------------------------------------------------------------


def test_emit_refuses_inconclusive_result(tmp_path):
    inconclusive = GateResult(
        ok=False,
        run=RunResult(verdict=None, conclusive=False, reason="no report produced"),
        ratchets=(),
        anchor="x",
        anchor_pinned=False,
        baseline_present=False,
    )
    with pytest.raises(ValueError, match="did not conclude"):
        audit_emit.emit_from_gate_result(
            tmp_path / "bundle",
            workspace=tmp_path,
            config=load_config_stub(tmp_path),
            result=inconclusive,
            created_at=_CREATED_AT,
        )


def load_config_stub(tmp_path: Path):
    (tmp_path / "honesty.toml").write_text(
        '[test]\ncommand = ["true"]\nreport_path = "report.xml"\n', encoding="utf-8"
    )
    return load_config(tmp_path / "honesty.toml")
