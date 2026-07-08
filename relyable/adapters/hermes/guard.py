"""guard.py — wire relyable.skills into the Hermes skill-admission chokepoint.

## The seam (see DISCOVERY.md for evidence)

Hermes (``NousResearch/hermes-agent``, Python) has **no skill-lifecycle plugin
hook** — its ``VALID_HOOKS`` set is tool/LLM/session/approval-scoped only. The real
admission chokepoint is the skill-WRITE guard ``_security_scan_skill(skill_dir) ->
Optional[str]`` in ``tools/skill_manager_tool.py``: ``_create_skill`` / ``_edit_skill``
call it after the atomic write and, on a non-empty return, ``shutil.rmtree`` the
skill directory — drop, not warn. That return contract — **``None`` => admit, an
error string => drop** — is what ``rederive_skill_guard`` below matches, so it
drops straight in alongside (or in place of) the existing scan.

Because there is no plugin hook, integration is a source-edit/patch, not a pure
plugin (relyable can ship as a pip dependency Hermes imports, but the one-line
call must be added to ``_security_scan_skill``). That is consistent with what
Hermes issue #25833 asks the project to build: the re-execution check it names as
missing.

## What it does

The guard hands one skill bundle to ``relyable.skills.rederive`` (which stands on
veriker) and converts the verdict to Hermes's drop-string contract: a skill whose
claimed verdict re-derives against the consumer's grader is admitted (``None``); a
forged / broken / unverifiable one returns a reason string and Hermes rolls it
back. ``usable`` is the batch form over a registry directory, exposing only the
ADMIT skills — non-ADMIT skills are absent, not present-with-a-warning.

## Bundle shape

relyable re-derives a **veriker bundle** (``manifest.json`` + ``skill/`` +
the pinned grader), which is the form ``relyable.skills.build_skill_bundle``
produces. A raw Hermes ``SKILL.md`` is therefore packaged into a bundle first (a
producer-side step); a prose-only skill with no checkable claim has nothing to
re-derive and is out of scope for this gate (disclosed in DISCOVERY.md). The
adapter adds no trust logic; it only places the existing binding's call at the
admission point and maps the verdict to Hermes's contract.
"""

from __future__ import annotations

from pathlib import Path

from relyable.skills import (
    ADMIT,
    AdmissionVerdict,
    admit_directory,
    rederive,
    usable_skills,
)

from .config import HermesGuardConfig


def admission_reason(verdict: AdmissionVerdict) -> str:
    """Render a rejected skill's verdict as the drop string Hermes logs/returns."""
    flag = " (forged VALIDATED label)" if verdict.forged_label else ""
    return (
        f"relyable: skill {verdict.skill_id!r} did not re-derive "
        f"[{verdict.reason_code}]{flag}: {verdict.detail}"
    )


def rederive_skill_guard(
    skill_dir: Path,
    config: HermesGuardConfig,
) -> str | None:
    """Hermes ``_security_scan_skill``-shaped guard for one skill bundle.

    Returns ``None`` to admit (the skill re-derived) or an error string to drop it
    (Hermes's caller ``shutil.rmtree``s the directory on a non-empty return). This
    is the one call a Hermes integrator adds to ``_security_scan_skill`` /
    ``_create_skill``.
    """
    verdict = rederive(
        skill_dir,
        grader_src=config.grader_src,
        permit_execution=config.permit_execution,
        pack_filename=config.pack_filename,
        grader_principal=config.grader_principal,
        require_separation=config.require_separation,
        artifact_principal=config.session_principal,
        sandbox=config.sandbox,
    )
    if verdict.verdict == ADMIT:
        return None
    return admission_reason(verdict)


def admit_registry(
    registry_dir: Path,
    config: HermesGuardConfig,
) -> list[AdmissionVerdict]:
    """Re-derive every skill bundle under ``registry_dir`` (audit trail: every
    verdict, admitted and rejected alike)."""
    return admit_directory(
        registry_dir,
        grader_src=config.grader_src,
        permit_execution=config.permit_execution,
        pack_filename=config.pack_filename,
        grader_principal=config.grader_principal,
        require_separation=config.require_separation,
        artifact_principal=config.session_principal,
        sandbox=config.sandbox,
    )


def usable(
    registry_dir: Path,
    config: HermesGuardConfig,
) -> list[AdmissionVerdict]:
    """The only thing the adapter exposes to Hermes's skill loader: the skills
    veriker re-derived (verdict == ADMIT). Fail-closed — a skill not affirmatively
    re-derived is simply absent, never surfaced with a warning."""
    return usable_skills(admit_registry(registry_dir, config))
