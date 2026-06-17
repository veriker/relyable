"""installpolicy.py — relyable as an OpenClaw ``security.installPolicy`` command.

OpenClaw runs a trusted local policy command after staging a skill/plugin and
before the install continues. This wires relyable's re-derivation gate into that
chokepoint: pack the staged native skill into a veriker bundle, re-derive it against
the consumer's grader, and answer allow/block. No fork — the operator just points
``security.installPolicy.exec.command`` at the ``relyable-installpolicy`` console
script.

PROTOCOL (OpenClaw security.installPolicy, protocolVersion 1):
  stdin  — one JSON object: {protocolVersion, openclawVersion, targetType,
           targetName, sourcePath, sourcePathKind, source, origin, request, skill}.
  stdout — one JSON object: {"protocolVersion": 1, "decision": "allow"} or
           {"protocolVersion": 1, "decision": "block", "reason": "..."}.
  Fail-closed: OpenClaw treats a non-zero exit / timeout / malformed JSON / missing
  fields / unsupported protocolVersion as BLOCK. This command therefore always emits
  a well-formed decision and never raises past `main`.

WHAT IT ADJUDICATES (honest scope): only ``targetType=="skill"`` with a known grader
kind and a locatable executable entrypoint. Everything it cannot judge — plugins,
unknown kinds, prose-only skills (OutOfScope) — is governed by
``RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE`` (default ``block``, fail-closed; set
``allow`` to make this a purely-functional gate that only blocks what it proves
non-conformant). This is a CONSUMER-SPEC CONFORMANCE gate, not a security scanner —
run it alongside ClawScan/VirusTotal, not instead of them.

CONFIG (env, via security.installPolicy.exec.env / passEnv):
  RELYABLE_INSTALLPOLICY_GRADER          (required) consumer's trusted grader path.
  RELYABLE_INSTALLPOLICY_KIND_MAP        (optional) JSON {slug: kind} mapping a skill
                                         slug to the grader kind; default = the slug.
  RELYABLE_INSTALLPOLICY_PERMIT_EXECUTION (optional) "0" disables running the skill
                                         (then every skill is could-not-conclude ->
                                         unjudgeable); default on — this gate vets BY
                                         running the entrypoint, so the operator must
                                         configure exec in a sandboxed/trusted host.
  RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE  "block" (default) | "allow".
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROTOCOL_VERSION = 1


def _allow() -> dict:
    return {"protocolVersion": PROTOCOL_VERSION, "decision": "allow"}


def _block(reason: str) -> dict:
    return {"protocolVersion": PROTOCOL_VERSION, "decision": "block", "reason": reason}


def _unjudgeable(env: dict, reason: str) -> dict:
    """Decision for a target this gate cannot adjudicate, per operator policy."""
    mode = (env.get("RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE") or "block").lower()
    if mode == "allow":
        return _allow()
    return _block(f"unjudgeable ({reason}); ON_UNJUDGEABLE=block")


def run(stdin_text: str, env: dict) -> dict:
    """Pure core: map one installPolicy request (JSON text) to a decision dict.
    Never raises — every failure path returns a well-formed allow/block decision."""
    try:
        req = json.loads(stdin_text)
    except ValueError as e:
        return _block(f"malformed request JSON: {e}")
    if not isinstance(req, dict):
        return _block("request was not a JSON object")
    if req.get("protocolVersion") != PROTOCOL_VERSION:
        return _block(f"unsupported protocolVersion {req.get('protocolVersion')!r}")

    if req.get("targetType") != "skill":
        return _unjudgeable(env, f"targetType={req.get('targetType')!r} (skills only)")

    source_path = req.get("sourcePath")
    if not source_path or not Path(source_path).is_dir():
        return _block(f"sourcePath not a readable directory: {source_path!r}")

    grader = env.get("RELYABLE_INSTALLPOLICY_GRADER")
    if not grader or not Path(grader).is_file():
        # Misconfiguration is fail-closed: a gate with no trust root must not allow.
        return _block(f"RELYABLE_INSTALLPOLICY_GRADER missing/unreadable: {grader!r}")
    grader_src = Path(grader)

    origin = req.get("origin") or {}
    slug = str(origin.get("slug") or req.get("targetName") or Path(source_path).name)
    kind = slug
    raw_map = env.get("RELYABLE_INSTALLPOLICY_KIND_MAP")
    if raw_map:
        try:
            kind = str((json.loads(raw_map) or {}).get(slug, slug))
        except ValueError:
            return _block("RELYABLE_INSTALLPOLICY_KIND_MAP is not valid JSON")

    permit = (env.get("RELYABLE_INSTALLPOLICY_PERMIT_EXECUTION") or "1") != "0"

    # Local imports: keep startup light and the module importable without the gate
    # stack until a real request arrives.
    from relyable.adapters._skillpack import OutOfScope, pack_native_skill
    from relyable.skills import ADMIT, rederive

    with tempfile.TemporaryDirectory(prefix="relyable-installpolicy-") as td:
        bundle = Path(td) / slug
        try:
            pack_native_skill(
                Path(source_path), bundle, grader_src=grader_src, kind=kind
            )
        except OutOfScope as e:
            return _unjudgeable(env, e.reason_code)
        except OSError as e:
            return _block(f"could not stage skill: {e}")

        verdict = rederive(bundle, grader_src=grader_src, permit_execution=permit)

    if verdict.verdict == ADMIT:
        return _allow()
    if verdict.rederived_label == "REJECTED":
        return _block(
            f"skill did not re-derive ({verdict.reason_code}): {verdict.detail}"
        )
    # Could-not-conclude (e.g. permit_execution off, no goldens) -> unjudgeable.
    return _unjudgeable(env, f"{verdict.reason_code}: {verdict.detail}")


def main() -> int:
    try:
        decision = run(sys.stdin.read(), dict(os.environ))
    except Exception as e:  # noqa: BLE001 — last-resort: still emit a fail-closed block
        decision = _block(f"relyable installpolicy internal error: {type(e).__name__}")
    sys.stdout.write(json.dumps(decision))
    sys.stdout.flush()
    # Exit 0 with an explicit decision is the clean path; the JSON decides. (A
    # non-zero exit would also fail-closed-block, but then the reason is lost.)
    return 0


if __name__ == "__main__":
    sys.exit(main())
