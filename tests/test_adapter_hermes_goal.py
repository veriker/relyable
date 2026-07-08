"""test_adapter_hermes_goal.py — the Hermes /goal completion guard (#18421 fix).

The ``/goal`` judge marks DONE from the agent's text alone. This guard re-derives the
completion claim against evidence and reports ``done`` ONLY when it affirmatively
re-derives. Driven over REAL relyable re-derivations (recompute + sealed-reference):
a completion claim that re-derives -> done; one that does not -> not done (the
false-positive that #18421 reports). Reuses the worked graders/fixtures.

The recompute grader stands in for an evidence grader here (the re-derivation
mechanism is identical); a real goal grader reads the filesystem / tool-ledger the
turn claims to have produced.
"""

from __future__ import annotations

from pathlib import Path

from relyable.adapters.hermes import (
    HermesGoalConfig,
    goal_done,
    rederive_goal_completion,
)
from relyable.memory.examples import recall_grader, recompute_grader, safe_versions

RECOMPUTE_GRADER = Path(recompute_grader.__file__)
SEALED_GRADER = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent

# A completion claim whose result re-derives from its inputs == real evidence.
COMPLETED = {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}}
# The #18421 case: the turn claims done, but the evidence does not re-derive.
CLAIMED_NOT_DONE = {"items": [3, 1, 2], "result": {"count": 3, "sum": 99, "max": 3}}


def _cfg(**kw) -> HermesGoalConfig:
    return HermesGoalConfig(grader_src=RECOMPUTE_GRADER, **kw)


# --- recompute mode -----------------------------------------------------------
def test_done_when_completion_rederives():
    assert goal_done("g1", COMPLETED, _cfg()) is True


def test_not_done_when_evidence_does_not_rederive():
    # The exact #18421 false-positive: text would say done, evidence refutes it.
    assert goal_done("g1", CLAIMED_NOT_DONE, _cfg()) is False


def test_verdict_surface():
    v = rederive_goal_completion("g1", COMPLETED, _cfg())
    assert v.done is True and v.rederived is True and v.reason_code == "RE_DERIVED"
    bad = rederive_goal_completion("g1", CLAIMED_NOT_DONE, _cfg())
    assert bad.done is False and bad.rederived is False


# --- sealed-reference mode ----------------------------------------------------
def test_sealed_reference_done_known_not_done_unknown():
    cfg = HermesGoalConfig(grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR)
    assert goal_done("g", {"package": "acme-http", "version": "1.4.2"}, cfg) is True
    assert goal_done("g", {"package": "acme-http", "version": "9.9.9"}, cfg) is False


def test_reference_anchor_mismatch_not_done_fail_closed():
    cfg = HermesGoalConfig(
        grader_src=SEALED_GRADER,
        reference_path=REFERENCE_DIR,
        reference_anchor="sha256:" + "0" * 64,
    )
    v = rederive_goal_completion("g", {"package": "acme-http", "version": "1.4.2"}, cfg)
    assert v.done is False and v.reason_code == "REFERENCE_ANCHOR_MISMATCH"


# --- config from env ----------------------------------------------------------
def test_config_from_env_requires_grader():
    import pytest

    with pytest.raises(ValueError, match="RELYABLE_HERMES_GOAL_GRADER is required"):
        HermesGoalConfig.from_env({})


def test_config_from_env_parses():
    cfg = HermesGoalConfig.from_env(
        {
            "RELYABLE_HERMES_GOAL_GRADER": str(SEALED_GRADER),
            "RELYABLE_HERMES_GOAL_REFERENCE": str(REFERENCE_DIR),
            "RELYABLE_HERMES_GOAL_NO_RUN": "1",
        }
    )
    assert cfg.grader_src == SEALED_GRADER
    assert cfg.reference_path == REFERENCE_DIR
    assert cfg.permit_execution is False
