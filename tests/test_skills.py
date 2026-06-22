"""relyable.skills — the fault matrix, re-derived through veriker.

A skill is usable iff veriker's OWN verifier (via relyable.gate + the gated
re-derivation pack lane) re-derives its VALIDATED label against the consumer's
trusted grader. The consumer's grader is pinned into every bundle, so the bundle
supplies only the digest-bound candidate; claimed_verdict is never read for the
decision; a poisoned bundle stays inert.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import skills_fixtures as fixtures
from skills_fixtures import GRADER_SRC

from relyable.skills import (
    ADMIT,
    REJECT,
    admit_directory,
    build_skill_bundle,
    rederive,
    usable_skills,
)


@pytest.fixture
def registry_dir(tmp_path) -> Path:
    d = tmp_path / "registry"
    fixtures.build_bundles(d)
    return d


def _admit(d, *, permit_execution=True):
    return admit_directory(d, grader_src=GRADER_SRC, permit_execution=permit_execution)


def _by_id(verdicts):
    return {v.skill_id: v for v in verdicts}


def _build(dest, **kw):
    return build_skill_bundle(dest, grader_src=GRADER_SRC, **kw)


# --- the fault matrix (permit_execution=True: the vetting posture) ------------
def test_fault_matrix(registry_dir):
    """Every scenario reaches the verdict + veriker reason_code + forged flag it
    must. The reason codes are veriker's own: RE_DERIVED (admit), plugin_failed
    (the grader pack returned non-zero), bad_file_sha (strict-SHA digest rail)."""
    expected = {
        "merge_good": (ADMIT, "RE_DERIVED", False),
        "merge_le_idiom": (REJECT, "plugin_failed", True),
        "parse_good": (ADMIT, "RE_DERIVED", False),
        "sort_good": (ADMIT, "RE_DERIVED", False),
        "merge_broken": (REJECT, "plugin_failed", True),
        "merge_raises": (REJECT, "plugin_failed", True),
        "frob_unknown": (REJECT, "plugin_failed", True),
        "merge_tampered": (REJECT, "bad_file_sha", True),
    }
    got = _by_id(_admit(registry_dir))
    assert set(got) == set(expected)
    for sid, (verdict, code, forged) in expected.items():
        v = got[sid]
        assert v.verdict == verdict, (sid, v)
        assert v.reason_code == code, (sid, v)
        assert v.forged_label == forged, (sid, v)


def test_only_rederived_skills_are_usable(registry_dir):
    usable = {v.skill_id for v in usable_skills(_admit(registry_dir))}
    assert usable == {"merge_good", "parse_good", "sort_good"}


def test_discriminator_detail_names_the_holdout_mismatch(registry_dir):
    """The wrong `<=` merge fails on the chr1 book-ended held-out, and the veriker
    verdict detail carries the grader's [SKILL_REDER_FAIL] mismatch marker — proof
    the candidate was actually RUN, not trusted."""
    v = _by_id(_admit(registry_dir))["merge_le_idiom"]
    assert "SKILL_REDER_FAIL" in v.detail
    assert "mismatch" in v.detail


def test_claimed_verdict_never_admits_a_failing_skill(tmp_path):
    """A wrong-merge skill CLAIMING VALIDATED is rejected by the re-derivation; the
    claim is contradicted, never trusted."""
    bdir = _build(
        tmp_path / "liar",
        skill_id="liar",
        kind="merge",
        body=fixtures.MERGE_LE_IDIOM,
        claimed_verdict="VALIDATED",
    )
    v = rederive(bdir, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == REJECT
    assert v.rederived_label == "REJECTED"
    assert v.forged_label is True


def test_honest_merge_admits(tmp_path):
    bdir = _build(
        tmp_path / "honest",
        skill_id="honest",
        kind="merge",
        body=fixtures.MERGE_GOOD,
        claimed_verdict="VALIDATED",
    )
    v = rederive(bdir, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == ADMIT
    assert v.rederived_label == "VALIDATED"
    assert v.forged_label is False


def test_digest_rail_is_veriker_strict_sha(tmp_path):
    """Swap the candidate body after the manifest is written -> veriker's own
    strict-SHA file_integrity gate rejects with bad_file_sha."""
    bdir = _build(
        tmp_path / "swap",
        skill_id="swap",
        kind="merge",
        body=fixtures.MERGE_GOOD,
        claimed_verdict="VALIDATED",
    )
    (bdir / "skill" / "candidate.py").write_text(
        fixtures.MERGE_LE_IDIOM, encoding="utf-8"
    )
    v = rederive(bdir, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == REJECT
    assert v.reason_code == "bad_file_sha"


def test_grader_is_consumer_installed_not_bundle_supplied(tmp_path):
    """The producer cannot ship a lying grader: even if a pack file is pre-placed,
    build_skill_bundle overwrites it with the consumer's trusted copy, so a
    poisoned skill still fails closed."""
    dest = tmp_path / "evil"
    (dest / "re_derive").mkdir(parents=True)
    (dest / "re_derive" / GRADER_SRC.name).write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    _build(
        dest,
        skill_id="evil",
        kind="merge",
        body=fixtures.MERGE_LE_IDIOM,
        claimed_verdict="VALIDATED",
    )
    installed = (dest / "re_derive" / GRADER_SRC.name).read_text(encoding="utf-8")
    assert "SKILL_REDER_FAIL" in installed  # the consumer's real grader, not the stub
    v = rederive(dest, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == REJECT


def test_grader_pin_rejects_self_consistent_lying_grader(tmp_path):
    """The strongest poisoned-inert axis: an adversary hand-assembles a bundle
    whose manifest is SELF-CONSISTENT with a lying exit(0) grader (so the strict-
    SHA rail is satisfied). The grader-pin still rejects, because the grader is not
    byte-identical to the consumer's trusted copy — ADMIT is impossible unless OUR
    grader graded the skill."""
    bdir = _build(
        tmp_path / "evil",
        skill_id="evil",
        kind="merge",
        body=fixtures.MERGE_LE_IDIOM,
        claimed_verdict="VALIDATED",
    )
    lying = "import sys\nsys.exit(0)\n"
    grader = bdir / "re_derive" / GRADER_SRC.name
    grader.write_text(lying, encoding="utf-8")
    man = json.loads((bdir / "manifest.json").read_text())
    man["files"][f"re_derive/{GRADER_SRC.name}"] = hashlib.sha256(
        lying.encode()
    ).hexdigest()
    (bdir / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")

    v = rederive(bdir, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == REJECT
    assert v.reason_code == "GRADER_MISMATCH"


def test_missing_grader_is_not_a_spurious_admit(tmp_path):
    """A bundle with NO grader pack would make veriker return NO_PACK (ok=True);
    the grader-pin rejects it (NO_GRADER) so the candidate is never silently
    admitted ungraded."""
    bdir = _build(
        tmp_path / "nopack",
        skill_id="nopack",
        kind="merge",
        body=fixtures.MERGE_GOOD,
        claimed_verdict="VALIDATED",
    )
    (bdir / "re_derive" / GRADER_SRC.name).unlink()
    v = rederive(bdir, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == REJECT
    assert v.reason_code == "NO_GRADER"


def test_undeclared_extra_file_rejected_by_conservation(tmp_path):
    """An honest skill, but the bundle ships an UNDECLARED extra file. veriker's own
    conservation gate (UNOWNED -> REJECT) catches it."""
    bdir = _build(
        tmp_path / "extra",
        skill_id="extra",
        kind="merge",
        body=fixtures.MERGE_GOOD,
        claimed_verdict="VALIDATED",
    )
    (bdir / "re_derive" / "stowaway.py").write_text("x = 1\n", encoding="utf-8")
    v = rederive(bdir, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == REJECT


def test_wont_run_posture_is_could_not_conclude_not_forged(registry_dir):
    """permit_execution=False: every skill is could-not-conclude (UNVERIFIED),
    nothing admitted, and an HONEST skill is NOT mislabeled forged."""
    verdicts = _admit(registry_dir, permit_execution=False)
    assert usable_skills(verdicts) == []
    by_id = _by_id(verdicts)
    assert by_id["merge_good"].rederived_label == "UNVERIFIED"
    assert by_id["merge_good"].forged_label is False
    # every skill is could-not-conclude EXCEPT the digest tamper, which the
    # strict-SHA rail rejects pre-execution (independent of permit_execution).
    assert by_id["merge_tampered"].reason_code == "bad_file_sha"
    assert by_id["merge_tampered"].rederived_label == "REJECTED"
    assert all(
        v.rederived_label == "UNVERIFIED"
        for v in verdicts
        if v.skill_id != "merge_tampered"
    )


def test_poisoned_registry_is_inert(tmp_path):
    """A fully-poisoned bundle dir (all claim VALIDATED, none re-derive) yields
    ZERO usable skills under the vetting posture — inert, not net-negative."""
    d = tmp_path / "poison"
    ids = fixtures.build_poisoned_bundles(d)
    verdicts = _admit(d)
    assert len(verdicts) == len(ids)
    assert usable_skills(verdicts) == []


def test_rederivation_is_deterministic(registry_dir):
    a = {(v.skill_id, v.verdict, v.reason_code) for v in _admit(registry_dir)}
    b = {(v.skill_id, v.verdict, v.reason_code) for v in _admit(registry_dir)}
    assert a == b
