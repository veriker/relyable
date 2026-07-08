"""learn_guard.py — re-derivation gate for Hermes ``/learn`` skill *distillation*.

## Why a separate guard from ``guard.py``

``guard.py::rederive_skill_guard`` expects ``skill_dir`` to ALREADY be a veriker
bundle (``manifest.json`` + ``skill/`` + the pinned grader). Hermes ``/learn``
(upstream commit ``e32ebc6aa``, PR #51506) does not produce a bundle — it has the
live agent author a raw ``SKILL.md`` tree (``SKILL.md`` + optional ``scripts/``)
and save it via ``skill_manage`` ``action="create"``, which lands in the SAME
``_security_scan_skill`` chokepoint ``guard.py`` targets. So the only missing piece
is the producer-side packaging step: raw ``/learn`` skill dir -> veriker bundle ->
re-derive. This module is that shim, and nothing more — the packaging itself is the
shared native seam ``relyable.adapters._skillpack.pack_native_skill``.

## The honesty boundary (this is the whole point — do NOT lose it)

``/learn``'s authoring standard mandates a ``## Verification`` section ("a single
command/check that proves the skill worked"). That command is SELF-AUTHORED: the
same model, from the same sources, that wrote the skill. It is a textbook self-spec,
and relyable's own finding (``relyable/skills/self_spec.py``) is that self-authored
specs catch the author's blind spots at A~=0. Running the agent's own
``## Verification`` line and admitting on green would REPRODUCE the
author=executor=inspector gap Hermes #25833 names and relyable exists to close —
i.e. theater.

So this guard travels ``## Verification`` in the bundle as an UNTRUSTED hint
(``skill/meta.json::invocation.self_authored_check``) for the audit trail, and never
lets it decide. The decision is exactly what ``relyable.gate`` enforces: re-derive
the skill's OWN entrypoint against the CONSUMER's pinned grader (``grader_src``, no
default — held-out goldens), env-clean, with separation of duties (the host-attested
``session_principal`` must differ from the grader's author). A skill whose
``## Verification`` is green but whose entrypoint fails the consumer's held-out
goldens is dropped anyway — that case is the A~=0 self-spec blind spot, caught.

## Scope + the out-of-scope policy (honest, not net-negative)

Re-derivation has teeth only on a skill that carries an executable oracle (an
entrypoint with a definable I/O contract — the scrape/convert/SQL/codegen class).
A pure-PROSE ``/learn`` skill (no script) has nothing to re-derive;
``_skillpack.detect_invocation`` raises ``OutOfScope`` for it.

This guard does NOT drop an out-of-scope skill: relyable has no re-derivation basis
to reject it, so asserting a verdict would be dishonest (TRUTHFULNESS rule 4 —
don't claim a capability you don't have). It ABSTAINS (returns ``None`` => Hermes
keeps it). It drops ONLY a skill it can judge that FAILS. The strict posture
("admit ONLY affirmatively re-derived skills") lives in the batch ``usable`` /
registry path, not in this inline single-skill write-guard. ``OutOfScope`` is
visible to the caller via ``package_learned_skill`` for a consumer that wants the
strict behavior.

## What this does NOT solve (stated honestly)

Grader-provisioning is unchanged: ``relyable.gate`` has no default grader; the
held-out golden is the consumer's, per-domain. ``/learn`` raises the COUNT of skills
carrying a structured claim; it does not supply a trust root. See
``LEARN_INTEGRATION_SCOPE.md``.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from relyable.adapters._skillpack import (
    OutOfScope,
    detect_invocation,
    parse_frontmatter,
)
from relyable.skills import ADMIT, rederive
from relyable.skills.bundle import build_native_skill_bundle

from .config import HermesGuardConfig
from .guard import admission_reason

# A level-2 ``## Verification`` heading, capturing its body up to the next
# level-1/level-2 heading or EOF. Case-insensitive on the word "Verification".
_VERIFICATION_RE = re.compile(
    r"^##\s+verification\s*$\n(.*?)(?=^#{1,2}\s|\Z)",
    re.MULTILINE | re.IGNORECASE | re.DOTALL,
)

_SKILL_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

# Recorded alongside the lifted ``## Verification`` so the bundle itself documents
# that the check is the agent's own and is NOT the gate's arbiter.
SELF_CHECK_SOURCE = "hermes-learn:## Verification (self-authored, UNTRUSTED)"


def _find_skill_md(skill_dir: Path) -> Path | None:
    """Locate the SKILL.md Hermes just wrote (uppercase by convention; tolerate case)."""
    canonical = skill_dir / "SKILL.md"
    if canonical.is_file():
        return canonical
    for p in sorted(skill_dir.glob("*.md")):
        if p.stem.lower() == "skill":
            return p
    return None


def parse_verification(skill_md_text: str) -> str | None:
    """Extract the body of the ``## Verification`` section, or None if absent/empty.

    This is the agent's SELF-AUTHORED check. It is returned so the caller can travel
    it in the bundle as an untrusted hint — it is never executed as the gate's
    decision (see the module honesty boundary).
    """
    m = _VERIFICATION_RE.search(skill_md_text)
    if not m:
        return None
    body = m.group(1).strip()
    return body or None


def _skill_id(skill_dir: Path, frontmatter: dict) -> str:
    raw = str(frontmatter.get("name") or skill_dir.name)
    return _SKILL_ID_SAFE.sub("-", raw).strip("-") or "learned-skill"


def package_learned_skill(
    skill_dir: Path,
    dest: Path,
    config: HermesGuardConfig,
) -> Path:
    """Package a raw Hermes ``/learn`` skill tree into a veriker bundle at ``dest``.

    Reuses the shared native seam: ``_skillpack.detect_invocation`` runs the scope
    gate (raising ``OutOfScope`` for a prose-only / ambiguous / off-allowlist skill)
    and resolves the entrypoint+runner the consumer's grader will execute. The
    ``## Verification`` text is lifted and recorded as an UNTRUSTED hint inside the
    invocation meta (``self_authored_check``); the entrypoint, not the check, is what
    the grader re-derives. ``session_principal`` is stamped as the producing
    principal (L0 meta author; the stronger L1 stamp is applied at re-derivation
    time). Returns ``dest``.

    Raises ``FileNotFoundError`` if the directory carries no SKILL.md, or
    ``OutOfScope`` if the skill has no executable oracle to re-derive.
    """
    skill_md = _find_skill_md(skill_dir)
    if skill_md is None:
        raise FileNotFoundError(f"no SKILL.md in {skill_dir}")
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    frontmatter = parse_frontmatter(text)

    invocation = detect_invocation(skill_dir, frontmatter).to_meta()
    verification = parse_verification(text)
    if verification is not None:
        invocation["self_authored_check"] = verification
        invocation["self_authored_check_source"] = SELF_CHECK_SOURCE

    skill_id = _skill_id(skill_dir, frontmatter)
    return build_native_skill_bundle(
        dest,
        skill_id=skill_id,
        kind=skill_id,  # per-skill goldens — the consumer's grader keys on this
        artifact_dir=skill_dir,
        grader_src=config.grader_src,
        invocation=invocation,
        author_principal=config.session_principal,
    )


def rederive_learned_skill_guard(
    skill_dir: Path,
    config: HermesGuardConfig,
) -> str | None:
    """``_security_scan_skill``-shaped guard for a ``/learn``-distilled skill dir.

    Drop-in twin of ``guard.py::rederive_skill_guard`` for the case where the
    chokepoint receives a RAW ``/learn`` skill tree rather than a pre-built bundle:
    it packages the tree (lifting ``## Verification`` as an untrusted hint) and
    re-derives the skill's entrypoint against the consumer's grader.

    Returns ``None`` to admit or an error string to drop (Hermes ``shutil.rmtree``s
    the directory on a non-empty return). Drop semantics, all honest:

      * IN-SCOPE skill whose entrypoint does NOT reproduce the consumer's goldens
        (forged self-check / broken / unverifiable under permit_execution) -> DROP.
      * OUT-OF-SCOPE skill (prose-only, no oracle) -> ABSTAIN (``None``): relyable
        has no re-derivation basis to reject it (see module docstring).
      * No SKILL.md at all -> DROP (a malformed write, not a learned skill).
    """
    with tempfile.TemporaryDirectory(prefix="relyable-learn-") as td:
        try:
            bundle = package_learned_skill(skill_dir, Path(td) / "bundle", config)
        except FileNotFoundError as e:
            return f"relyable: /learn skill could not be packaged: {e}"
        except OutOfScope:
            # No executable oracle -> relyable abstains rather than assert a verdict
            # it cannot derive. The skill is kept (None); not claimed re-derived.
            return None
        verdict = rederive(
            bundle,
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
