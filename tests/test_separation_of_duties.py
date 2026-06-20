"""Separation of duties — the gate-level guard against an agent authoring both a
skill and the criteria that admit it (prototype C).

The producing principal (skill/meta.json "author_principal") must differ from the
grader's authoring principal (consumer config). When it does not, the skill is
REJECTED *before* the grader runs — a fail-closed pre-check, not a forgery finding.

These tests pin the honesty boundary too: separation is OPT-IN (off by default,
so the whole existing fault matrix is unchanged), it is a second rail on top of
re-derivation (not a replacement), and it cannot itself admit anything.
"""

from __future__ import annotations

from pathlib import Path

import skills_fixtures as fixtures
from skills_fixtures import GRADER_SRC

from relyable.gate import (
    MISSING_PRINCIPAL,
    SAME_PRINCIPAL,
    verify_attested_bundle,
)
from relyable.skills import ADMIT, REJECT, build_skill_bundle, rederive

GRADER_PRINCIPAL = "grader-model/claude-opus-4-8"
OTHER_PRINCIPAL = "author-model/gpt-x"


def _good_bundle(dest: Path, *, author_principal: str | None) -> Path:
    """A skill that genuinely re-derives (MERGE_GOOD), tagged with author_principal."""
    return build_skill_bundle(
        dest / "merge_good",
        skill_id="merge_good",
        kind="merge",
        body=fixtures.MERGE_GOOD,
        claimed_verdict="VALIDATED",
        grader_src=GRADER_SRC,
        author_principal=author_principal,
    )


def test_off_by_default_admits_genuine_skill(tmp_path):
    """With separation NOT required, a genuinely-re-deriving skill is admitted even
    when author == grader principal: the existing behavior is untouched."""
    b = _good_bundle(tmp_path, author_principal=GRADER_PRINCIPAL)
    v = rederive(b, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == ADMIT
    assert v.reason_code == "RE_DERIVED"


def test_same_principal_rejected_before_grader(tmp_path):
    """A genuinely-correct skill is still REJECTED when its author principal equals
    the grader's — the same agent cannot grade its own homework. The skill WOULD
    re-derive (proven by the off-by-default test above), so the rejection is the
    separation rail, not a re-derivation failure."""
    b = _good_bundle(tmp_path, author_principal=GRADER_PRINCIPAL)
    v = rederive(
        b,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_PRINCIPAL,
        require_separation=True,
    )
    assert v.verdict == REJECT
    assert v.reason_code == SAME_PRINCIPAL
    assert v.rederived_label == "UNVERIFIED"  # the grader never ran


def test_distinct_principals_admit(tmp_path):
    """Separation required + author != grader: the skill clears the SoD rail and is
    then admitted on its genuine re-derivation."""
    b = _good_bundle(tmp_path, author_principal=OTHER_PRINCIPAL)
    v = rederive(
        b,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_PRINCIPAL,
        require_separation=True,
    )
    assert v.verdict == ADMIT
    assert v.reason_code == "RE_DERIVED"


def test_missing_author_principal_fails_closed(tmp_path):
    """Separation required but the bundle declares no author_principal: cannot prove
    distinctness -> fail-closed (MISSING_PRINCIPAL), even for a correct skill."""
    b = _good_bundle(tmp_path, author_principal=None)
    v = rederive(
        b,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_PRINCIPAL,
        require_separation=True,
    )
    assert v.verdict == REJECT
    assert v.reason_code == MISSING_PRINCIPAL


def test_missing_grader_principal_fails_closed(tmp_path):
    """Symmetric: separation required but the consumer named no grader principal."""
    b = _good_bundle(tmp_path, author_principal=OTHER_PRINCIPAL)
    v = rederive(
        b,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=None,
        require_separation=True,
    )
    assert v.verdict == REJECT
    assert v.reason_code == MISSING_PRINCIPAL


def test_separation_does_not_rescue_a_bad_skill(tmp_path):
    """Separation is a second rail, never a bypass: a skill that does NOT re-derive
    is rejected even when the principals are properly distinct (here on the
    re-derivation, having passed the SoD pre-check)."""
    b = build_skill_bundle(
        tmp_path / "merge_le_idiom",
        skill_id="merge_le_idiom",
        kind="merge",
        body=fixtures.MERGE_LE_IDIOM,  # the wrong <=-idiom; veriker returns mismatch
        claimed_verdict="VALIDATED",
        grader_src=GRADER_SRC,
        author_principal=OTHER_PRINCIPAL,
    )
    v = rederive(
        b,
        grader_src=GRADER_SRC,
        permit_execution=True,
        grader_principal=GRADER_PRINCIPAL,
        require_separation=True,
    )
    assert v.verdict == REJECT
    assert v.rederived_label == "REJECTED"  # the grader ran and contradicted it


def test_gate_layer_same_principal_short_circuits(tmp_path):
    """At the gate layer, SAME_PRINCIPAL returns before the grader-pin even runs:
    separation_ok is False, grader_ok is False, and no veriker Verdict was produced."""
    b = _good_bundle(tmp_path, author_principal=GRADER_PRINCIPAL)
    res = verify_attested_bundle(
        b,
        grader_src=GRADER_SRC,
        permit_execution=True,
        artifact_principal=GRADER_PRINCIPAL,
        grader_principal=GRADER_PRINCIPAL,
        require_separation=True,
    )
    assert res.separation_ok is False
    assert res.separation_reason_code == SAME_PRINCIPAL
    assert res.grader_ok is False
    assert res.verdict is None
