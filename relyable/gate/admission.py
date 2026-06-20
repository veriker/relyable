"""admission.py — relyable's shared re-derivation admission gate.

ONE home for the domain-agnostic boilerplate that relyable's trust-surface
bindings (skills, memory) consume to admit only what re-derives:

  - build_attested_bundle(...)  — assemble a real vcp-v1.1 veriker bundle
    (skill/candidate.py + skill/meta.json + a gate-installed grader pack +
    digest-bound manifest declaring re_derivation_invocation).
  - verify_attested_bundle(...) — digest-PIN the bundle's grader against the
    consumer's trusted copy, then run veriker's own BundleVerifier over the
    gated re_derivation_invocation pack lane, and return a structured result.

What STAYS with each binding (domain-specific, NOT here):
  - the grader pack itself (the held-out construction + candidate evaluation);
  - the meta dict shape and the ADMIT/REJECT mapping over the veriker Verdict.

This module is a genuine veriker CONSUMER — it imports only the public veriker
verify surface (``BundleVerifier`` + the re-derivation plugin). The substrate
ships as the ``veriker`` package, a declared dependency, which provides the
``audit_bundle`` import this gate re-derives through.

NOTE for the next builder: this module does NOT emit a down-channel event — the
L→V event emission lives in the binding/demo layer, not in the admission gate.
There is no event call to drop here when the skills/memory bindings are built.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# The veriker substrate (a declared dependency) provides ``audit_bundle``.
from audit_bundle.plugins.re_derivation_invocation import ReDerivationInvocationCheck
from audit_bundle.verdict import Verdict, VerdictState
from audit_bundle.verifier import BundleVerifier

# Fixed, in-the-past build timestamp (deterministic bundles; mirrors the veriker
# soak examples' literal created_at — a re-derivation bundle is not time-bearing).
DEFAULT_CREATED_AT = "2026-06-13T00:00:00Z"

# Grader-pin reason codes (consumer-facing; distinct from veriker's own codes).
NO_GRADER = "NO_GRADER"
GRADER_MISMATCH = "GRADER_MISMATCH"

# Separation-of-duties reason codes. The principal that PRODUCED an artifact must
# not be the principal that AUTHORED the grader that judges it — otherwise the
# trust root is circular ("the same agent grading its own homework"). See the
# `require_separation` branch of verify_attested_bundle for the honesty boundary.
SAME_PRINCIPAL = "SAME_PRINCIPAL"
MISSING_PRINCIPAL = "MISSING_PRINCIPAL"


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_attested_bundle(
    dest: Path,
    *,
    candidate_body: str | None = None,
    artifact_dir: Path | None = None,
    meta: dict,
    grader_src: Path,
    bundle_id: str,
    pack_filename: str | None = None,
    created_at: str = DEFAULT_CREATED_AT,
) -> Path:
    """Assemble a real vcp-v1.1 veriker bundle at `dest`. Provide EXACTLY ONE of
    `candidate_body` or `artifact_dir`:

    single-body mode (`candidate_body`, the default) — a one-file Python candidate:
        skill/candidate.py          the candidate body (digest-bound)
        skill/meta.json             `meta` (consumer-shaped; e.g. {skill_id, kind})
        re_derive/<pack_filename>   the grader, ALWAYS copied from `grader_src`

    artifact-tree mode (`artifact_dir`) — a native multi-file / non-Python skill
    (e.g. a ClawHub SKILL.md + scripts). The whole tree is copied verbatim under
    `skill/` and every file digest-bound, so the grader can run the skill's own
    entrypoint instead of importing a single candidate.py:
        skill/<every file in artifact_dir>   the native skill, verbatim
        skill/meta.json             `meta` (overwrites any meta.json in the tree —
                                    the consumer's meta is authoritative)
        re_derive/<pack_filename>   the grader, ALWAYS copied from `grader_src`

    In both modes the grader is copied from `grader_src` (the consumer's trusted
    copy; never producer-supplied) so a poisoned bundle cannot ship a lying pack.
    `pack_filename` defaults to grader_src.name. The manifest declares
    `re_derivation_invocation` and digest-binds every file (the producer computes
    the digests to BUILD the bundle; veriker's strict-SHA walk independently
    re-checks them — that walk, not this builder, is the trust rail). Returns dest.
    """
    if (candidate_body is None) == (artifact_dir is None):
        raise ValueError(
            "build_attested_bundle: pass exactly one of candidate_body or artifact_dir"
        )
    pack = pack_filename or grader_src.name
    skill_dir = dest / "skill"
    rederive_dir = dest / "re_derive"
    skill_dir.mkdir(parents=True, exist_ok=True)
    rederive_dir.mkdir(parents=True, exist_ok=True)

    if artifact_dir is not None:
        # Copy the native skill tree verbatim under skill/ (dirs_exist_ok so a
        # caller may pre-create skill_dir). The consumer's meta.json, written
        # next, is authoritative and overwrites any meta.json shipped in the tree.
        shutil.copytree(artifact_dir, skill_dir, dirs_exist_ok=True)
    else:
        assert candidate_body is not None  # guaranteed by the exactly-one check above
        (skill_dir / "candidate.py").write_text(candidate_body, encoding="utf-8")
    (skill_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
    )
    shutil.copyfile(grader_src, rederive_dir / pack)

    # Digest-bind every file actually present under skill/ (recursively) plus the
    # grader. In artifact-tree mode this covers the whole native skill; in
    # single-body mode it is exactly {candidate.py, meta.json}.
    files = {
        f"skill/{p.relative_to(skill_dir).as_posix()}": file_digest(p)
        for p in sorted(skill_dir.rglob("*"))
        if p.is_file()
    }
    files[f"re_derive/{pack}"] = file_digest(rederive_dir / pack)
    manifest = {
        "schema_version": "vcp-v1.1",
        "bundle_id": bundle_id,
        "created_at": created_at,
        "files": files,
        "spec_files": {},
        "cross_refs": {},
        "payload": {},
        "typed_checks": ["re_derivation_invocation"],
        "per_output_manifests": [],
        "dispatch_records": [],
        "aggregate_stamp": None,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return dest


def flatten_reasons(verdict) -> list:
    """All VerdictReason across a veriker Verdict and its legs (depth-first)."""
    out = list(getattr(verdict, "reasons", ()) or ())
    for leg in getattr(verdict, "legs", ()) or ():
        out.extend(flatten_reasons(leg))
    return out


@dataclass(frozen=True, slots=True)
class AttestedVerifyResult:
    """Structured result of pin-and-verify. Each consumer maps this to its own
    ADMIT/REJECT vocabulary; the shared layer never decides the consumer's label.

    grader_ok=False means the bundle's grader failed the digest-pin (the veriker
    Verdict was never run); `grader_reason_code` is NO_GRADER / GRADER_MISMATCH.
    Otherwise `verdict` is the raw veriker Verdict and the convenience accessors
    (`ok`, `is_error`, `first_reason_code`, `detail`) summarize it.
    """

    grader_ok: bool
    grader_reason_code: str | None
    verdict: Verdict | None  # raw veriker Verdict, or None when grader_ok is False
    reasons: tuple = field(default_factory=tuple)
    # Separation-of-duties pre-check (only meaningful when require_separation=True;
    # otherwise always (True, None) and the gate behaves exactly as before).
    # separation_ok=False means the artifact's claimed author and the grader's
    # author could not be shown distinct — the verdict was never run.
    separation_ok: bool = True
    separation_reason_code: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.verdict is not None and self.verdict.ok)

    @property
    def is_error(self) -> bool:
        """Veriker could-not-conclude (ERROR state, e.g. RE_DERIVATION_NOT_EXECUTED)."""
        return self.verdict is not None and self.verdict.state is VerdictState.ERROR

    @property
    def first_reason_code(self) -> str | None:
        return self.reasons[0].reason_code if self.reasons else None

    @property
    def detail(self) -> str:
        if self.verdict is None:
            return self.grader_reason_code or "grader pin failed"
        return (
            "; ".join(
                f"[{getattr(r, 'check_name', '')}] {r.reason_code}: {r.detail}"
                for r in self.reasons[:3]
            )
            or "not OK"
        )


@contextlib.contextmanager
def _pythonpath(extra: str | None):
    """Temporarily prepend `extra` to PYTHONPATH (for a grader subprocess that
    must import a consumer's trusted harness). Verifier-side, never bundle-set."""
    if not extra:
        yield
        return
    prev = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join([extra, prev or ""])
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prev


def verify_attested_bundle(
    bundle_dir: Path,
    *,
    grader_src: Path,
    pack_filename: str | None = None,
    permit_execution: bool,
    env_pythonpath: str | None = None,
    artifact_principal: str | None = None,
    grader_principal: str | None = None,
    require_separation: bool = False,
) -> AttestedVerifyResult:
    """Digest-pin the bundle's grader against `grader_src`, then run veriker's
    BundleVerifier over the gated re_derivation_invocation pack lane.

    The grader-pin is fail-closed BEFORE any verify().ok is trusted: the grader
    the verifier will run MUST be byte-identical to `grader_src`. An absent grader
    would make veriker return NO_PACK (ok=True) and never grade the candidate (a
    spurious OK); a bundle shipping a lying exit(0) grader with a self-consistent
    manifest would otherwise pass. Pinning here makes a trusted verdict impossible
    unless the consumer's OWN grader graded the candidate — so this is safe for ANY
    directory, not only bundles the consumer itself built.

    `env_pythonpath` is prepended to PYTHONPATH around the verify call for a grader
    that imports a consumer harness (verifier-side, never bundle-supplied).

    Separation of duties (opt-in via `require_separation=True`): refuse, fail-closed
    and BEFORE the grader even runs, when the artifact's producing principal and the
    grader's authoring principal cannot be shown distinct. This is the mechanical
    answer to "the same agent must never write its own pass criteria": an agent
    cannot both author a skill and author the grader that admits it.

      - `artifact_principal` — who produced the candidate (e.g. a model id). For the
        skills binding it flows from `skill/meta.json` ("author_principal").
      - `grader_principal`  — who authored the grader. Consumer config — it travels
        with the grader the consumer pinned, so it is trusted to the same degree as
        the grader bytes themselves.

    HONESTY BOUNDARY (do not overclaim): `artifact_principal` is producer-supplied,
    so this check defends against *accidental* circularity (the common real case:
    one model authors and grades) and gives the audit trail a separation signal. It
    is NOT a cryptographic identity proof — a producer that LIES about its principal
    can evade the equality test. That liar still cannot pass the gate, because the
    re-derivation itself (the grader the consumer pinned, run on a disposable host)
    is the load-bearing defense; separation is a second, independent rail, not a
    replacement for it.
    """
    if require_separation:
        if not artifact_principal or not grader_principal:
            return AttestedVerifyResult(
                grader_ok=False,
                grader_reason_code=None,
                verdict=None,
                separation_ok=False,
                separation_reason_code=MISSING_PRINCIPAL,
            )
        if artifact_principal == grader_principal:
            return AttestedVerifyResult(
                grader_ok=False,
                grader_reason_code=None,
                verdict=None,
                separation_ok=False,
                separation_reason_code=SAME_PRINCIPAL,
            )

    pack = pack_filename or grader_src.name
    grader = bundle_dir / "re_derive" / pack
    if not grader.is_file():
        return AttestedVerifyResult(False, NO_GRADER, None)
    if file_digest(grader) != file_digest(grader_src):
        return AttestedVerifyResult(False, GRADER_MISMATCH, None)

    with _pythonpath(env_pythonpath):
        verdict = BundleVerifier(
            [
                ReDerivationInvocationCheck(
                    pack_filename=pack, permit_execution=permit_execution
                )
            ]
        ).verify(bundle_dir)
    return AttestedVerifyResult(True, None, verdict, tuple(flatten_reasons(verdict)))
