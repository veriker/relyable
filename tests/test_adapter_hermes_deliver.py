"""test_adapter_hermes_deliver.py — the Hermes deliver-edge guard (output edge).

Hermes is Python, so the deliver guard is a DIRECT in-process call (no subprocess) at
the ``finalize_turn`` chokepoint. This drives it over REAL relyable re-derivations
(recompute + sealed-reference modes): a deliverable that re-derives is delivered
(``deliver_block_reason`` -> None), a fabricated one is suppressed (-> reason string)
— the openclaw#49876 / #44637 fail-closed posture, on Hermes. Reuses the same worked
graders/fixtures as the memory tests.
"""

from __future__ import annotations

from pathlib import Path

from relyable.adapters.hermes import (
    HermesDeliverConfig,
    deliver_block_reason,
    rederive_deliverable,
)
from relyable.memory import compute_reference_anchor
from relyable.memory.examples import recall_grader, recompute_grader, safe_versions

RECOMPUTE_GRADER = Path(recompute_grader.__file__)
SEALED_GRADER = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent

GOOD = {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}}
FABRICATED = {"items": [3, 1, 2], "result": {"count": 3, "sum": 99, "max": 3}}


def _cfg(**kw) -> HermesDeliverConfig:
    return HermesDeliverConfig(grader_src=RECOMPUTE_GRADER, **kw)


# --- recompute mode -----------------------------------------------------------
def test_rederiving_deliverable_is_delivered():
    assert deliver_block_reason("brief", GOOD, _cfg()) is None


def test_fabricated_deliverable_is_suppressed():
    reason = deliver_block_reason("fake", FABRICATED, _cfg())
    assert reason is not None
    assert "did not re-derive" in reason


def test_verdict_surface():
    v = rederive_deliverable("brief", GOOD, _cfg())
    assert v.admitted is True and v.verdict == "ADMIT" and v.rederived is True
    bad = rederive_deliverable("fake", FABRICATED, _cfg())
    assert bad.admitted is False and bad.verdict == "REJECT"


# --- sealed-reference mode ----------------------------------------------------
def test_sealed_reference_delivers_known_suppresses_unknown():
    cfg = HermesDeliverConfig(grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR)
    good = {"package": "acme-http", "version": "1.4.2"}
    bad = {"package": "acme-http", "version": "9.9.9"}
    assert deliver_block_reason("pkg", good, cfg) is None
    assert deliver_block_reason("poison", bad, cfg) is not None


def test_reference_anchor_mismatch_suppresses_fail_closed():
    cfg = HermesDeliverConfig(
        grader_src=SEALED_GRADER,
        reference_path=REFERENCE_DIR,
        reference_anchor="sha256:" + "0" * 64,
    )
    reason = deliver_block_reason(
        "pkg", {"package": "acme-http", "version": "1.4.2"}, cfg
    )
    assert reason is not None and "REFERENCE_ANCHOR_MISMATCH" in reason


def test_reference_anchor_match_delivers():
    cfg = HermesDeliverConfig(
        grader_src=SEALED_GRADER,
        reference_path=REFERENCE_DIR,
        reference_anchor=compute_reference_anchor(REFERENCE_DIR),
    )
    assert (
        deliver_block_reason("pkg", {"package": "acme-http", "version": "1.4.2"}, cfg)
        is None
    )


# --- config from env ----------------------------------------------------------
def test_config_from_env_requires_grader():
    import pytest

    with pytest.raises(ValueError, match="RELYABLE_HERMES_DELIVER_GRADER is required"):
        HermesDeliverConfig.from_env({})


def test_config_from_env_parses():
    cfg = HermesDeliverConfig.from_env(
        {
            "RELYABLE_HERMES_DELIVER_GRADER": str(SEALED_GRADER),
            "RELYABLE_HERMES_DELIVER_REFERENCE": str(REFERENCE_DIR),
            "RELYABLE_HERMES_DELIVER_NO_RUN": "1",
        }
    )
    assert cfg.grader_src == SEALED_GRADER
    assert cfg.reference_path == REFERENCE_DIR
    assert cfg.permit_execution is False
