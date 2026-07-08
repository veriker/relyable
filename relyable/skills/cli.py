"""cli.py — the skills surface. ``relyable-skills admit`` / ``relyable-skills init``.

``admit`` drops into a pipeline (or an agent's skill-load step) as an exit-0/1 gate:

    relyable-skills admit ./skills --grader ./my_grader.py --run
    relyable-skills admit ./skills --grader ./my_grader.py --json

Each subdirectory of ``<registry>`` with a manifest.json is a candidate skill
bundle. The gate re-derives every one against ``--grader`` (the consumer's own
trusted grader) and reports per-skill verdicts. Exit code is non-zero if ANY
candidate is rejected (fail-closed), so a poisoned registry stops the pipeline.

``--run`` sets ``permit_execution=True`` (vet by running the candidate on a
disposable host); without it, the gate won't run untrusted code and every skill
is could-not-conclude / unadmitted.

``init`` solves the OTHER end — the blank page. Point it at a skill (and the repo
it lives in) and it detects the cheapest applicable grader rung and scaffolds the
grader, so you CONFIRM a detected grader instead of writing one from scratch:

    relyable-skills init ./mypkg/skills/foo.py --smoke
    relyable-skills init ./mypkg/skills/foo.py --project-root ./ --out grader.py

Only a clean T1 (pre-existing suite) is auto-fillable; T0/T2/T5 emit templates
with FILL-ME sections. Stdlib only on the admit path.

``prove`` is the T2 graduation: an agent PROPOSES a property (round_trip /
idempotence / schema_conformance) via a spec; this gate certifies it is
NON-VACUOUS — it mutates the current skill (the reference) and the property must
KILL the mutants, else it asserts too little and is rejected:

    relyable-skills prove ./mypkg/skills/codec.py --kind round_trip \\
        --spec spec.json --grader-out codec_grader.py

The agent's work is writing spec.json (prompting), not hand-authoring criteria:

    {"kind": "round_trip",
     "contract_fn": {"forward": "encode", "inverse": "decode"},
     "inputs": [["hello"], ["world"]]}            # each item = one call's args

    {"kind": "idempotence", "contract_fn": "normalize",
     "inputs": [[[3, 1, 2]]]}

    {"kind": "schema_conformance", "contract_fn": "build",
     "schema": {"type": "object", "required": ["x"]}, "inputs": [[5]]}

HONEST CATCH: kills-mutants proves NON-VACUOUS, not correct-spec. ``determinism``
is NOT provable (it survives mutation) and is refused. ``prove`` needs mutmut on
PATH (install it — installing a package is not user friction). Exit: 0 = certified
non-vacuous; 1 = vacuous (survivors listed); 2 = refused / usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .registry import admit_directory, usable_skills
from .scaffold import scaffold_grader


def _cmd_admit(args: argparse.Namespace) -> int:
    registry = Path(args.registry)
    grader = Path(args.grader)
    if not registry.is_dir():
        print(f"registry not a directory: {registry}", file=sys.stderr)
        return 2
    if not grader.is_file():
        print(f"grader not a file: {grader}", file=sys.stderr)
        return 2

    verdicts = admit_directory(
        registry,
        grader_src=grader,
        permit_execution=args.run,
        pack_filename=args.pack_filename,
    )
    usable = usable_skills(verdicts)

    if args.json:
        print(
            json.dumps(
                {
                    "registry": str(registry),
                    "permit_execution": args.run,
                    "usable": [v.skill_id for v in usable],
                    "verdicts": [asdict(v) for v in verdicts],
                },
                indent=2,
            )
        )
    else:
        for v in verdicts:
            flag = " FORGED" if v.forged_label else ""
            print(f"{v.verdict:<6} {v.skill_id}  [{v.reason_code}]{flag}")
        print(f"\n{len(usable)}/{len(verdicts)} usable")

    # Fail-closed: any rejected candidate is a non-zero exit.
    return 0 if len(usable) == len(verdicts) and verdicts else 1


def _smoke_t1(skill_path: Path, grader: Path) -> tuple[bool, str]:
    """Build a bundle around the CURRENT skill body and re-derive it once against
    the freshly-scaffolded T1 grader. A passing skill that its detected suite
    REJECTS is a sign the detection is off (wrong suite / target). Imports the
    veriker-backed gate lazily so ``init`` for T0/T2/T5 never pays for it."""
    from .bundle import build_skill_bundle  # noqa: PLC0415
    from .gate import rederive  # noqa: PLC0415

    try:
        body = skill_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"skill_unreadable: {e}"
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="relyable-smoke-") as td:
        bundle = build_skill_bundle(
            Path(td) / "bundle",
            skill_id=skill_path.stem,
            kind="scaffold-smoke",
            body=body,
            claimed_verdict="VALIDATED",
            grader_src=grader,
        )
        v = rederive(bundle, grader_src=grader, permit_execution=True)
    return v.verdict == "ADMIT", f"{v.verdict} [{v.reason_code}]: {v.detail}"


def _cmd_init(args: argparse.Namespace) -> int:
    skill_path = Path(args.skill)
    if not skill_path.is_file():
        print(f"skill not a file: {skill_path}", file=sys.stderr)
        return 2
    dest = (
        Path(args.out)
        if args.out
        else skill_path.with_name(f"{skill_path.stem}_grader.py")
    )

    result = scaffold_grader(skill_path, dest, project_root=args.project_root)

    smoke_ok: bool | None = None
    smoke_detail = ""
    if args.smoke:
        if result.rung == "T1":
            smoke_ok, smoke_detail = _smoke_t1(skill_path, dest)
        else:
            smoke_detail = (
                f"--smoke skipped: rung {result.rung} is a template, not runnable yet"
            )

    if args.json:
        print(
            json.dumps(
                {
                    "skill": str(skill_path),
                    "grader": str(result.dest),
                    "rung": result.rung,
                    "auto_fillable": result.auto_fillable,
                    "needs_confirmation": result.needs_confirmation,
                    "reason": result.reason,
                    "caveat": result.caveat,
                    "next_step": result.next_step,
                    "smoke_ok": smoke_ok,
                    "smoke_detail": smoke_detail or None,
                },
                indent=2,
            )
        )
    else:
        tag = "AUTO-FILLABLE" if result.auto_fillable else "TEMPLATE (confirm/fill)"
        print(f"rung {result.rung}  [{tag}]  -> {result.dest}")
        print(f"  why:    {result.reason}")
        print(f"  caveat: {result.caveat}")
        print(f"  next:   {result.next_step}")
        if smoke_detail:
            mark = "ok" if smoke_ok else ("FAIL" if smoke_ok is False else "—")
            print(f"  smoke:  [{mark}] {smoke_detail}")

    # Exit non-zero only if a requested T1 smoke check actively FAILED (the detected
    # suite rejected the current skill) — that means the scaffold is not trustworthy
    # as-is. A template (no smoke) still exits 0: writing it is the success.
    return 1 if smoke_ok is False else 0


def _resolve_prove_spec(spec: dict, kind_flag: str | None) -> tuple[str, str, dict]:
    """Turn a prove spec.json (+ optional --kind) into (kind, contract_fn, params)
    for make_property_grader. Raises ValueError on a malformed spec."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object")
    kind = kind_flag or spec.get("kind")
    if not kind:
        raise ValueError("no kind: pass --kind or set 'kind' in the spec")
    if kind_flag and spec.get("kind") and spec["kind"] != kind_flag:
        raise ValueError(
            f"--kind {kind_flag!r} conflicts with spec kind {spec['kind']!r}"
        )
    inputs = spec.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError(
            "'inputs' must be a non-empty list (each item = one call's args)"
        )

    if kind == "round_trip":
        cf = spec.get("contract_fn")
        if isinstance(cf, dict):
            forward, inverse = cf.get("forward"), cf.get("inverse")
        else:
            forward, inverse = spec.get("forward", cf), spec.get("inverse")
        if not forward or not inverse:
            raise ValueError(
                "round_trip needs a forward and an inverse fn "
                "(contract_fn: {forward, inverse}, or top-level forward/inverse)"
            )
        return kind, str(forward), {"inverse": str(inverse), "inputs": inputs}

    contract_fn = spec.get("contract_fn")
    if not contract_fn or not isinstance(contract_fn, str):
        raise ValueError(f"{kind} needs a string 'contract_fn'")
    return kind, contract_fn, {"inputs": inputs, "schema": spec.get("schema", {})}


