"""test_adapter_hermes.py — the Hermes skills adapter, driven through a faithful
reconstruction of Hermes's skill-write admission contract.

Not mocked-only: ``fake_hermes.create_skill`` reproduces the real upstream
``_create_skill`` rollback flow (DISCOVERY.md), and the guard re-derives REAL
veriker bundles built by ``skills_fixtures``. A re-deriving skill is admitted and
survives; a forged/broken one is dropped (rmtree) and Hermes gets the reason; an
unverifiable one (no execution permitted) is refused fail-closed.
"""

from __future__ import annotations

from pathlib import Path

import fake_hermes
import pytest
import skills_fixtures as fixtures
from skills_fixtures import GRADER_SRC

from relyable.adapters.hermes import (
    HermesGuardConfig,
    admit_registry,
    rederive_skill_guard,
    usable,
)
from relyable.skills import build_skill_bundle, rederive


def _cfg(permit_execution: bool = True) -> HermesGuardConfig:
    return HermesGuardConfig(grader_src=GRADER_SRC, permit_execution=permit_execution)


def _build_one(dest: Path, skill_id: str, body: str, claimed: str = "VALIDATED"):
    return fixtures._build(dest, skill_id, "merge", body, claimed)


# --- the guard occupies _security_scan_skill's slot in the real rollback flow ---
def test_good_skill_admitted_and_survives(tmp_path):
    bundle = _build_one(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    result = fake_hermes.create_skill(bundle, lambda d: rederive_skill_guard(d, _cfg()))
    assert result == {"success": True}
    assert bundle.is_dir()  # kept: not rolled back


def test_forged_skill_dropped_and_rolled_back(tmp_path):
    # Claims VALIDATED but the <= idiom collapses a book-ended held-out pair:
    # veriker re-derives a mismatch -> guard returns a reason -> Hermes rmtree's it.
    bundle = _build_one(tmp_path, "merge_le_idiom", fixtures.MERGE_LE_IDIOM)
    result = fake_hermes.create_skill(bundle, lambda d: rederive_skill_guard(d, _cfg()))
    assert result["success"] is False
    assert "did not re-derive" in result["error"]
    assert "forged VALIDATED label" in result["error"]
    assert not bundle.exists()  # rolled back


def test_broken_skill_dropped(tmp_path):
    bundle = _build_one(tmp_path, "merge_raises", fixtures.MERGE_RAISES)
    result = fake_hermes.create_skill(bundle, lambda d: rederive_skill_guard(d, _cfg()))
    assert result["success"] is False
    assert not bundle.exists()


def test_unverifiable_refused_fail_closed(tmp_path):
    # permit_execution=False: the candidate is never run, so nothing re-derives and
    # even a genuinely-good skill is refused (could-not-conclude), never admitted.
    bundle = _build_one(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    err = rederive_skill_guard(bundle, _cfg(permit_execution=False))
    assert err is not None
    assert "did not re-derive" in err


def test_guard_returns_none_means_admit(tmp_path):
    bundle = _build_one(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    assert rederive_skill_guard(bundle, _cfg()) is None


# --- the batch surface exposes ONLY re-derived skills (drop-not-warn) ----------
def test_usable_exposes_only_admitted(tmp_path):
    reg = tmp_path / "registry"
    fixtures.build_bundles(reg)  # the full fault matrix: 4 good, 4 bad
    verdicts = admit_registry(reg, _cfg())
    use = usable(reg, _cfg())
    use_ids = {v.skill_id for v in use}
    assert use_ids == {"merge_good", "parse_good", "sort_good"}
    # every bad row is absent from `usable`, present in the full audit trail
    assert len(verdicts) == 8
    assert all(v.verdict == "ADMIT" for v in use)


def test_fully_poisoned_registry_is_inert(tmp_path):
    reg = tmp_path / "poison"
    fixtures.build_poisoned_bundles(reg)  # every skill claims VALIDATED, none hold
    assert usable(reg, _cfg()) == []  # inert, not net-negative


# --- host config: grader_src + permit_execution come from the host, never shipped
def test_config_from_env_requires_grader():
    with pytest.raises(ValueError, match="RELYABLE_HERMES_GRADER is required"):
        HermesGuardConfig.from_env({})


def test_config_from_env_parses(tmp_path):
    cfg = HermesGuardConfig.from_env(
        {
            "RELYABLE_HERMES_GRADER": str(GRADER_SRC),
            "RELYABLE_HERMES_PERMIT_EXECUTION": "yes",
        }
    )
    assert cfg.grader_src == GRADER_SRC
    assert cfg.permit_execution is True


def test_config_permit_execution_defaults_false(tmp_path):
    cfg = HermesGuardConfig.from_env({"RELYABLE_HERMES_GRADER": str(GRADER_SRC)})
    assert cfg.permit_execution is False  # fail-closed default


# --- separation of duties + host-attested principal (L1) through the adapter ----
GRADER_P = "grader/claude-opus-4-8"
OTHER_P = "author/gpt-x"


def _good_with_meta_author(dest: Path, author: str | None):
    """A genuinely re-deriving skill tagged with a meta author_principal."""
    return build_skill_bundle(
        dest / "merge_good",
        skill_id="merge_good",
        kind="merge",
        body=fixtures.MERGE_GOOD,
        claimed_verdict="VALIDATED",
        grader_src=GRADER_SRC,
        author_principal=author,
    )


def _sod_cfg(**kw) -> HermesGuardConfig:
    return HermesGuardConfig(grader_src=GRADER_SRC, permit_execution=True, **kw)


def test_separation_off_by_default(tmp_path):
    """Default config: even author==grader passes, behavior unchanged from before."""
    bundle = _good_with_meta_author(tmp_path, GRADER_P)
    assert rederive_skill_guard(bundle, _cfg()) is None  # admitted


def test_host_attested_same_principal_dropped(tmp_path):
    """require_separation + host session principal == grader principal: a genuinely
    good skill is dropped before the grader runs (SAME_PRINCIPAL)."""
    bundle = _good_with_meta_author(tmp_path, OTHER_P)  # meta says someone else...
    cfg = _sod_cfg(
        require_separation=True,
        grader_principal=GRADER_P,
        session_principal=GRADER_P,  # ...but the HOST attests it's the grader's model
    )
    err = rederive_skill_guard(bundle, cfg)
    assert err is not None
    assert "SAME_PRINCIPAL" in err


def test_host_attested_distinct_admits(tmp_path):
    bundle = _good_with_meta_author(tmp_path, None)
    cfg = _sod_cfg(
        require_separation=True, grader_principal=GRADER_P, session_principal=OTHER_P
    )
    assert rederive_skill_guard(bundle, cfg) is None  # cleared SoD, then re-derived


def test_meta_principal_used_when_no_session(tmp_path):
    """L0 fallback: with no host session principal, the bundle's meta author is used
    (and stamped principal_source='meta')."""
    bundle = _good_with_meta_author(tmp_path, GRADER_P)
    v = rederive(
        bundle,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_P,
        require_separation=True,
    )
    assert v.verdict == "REJECT"
    assert v.reason_code == "SAME_PRINCIPAL"
    assert v.principal_source == "meta"


def test_host_attestation_closes_the_meta_lie(tmp_path):
    """The honesty-boundary narrative. A producer LIES in meta (claims a different
    author) to dodge separation. With only the L0 meta signal the lie WORKS — the
    skill is wrongly admitted. With L1 host attestation the adapter stamps the true
    session principal, the lie is irrelevant, and the circular skill is dropped."""
    bundle = _good_with_meta_author(tmp_path, OTHER_P)  # the lie: "a different model"

    # L0 only (trust the meta): separation passes on the lie -> admitted.
    v_l0 = rederive(
        bundle,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_P,
        require_separation=True,
    )
    assert v_l0.verdict == "ADMIT"  # evaded — meta is forgeable
    assert v_l0.principal_source == "meta"

    # L1 (host attests the real session principal == grader's): lie ignored, dropped.
    v_l1 = rederive(
        bundle,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_P,
        require_separation=True,
        artifact_principal=GRADER_P,  # what the adapter stamps from Hermes's session
    )
    assert v_l1.verdict == "REJECT"
    assert v_l1.reason_code == "SAME_PRINCIPAL"
    assert v_l1.principal_source == "host"


def test_config_from_env_parses_separation(tmp_path):
    cfg = HermesGuardConfig.from_env(
        {
            "RELYABLE_HERMES_GRADER": str(GRADER_SRC),
            "RELYABLE_HERMES_REQUIRE_SEPARATION": "1",
            "RELYABLE_HERMES_GRADER_PRINCIPAL": GRADER_P,
            "RELYABLE_HERMES_SESSION_PRINCIPAL": OTHER_P,
        }
    )
    assert cfg.require_separation is True
    assert cfg.grader_principal == GRADER_P
    assert cfg.session_principal == OTHER_P


def test_config_separation_defaults_off(tmp_path):
    cfg = HermesGuardConfig.from_env({"RELYABLE_HERMES_GRADER": str(GRADER_SRC)})
    assert cfg.require_separation is False
    assert cfg.grader_principal is None
    assert cfg.session_principal is None
