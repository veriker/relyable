"""registry.py — the attested registry: expose ONLY skills veriker re-derives.

Each skill is a real veriker bundle in its own subdirectory. The registry runs
veriker's verifier on every bundle (via ``gate.rederive``) and exposes only those
whose VALIDATED label veriker independently re-derived. A skill veriker does not
pass is absent from the usable table — not present-with-a-warning.

This is the attested-admission shape (admit iff re-derived) where the "root" is a
re-derivation veriker reproduces, not an asserted label. Worst case the registry
is INERT (a fully-poisoned bundle dir yields zero usable skills) rather than
net-negative — the trust label is removed as an attack surface. (ALE Exp 4/5/6:
an unattested registry/cue *degrades* the agent; the re-derivable label only
restores the baseline.)
"""

from __future__ import annotations

from pathlib import Path

from relyable.verdicts.sandbox import Sandbox

from .gate import ADMIT, AdmissionVerdict, rederive


def admit_directory(
    registry_dir: Path,
    *,
    grader_src: Path,
    permit_execution: bool,
    pack_filename: str | None = None,
    grader_principal: str | None = None,
    require_separation: bool = False,
    artifact_principal: str | None = None,
    sandbox: Sandbox | None = None,
    sandbox_timeout: float | None = None,
) -> list[AdmissionVerdict]:
    """Re-derive every veriker skill bundle under ``registry_dir`` (one subdir per
    skill, each with a manifest.json) against the consumer's ``grader_src``.
    Returns one verdict per skill (admitted and rejected alike) for the audit
    trail.

    ``grader_principal`` + ``require_separation`` opt into the separation-of-duties
    check (a skill whose producing principal equals ``grader_principal`` is rejected
    before the grader runs). ``artifact_principal`` (host/harness-attested) overrides
    each bundle's meta principal for the whole batch — use it when one session
    authored every skill in the directory. ``sandbox`` (opt-in) runs each
    re-derivation behind a ``Sandbox``; the isolation used is stamped on each
    verdict (``isolation_level``). None = in-process (host is the boundary)."""
    verdicts: list[AdmissionVerdict] = []
    for sub in sorted(p for p in registry_dir.iterdir() if p.is_dir()):
        if not (sub / "manifest.json").is_file():
            continue
        verdicts.append(
            rederive(
                sub,
                grader_src=grader_src,
                permit_execution=permit_execution,
                pack_filename=pack_filename,
                grader_principal=grader_principal,
                require_separation=require_separation,
                artifact_principal=artifact_principal,
                sandbox=sandbox,
                sandbox_timeout=sandbox_timeout,
            )
        )
    return verdicts


def usable_skills(verdicts: list[AdmissionVerdict]) -> list[AdmissionVerdict]:
    """The skills a consumer may use: verdict == ADMIT only. Fail-closed —
    anything not affirmatively re-derived is excluded."""
    return [v for v in verdicts if v.verdict == ADMIT]