def _cmd_prove(args: argparse.Namespace) -> int:
    from dataclasses import asdict  # noqa: PLC0415

    from .anti_vacuity import prove_non_vacuous  # noqa: PLC0415
    from .property_grader import make_property_grader  # noqa: PLC0415

    skill_path = Path(args.skill)
    spec_path = Path(args.spec)
    if not skill_path.is_file():
        print(f"skill not a file: {skill_path}", file=sys.stderr)
        return 2
    if not spec_path.is_file():
        print(f"spec not a file: {spec_path}", file=sys.stderr)
        return 2
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"spec unreadable / not JSON: {e}", file=sys.stderr)
        return 2
    try:
        kind, contract_fn, params = _resolve_prove_spec(spec, args.kind)
        grader_src = make_property_grader(
            kind, contract_fn=contract_fn, params=params, placeholders=False
        )
    except ValueError as e:
        print(f"prove refused: {e}", file=sys.stderr)
        return 2

    reference = skill_path.read_text(encoding="utf-8")
    try:
        cert = prove_non_vacuous(
            grader_src, reference, kind=kind, max_survivors=args.max_survivors
        )
    except ValueError as e:  # determinism / unprovable kind — refused up front
        print(f"prove refused: {e}", file=sys.stderr)
        return 2

    # Only a NON-VACUOUS property yields a pinnable grader; a vacuous one is not
    # written (handing back a grader that looks certified would be dishonest).
    grader_out = Path(args.grader_out)
    if cert.ok:
        grader_out.write_text(grader_src, encoding="utf-8")

    if args.json:
        payload = asdict(cert)
        payload["grader"] = str(grader_out) if cert.ok else None
        print(json.dumps(payload, indent=2))
    else:
        tag = "NON-VACUOUS (certified)" if cert.ok else "VACUOUS (rejected)"
        print(f"{tag}  kind={cert.kind}  engine={cert.engine} {cert.mutmut_version}")
        print(
            f"  {cert.killed}/{cert.total} mutants killed; "
            f"{len(cert.survivors)} survived (<= max {cert.max_survivors})"
        )
        if cert.survivors:
            print(f"  survivors: {list(cert.survivors[:20])}")
        if cert.reason:
            print(f"  reason: {cert.reason}")
        if cert.ok:
            print(f"  grader: {grader_out}  (pin as grader_src)")
        print(f"  ref: sha256:{cert.reference_digest[:16]}…  ({cert.honest_catch})")

    return 0 if cert.ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="relyable-skills")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_admit = sub.add_parser(
        "admit", help="re-derive every skill bundle under <registry>"
    )
    p_admit.add_argument("registry", help="dir of skill bundles (one subdir each)")
    p_admit.add_argument(
        "--grader", required=True, help="path to the consumer's trusted grader"
    )
    p_admit.add_argument(
        "--run",
        action="store_true",
        help="permit_execution=True (run candidates to vet them)",
    )
    p_admit.add_argument(
        "--pack-filename",
        dest="pack_filename",
        default=None,
        help="grader filename inside the bundle (defaults to the grader's name)",
    )
    p_admit.add_argument("--json", action="store_true", help="machine-readable output")
    p_admit.set_defaults(func=_cmd_admit)

    p_init = sub.add_parser(
        "init", help="detect the cheapest grader rung for a skill and scaffold it"
    )
    p_init.add_argument("skill", help="path to the skill module (the candidate body)")
    p_init.add_argument(
        "--project-root",
        dest="project_root",
        default=None,
        help="the consumer repo (default: nearest ancestor with a project marker)",
    )
    p_init.add_argument(
        "--out",
        default=None,
        help="where to write the grader (default: <skill>_grader.py beside the skill)",
    )
    p_init.add_argument(
        "--smoke",
        action="store_true",
        help="for a T1 scaffold, re-derive the current skill once to confirm the "
        "detected suite admits it",
    )
    p_init.add_argument("--json", action="store_true", help="machine-readable output")
    p_init.set_defaults(func=_cmd_init)

    p_prove = sub.add_parser(
        "prove",
        help="certify an agent-proposed property is NON-VACUOUS (mutate the skill; "
        "the property must kill the mutants). Needs mutmut on PATH.",
    )
    p_prove.add_argument(
        "skill", help="the skill module used as the reference candidate"
    )
    p_prove.add_argument(
        "--kind",
        default=None,
        help="property kind: round_trip | idempotence | schema_conformance "
        "(determinism is NOT provable). May instead be set in the spec.",
    )
    p_prove.add_argument(
        "--spec",
        required=True,
        help="spec.json: {kind?, contract_fn (or {forward,inverse}), inputs, schema?}",
    )
    p_prove.add_argument(
        "--grader-out",
        dest="grader_out",
        required=True,
        help="where to write the certified concrete grader (written only if non-vacuous)",
    )
    p_prove.add_argument(
        "--max-survivors",
        dest="max_survivors",
        type=int,
        default=0,
        help="survivor floor (default 0 — every mutant must be killed)",
    )
    p_prove.add_argument("--json", action="store_true", help="machine-readable output")
    p_prove.set_defaults(func=_cmd_prove)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
