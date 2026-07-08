"""bundle.py — assemble a real veriker bundle around a candidate skill.

The producer ships a CLAIM: a skill body + its kind + an asserted verdict. This
binding turns that claim into a real veriker audit bundle (vcp-v1.1 manifest,
files digest-bound) so veriker's own verifier can re-derive it. The bundle
carries:

    skill/candidate.py            the candidate body (digest-bound by the manifest)
    skill/meta.json               {skill_id, kind, claimed_verdict}
    re_derive/<grader name>       the GRADER — ALWAYS installed from the consumer's
                                  own trusted copy (grader_src), never producer-
                                  supplied

The manifest declares ``re_derivation_invocation`` and digest-binds every file
(the producer computes the digests to BUILD the bundle; veriker's strict-SHA walk
independently re-checks them — that walk, not this builder, is the trust rail).
Thin wrapper over ``relyable.gate.build_attested_bundle``.
"""

from __future__ import annotations

from pathlib import Path

from relyable.gate import build_attested_bundle


def build_skill_bundle(
    dest: Path,
    *,
    skill_id: str,
    kind: str,
    body: str,
    claimed_verdict: str,
    grader_src: Path,
    pack_filename: str | None = None,
    author_principal: str | None = None,
) -> Path:
    """Write a real veriker bundle for one candidate skill at ``dest``. The grader
    is installed from the consumer's trusted copy (``grader_src``); only the skill
    body + meta come from the producer. Returns ``dest``.

    ``author_principal`` (optional) records who produced the skill (e.g. a model
    id) for the separation-of-duties check; it is producer-supplied (see the
    honesty boundary in ``relyable.gate.verify_attested_bundle``)."""
    meta = {"skill_id": skill_id, "kind": kind, "claimed_verdict": claimed_verdict}
    if author_principal is not None:
        meta["author_principal"] = author_principal
    return build_attested_bundle(
        dest,
        candidate_body=body,
        meta=meta,
        grader_src=grader_src,
        pack_filename=pack_filename,
        bundle_id=f"relyable-skill-{skill_id}",
    )


def build_native_skill_bundle(
    dest: Path,
    *,
    skill_id: str,
    kind: str,
    artifact_dir: Path,
    grader_src: Path,
    claimed_verdict: str = "CLAIMS_SPEC_CONFORMANT",
    invocation: dict | None = None,
    pack_filename: str | None = None,
    author_principal: str | None = None,
) -> Path:
    """Write a real veriker bundle whose candidate is a NATIVE multi-file / non-
    Python skill (e.g. a ClawHub SKILL.md + scripts), copied verbatim from
    ``artifact_dir`` under ``skill/``.

    Unlike ``build_skill_bundle`` (one Python ``candidate.py``), this carries the
    whole skill tree so the grader can run the skill's own entrypoint. The grader
    is still installed from the consumer's trusted ``grader_src`` (never producer-
    supplied).

    A native skill carries no machine-checkable pass-label, so ``claimed_verdict``
    defaults to the sentinel ``"CLAIMS_SPEC_CONFORMANT"`` — present only for the
    audit trail; the decision is the consumer-grader re-derivation, never this
    label. ``invocation`` (e.g. {"entrypoint": "convert.py", "runner": "python"})
    is recorded in ``skill/meta.json`` as a HINT for the grader; it travels in the
    bundle and is therefore producer-influenced — the consumer's grader treats it
    as untrusted and a lying entrypoint simply fails to re-derive (fail-closed)."""
    meta: dict = {
        "skill_id": skill_id,
        "kind": kind,
        "claimed_verdict": claimed_verdict,
    }
    if invocation is not None:
        meta["invocation"] = invocation
    if author_principal is not None:
        meta["author_principal"] = author_principal
    return build_attested_bundle(
        dest,
        artifact_dir=artifact_dir,
        meta=meta,
        grader_src=grader_src,
        pack_filename=pack_filename,
        bundle_id=f"relyable-skill-{skill_id}",
    )
