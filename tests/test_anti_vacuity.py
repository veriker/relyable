"""anti_vacuity (B2) — the mutation-ratchet anti-vacuity gate.

Two layers, mirroring test_mutation.py:
  (a) cert assembly / scope-binding / version-stamp / fail-closed, driven through
      an INJECTED engine runner + the RECORDED tests/fixtures/mutmut_results.txt —
      no mutmut binary needed (the self-gate runs these);
  (b) ONE live end-to-end test (skipped when mutmut is absent): a faithful
      round-trip on a correct reference kills M/M; a weak schema-conformance
      property leaves survivors -> ok=False.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from relyable.skills.anti_vacuity import (
    HONEST_CATCH,
    EngineResult,
    prove_non_vacuous,
)
from relyable.skills.property_grader import make_property_grader
from relyable.verdicts.ratchets.mutation import (
    MutationEngineError,
    MutationReport,
    parse_mutmut_results,
)

_FIXTURES = Path(__file__).parent / "fixtures"

# A concrete round-trip grader + a faithful reference (string reverse round-trips).
_GRADER = make_property_grader(
    "round_trip",
    contract_fn="encode",
    params={"inverse": "decode", "inputs": [("hi",)]},
)
_REF = "def encode(s):\n    return s[::-1]\n\n\ndef decode(s):\n    return s[::-1]\n"


def _recorded() -> MutationReport:
    return parse_mutmut_results((_FIXTURES / "mutmut_results.txt").read_text())


def _runner(report=None, exc=None, version="3.6.0"):
    def run(workspace, *, mutmut_binary, timeout):
        if exc is not None:
            raise exc
        return EngineResult(report=report, version=version)

    return run


# ---------------------------------------------------------------------------
# (a) cert assembly + fail-closed via injected runner (no mutmut)
# ---------------------------------------------------------------------------


def test_cert_fails_when_survivors_exceed_floor():
    # fixture: killed=1, survived=2, total=3
    cert = prove_non_vacuous(
        _GRADER, _REF, kind="round_trip", run_engine=_runner(report=_recorded())
    )
    assert cert.ok is False
    assert cert.killed == 1 and cert.total == 3
    assert len(cert.survivors) == 2 and "survivor" in cert.reason


def test_cert_passes_within_floor():
    cert = prove_non_vacuous(
        _GRADER,
        _REF,
        kind="round_trip",
        max_survivors=2,
        run_engine=_runner(report=_recorded()),
    )
    assert cert.ok is True and cert.reason == ""


def test_scope_binding_records_reference_digest():
    cert = prove_non_vacuous(
        _GRADER, _REF, kind="round_trip", run_engine=_runner(report=_recorded())
    )
    assert cert.reference_digest == hashlib.sha256(_REF.encode()).hexdigest()


def test_version_is_stamped_from_engine():
    cert = prove_non_vacuous(
        _GRADER,
        _REF,
        kind="round_trip",
        run_engine=_runner(report=_recorded(), version="9.9.9-test"),
    )
    assert cert.mutmut_version == "9.9.9-test" and cert.engine == "mutmut"


def test_honest_catch_on_cert_verbatim():
    cert = prove_non_vacuous(
        _GRADER, _REF, kind="round_trip", run_engine=_runner(report=_recorded())
    )
    assert cert.honest_catch == HONEST_CATCH
    assert "kills-mutants proves NON-VACUOUS, not correct-spec" in cert.honest_catch


def test_fail_closed_mutmut_absent():
    cert = prove_non_vacuous(
        _GRADER,
        _REF,
        kind="round_trip",
        run_engine=_runner(exc=MutationEngineError("'mutmut' not found on PATH")),
    )
    assert cert.ok is False
    assert "BLOCK" in cert.reason and cert.total == 0


def test_fail_closed_zero_mutant_is_block_not_pass():
    cert = prove_non_vacuous(
        _GRADER,
        _REF,
        kind="round_trip",
        run_engine=_runner(report=MutationReport(killed=0, survived=0, total=0)),
    )
    assert cert.ok is False and "zero mutants" in cert.reason


def test_determinism_rejected_up_front():
    with pytest.raises(ValueError, match="not a provable property"):
        prove_non_vacuous(
            _GRADER, _REF, kind="determinism", run_engine=_runner(report=_recorded())
        )


def test_placeholder_grader_rejected():
    placeholder = make_property_grader(
        "schema_conformance", contract_fn="build", placeholders=True
    )
    with pytest.raises(ValueError, match="CONCRETE"):
        prove_non_vacuous(
            placeholder,
            "def build(n):\n    return {'x': n}\n",
            kind="schema_conformance",
            run_engine=_runner(report=_recorded()),
        )


def test_kind_mismatch_rejected():
    with pytest.raises(ValueError, match="does not match"):
        prove_non_vacuous(
            _GRADER, _REF, kind="idempotence", run_engine=_runner(report=_recorded())
        )


# ---------------------------------------------------------------------------
# (b) live: drive REAL mutmut (skipped if absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("mutmut") is None, reason="mutmut not installed")
def test_live_round_trip_kills_all_mutants():
    """A faithful round-trip (decode(encode(n)) == n) kills every mutant — ok with
    survived==0, killed==total."""
    grader = make_property_grader(
        "round_trip",
        contract_fn="encode",
        params={"inverse": "decode", "inputs": [(3,), (7,), (100,)]},
    )
    ref = "def encode(n):\n    return n + 1\n\n\ndef decode(n):\n    return n - 1\n"
    cert = prove_non_vacuous(grader, ref, kind="round_trip", timeout=300)
    assert cert.ok is True, cert.reason
    assert cert.total > 0 and cert.killed == cert.total and not cert.survivors
    assert cert.mutmut_version and cert.mutmut_version != "unknown"


@pytest.mark.skipif(shutil.which("mutmut") is None, reason="mutmut not installed")
def test_live_weak_schema_property_leaves_survivors():
    """A schema-conformance property whose mutants stay shape-valid is vacuous —
    survivors are listed, ok=False."""
    grader = make_property_grader(
        "schema_conformance",
        contract_fn="build",
        params={"schema": {"type": "object"}, "inputs": [(1,), (5,), (9,)]},
    )
    ref = 'def build(n):\n    return {"x": n + 1, "y": n * 2}\n'
    cert = prove_non_vacuous(grader, ref, kind="schema_conformance", timeout=300)
    assert cert.ok is False
    assert cert.total > 0 and len(cert.survivors) > 0
