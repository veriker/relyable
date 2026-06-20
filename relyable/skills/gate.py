"""gate.py — the skills admission gate, standing on relyable.gate / veriker.

The gate does not re-implement the re-derivation doctrine. It hands each skill
bundle to veriker's OWN verifier (via ``relyable.gate.verify_attested_bundle``)
and maps the resulting ``Verdict`` to an ADMIT/REJECT decision:

    res = verify_attested_bundle(bundle_dir, grader_src=..., permit_execution=...)
    ADMIT iff res.ok

Everything that makes the verdict trustworthy — the strict-SHA digest rail over
the manifest, the sealed-snapshot read, the fail-closed dispatch, the
``permit_execution`` gate, and the could-not-conclude semantics — is veriker's,
imported through ``relyable.gate``, not reproduced here. The candidate skill is
executed inside veriker's gated pack lane (the grader the consumer pinned), the
only lane that may run bundle-supplied code.

``claimed_verdict`` (from skill/meta.json) is read ONLY to flag a forged label
for the audit trail; it never contributes to the decision and is never a
fallback. A poisoned bundle therefore stays inert: with ``permit_execution=False``
every skill is could-not-conclude (not OK -> not admitted); with
``permit_execution=True`` a wrong/broken/raising skill yields a re-derivation
mismatch (not OK -> not admitted), and the producer cannot ship a lying grader
because ``relyable.gate`` pins the bundle's grader to the consumer's trusted copy.

The grader (``grader_src``) is the consumer's trust root and is a required
argument — there is no built-in default, because the held-out goldens that decide
"does this skill re-derive" are domain-specific and must be the consumer's own.
See ``relyable/skills/examples/interval_grader.py`` for a worked grader.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from relyable.gate import verify_attested_bundle
from relyable.verdicts.sandbox import Sandbox

ADMIT = "ADMIT"
REJECT = "REJECT"

# The single stdout line the sandbox worker emits and the parent scans for. Defined
# here (the parser side) so the worker imports it from gate, not the reverse —
# otherwise running ``python -m relyable.skills._sandbox_worker`` double-imports the
# worker (once during package init via gate, once as __main__) and warns.
VERDICT_SENTINEL = "RELYABLE_VERDICT_JSON:"


@dataclass(frozen=True, slots=True)
class AdmissionVerdict:
    """The re-derived verdict for one skill. ``verdict`` (ADMIT/REJECT) is the
    only thing the registry acts on; it is veriker's ``verify().ok``.
    ``rederived_label`` is the gate's independent conclusion; ``forged_label``
    flags a claimed VALIDATED that the re-derivation contradicts."""

    skill_id: str
    kind: str
    verdict: str
    reason_code: str
    detail: str
    rederived_label: str  # "VALIDATED" | "REJECTED" | "UNVERIFIED"
    claimed_verdict: str  # echoed for the audit trail (NOT used in the decision)
    forged_label: bool
    # Where the artifact's principal came from for the separation check: "host"
    # (host/harness-attested, the stronger L1 source), "meta" (bundle-supplied,
    # the weaker L0 source — forgeable), or "none" (no principal / separation off).
    # Audit honesty: never read an L1-strength guarantee off an L0 (meta) signal.
    principal_source: str = "none"
    # Isolation the re-derivation ran behind: "host" (relyable applied none — the
    # host/CI/managed-agent is responsible, the zero-overhead common case),
    # "subprocess" (an extra process boundary; NOT a security boundary), or
    # "container". Same honesty rule: a host-isolation admission must not read as a
    # container-isolation one.
    isolation_level: str = "host"


def _read_meta(bundle_dir: Path) -> dict:
    try:
        return json.loads(
            (bundle_dir / "skill" / "meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}


def rederive(
    bundle_dir: Path,
    *,
    grader_src: Path,
    permit_execution: bool,
    pack_filename: str | None = None,
    grader_principal: str | None = None,
    require_separation: bool = False,
    artifact_principal: str | None = None,
    sandbox: Sandbox | None = None,
    sandbox_timeout: float | None = None,
) -> AdmissionVerdict:
    """Re-derive one skill's admission through veriker.

    ``grader_src`` is the consumer's trusted grader (held-out goldens + reference
    solver); ``relyable.gate`` digest-pins the bundle's grader against it, so a
    hand-assembled bundle naming a lying grader cannot be admitted.

    ``permit_execution`` is the consumer's explicit trust decision (no default,
    mirroring veriker): False = won't run untrusted code (the skill stays
    could-not-conclude / unadmitted); True = vet by running the candidate on a
    disposable host.

    ``require_separation`` (opt-in) enforces separation of duties: the skill's
    producing principal must differ from ``grader_principal`` (consumer config —
    who authored the grader), or the skill is REJECTED before the grader runs. This
    is the gate-level guard against the same agent writing both a skill and the
    criteria that admit it. See the honesty boundary in
    ``relyable.gate.verify_attested_bundle``.

    The producing principal is resolved with a trust-source preference: an explicit
    ``artifact_principal`` (HOST/harness-attested — the stronger L1 source, e.g. the
    adapter stamping Hermes's session model) OVERRIDES ``author_principal`` from
    skill/meta.json (producer-supplied — the weaker, forgeable L0 source). The
    source actually used is recorded on the verdict (``principal_source``) so the
    audit trail never reads an L1 guarantee off an L0 signal.

    ``sandbox`` (opt-in) runs the WHOLE re-derivation behind a ``Sandbox`` — the
    only honest boundary, because veriker runs the grader pack with a hardcoded
    in-process ``subprocess.run`` that relyable cannot wrap. None (default) runs
    in-process and records ``isolation_level="host"`` (the host/CI/managed agent is
    the boundary — the zero-overhead common case). A ``SubprocessSandbox`` /
    ``ContainerSandbox`` runs an in-sandbox worker and records its label; a
    ContainerSandbox image must carry relyable + veriker and reach the bundle/grader.
    """
    if sandbox is not None:
        return _rederive_sandboxed(
            bundle_dir,
            grader_src=grader_src,
            permit_execution=permit_execution,
            pack_filename=pack_filename,
            grader_principal=grader_principal,
            require_separation=require_separation,
            artifact_principal=artifact_principal,
            sandbox=sandbox,
            sandbox_timeout=sandbox_timeout,
        )
    meta = _read_meta(bundle_dir)
    skill_id = str(meta.get("skill_id", bundle_dir.name))
    kind = str(meta.get("kind", "?"))
    claimed = str(meta.get("claimed_verdict", ""))
    meta_principal = meta.get("author_principal") or None
    if artifact_principal is not None:
        effective_principal, principal_source = artifact_principal, "host"
    elif meta_principal is not None:
        effective_principal, principal_source = meta_principal, "meta"
    else:
        effective_principal, principal_source = None, "none"

    def _verdict(v, code, detail, rederived):
        forged = (claimed == "VALIDATED") and (rederived == "REJECTED")
        return AdmissionVerdict(
            skill_id=skill_id,
            kind=kind,
            verdict=v,
            reason_code=code,
            detail=detail,
            rederived_label=rederived,
            claimed_verdict=claimed,
            forged_label=forged,
            principal_source=principal_source,
        )

    # Grader-pin + veriker verify via the shared gate (fail-closed BEFORE we trust
    # any verify().ok): the grader the verifier runs MUST be byte-identical to the
    # consumer's own, so a hand-assembled bundle naming a lying exit(0) grader
    # cannot be admitted. relyable.gate owns the pin + dispatch; this gate owns
    # only the ADMIT/REJECT + forged-label mapping below.
    res = verify_attested_bundle(
        bundle_dir,
        grader_src=grader_src,
        pack_filename=pack_filename,
        permit_execution=permit_execution,
        artifact_principal=effective_principal,
        grader_principal=grader_principal,
        require_separation=require_separation,
    )
    if not res.separation_ok:
        # Separation of duties failed: the producing principal and the grader's
        # author could not be shown distinct. Fail-closed BEFORE the grader runs;
        # not a forgery finding (the re-derivation never ran).
        return _verdict(
            REJECT,
            res.separation_reason_code or "SAME_PRINCIPAL",
            f"separation of duties: {res.separation_reason_code}",
            "UNVERIFIED",
        )
    if not res.grader_ok:
        # Grader absent / not the consumer's trusted copy: could-not-trust, not a
        # forgery finding (the re-derivation never ran). Fail-closed.
        return _verdict(
            REJECT, res.grader_reason_code or "NO_GRADER", res.detail, "UNVERIFIED"
        )

    detail = res.detail
    if res.ok:
        # OK from a bundle that carries the pinned grader, with execution
        # permitted, means the grader exited 0 = RE_DERIVED.
        v, rederived, code = ADMIT, "VALIDATED", "RE_DERIVED"
        detail = "veriker re-derivation OK (held-out reproduced)"
    elif res.is_error:
        # Could-not-conclude (e.g. permit_execution=False). NOT admitted
        # (fail-closed), but NOT a forgery finding — the re-derivation never ran,
        # so it never contradicted the claim.
        v, rederived = REJECT, "UNVERIFIED"
        code = res.first_reason_code or "VERIFIER_INCOMPLETE"
    else:
        # State REJECT: veriker actively re-derived and CONTRADICTED the bundle
        # (mismatch / bad_file_sha / structural reject).
        v, rederived = REJECT, "REJECTED"
        code = res.first_reason_code or "REJECTED"

    return _verdict(v, code, detail, rederived)


def _rederive_sandboxed(
    bundle_dir: Path,
    *,
    grader_src: Path,
    permit_execution: bool,
    pack_filename: str | None,
    grader_principal: str | None,
    require_separation: bool,
    artifact_principal: str | None,
    sandbox: Sandbox,
    sandbox_timeout: float | None,
) -> AdmissionVerdict:
    """Run the worker inside ``sandbox`` and reconstruct its verdict, stamped with
    the isolation the sandbox actually provided. Fail-closed: any worker that does
    not emit a parseable verdict is a REJECT, never an admit.

    Paths are passed absolute. For ``SubprocessSandbox`` (same host) they resolve as
    is. For ``ContainerSandbox`` the bundle dir + grader must be reachable at those
    paths inside the container and the image must carry relyable + veriker; mapping
    arbitrary host paths into the mount is a documented follow-up, not done here.
    """
    skill_id = str(_read_meta(bundle_dir).get("skill_id", bundle_dir.name))

    def _fail(code: str, detail: str) -> AdmissionVerdict:
        return AdmissionVerdict(
            skill_id=skill_id,
            kind="?",
            verdict=REJECT,
            reason_code=code,
            detail=detail,
            rederived_label="UNVERIFIED",
            claimed_verdict="",
            forged_label=False,
            isolation_level=sandbox.label,
        )

    cmd = [
        sys.executable,
        "-m",
        "relyable.skills._sandbox_worker",
        "--bundle-dir",
        str(bundle_dir),
        "--grader-src",
        str(grader_src),
    ]
    if pack_filename:
        cmd += ["--pack-filename", pack_filename]
    if permit_execution:
        cmd.append("--permit-execution")
    if grader_principal:
        cmd += ["--grader-principal", grader_principal]
    if require_separation:
        cmd.append("--require-separation")
    if artifact_principal:
        cmd += ["--artifact-principal", artifact_principal]

    result = sandbox.run(cmd, cwd=bundle_dir, timeout=sandbox_timeout)
    if result.timed_out:
        return _fail("SANDBOX_TIMEOUT", f"sandbox ({sandbox.label}) timed out")
    line = next(
        (
            ln[len(VERDICT_SENTINEL) :]
            for ln in result.stdout.splitlines()
            if ln.startswith(VERDICT_SENTINEL)
        ),
        None,
    )
    if line is None:
        tail = (result.stderr or result.stdout or "").strip()[-300:]
        return _fail(
            "SANDBOX_NO_VERDICT",
            f"sandbox ({sandbox.label}) emitted no verdict (rc={result.returncode}): "
            f"...{tail}",
        )
    try:
        data = json.loads(line)
    except ValueError as e:
        return _fail("SANDBOX_BAD_VERDICT", f"unparseable worker verdict: {e}")
    # The worker ran in-sandbox (isolation_level "host" from ITS view); overwrite
    # with the isolation the sandbox actually provided from OUR view.
    data["isolation_level"] = sandbox.label
    return AdmissionVerdict(**data)
