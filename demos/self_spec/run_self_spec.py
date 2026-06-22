#!/usr/bin/env python3
"""run_self_spec.py — grade a directory of native skills against THEIR OWN spec.

The companion to ``demos/directory_funnel/funnel.py``. The funnel sizes how much of
a directory relyable can adjudicate with CONSUMER goldens (and found K=0). This runs
the orthogonal author-grounded pass: for each skill, detect the author's OWN
committed oracle (shipped suite / documented examples / fixtures) and re-derive the
authentic bytes against it — no goldens authored by us.

    python run_self_spec.py <skills_dir> [--md OUT.md] [--json]

Each skill subdir must carry a SKILL.md. Verdicts (per the self_spec taxonomy):
REPRODUCES / CONTRADICTS / UNJUDGEABLE_{NO_SPEC,NONDET,ENV,UNPARSE}. The honest
headline is "ships a self-spec: A of N; of those R reproduced, C contradicted" —
NOT "N skills verified". A CONTRADICTS is the author's own oracle disagreeing with
the author's own bytes; treat it as a responsible-disclosure lead, never a public
name-and-shame.

EXECUTION IS FAIL-CLOSED. This pass vets BY RUNNING each (untrusted) tool. It will
NOT execute anything unless you pass ``--allow-host-exec`` — your explicit vow that
THIS host is disposable/sandboxed; without it every tool is UNJUDGEABLE_NO_SANDBOX and
nothing runs. ``--sandbox docker:<image>`` additionally isolates the gate's
re-derivation worker (network off) — defense-in-depth, not a substitute for the ack.
Functional-conformance only; run alongside ClawHub verify / ClawScan, never instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Allow running from the repo without an install: add the package root to sys.path.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from relyable.skills import self_spec as ss  # noqa: E402
from relyable.skills.self_spec import ToolVerdict  # noqa: E402

_REPRO = ToolVerdict.REPRODUCES
_CONTRA = ToolVerdict.CONTRADICTS


def _skill_verdict(per_tool: dict[str, ToolVerdict]) -> str:
    """Roll the per-tool verdicts up to one skill-level label: any CONTRADICTS ->
    CONTRADICTS; else any REPRODUCES -> REPRODUCES; else the (single) unjudgeable
    reason, or UNJUDGEABLE if mixed."""
    vals = list(per_tool.values())
    if any(v == _CONTRA for v in vals):
        return "CONTRADICTS"
    if any(v == _REPRO for v in vals):
        return "REPRODUCES"
    uniq = set(vals)
    return next(iter(uniq)).value if len(uniq) == 1 else "UNJUDGEABLE"


def _make_sandbox(spec: str | None):
    """Mirror of verdicts/cli.py: 'subprocess' (weak; NOT a security boundary) or
    'docker:<image>' (network off). None => in-process default."""
    if spec is None or spec == "subprocess":
        return None
    if spec.startswith("docker:"):
        from relyable.verdicts.sandbox import ContainerSandbox

        image = spec.split(":", 1)[1]
        if not image:
            raise SystemExit("--sandbox docker:<image> requires an image name")
        return ContainerSandbox(image)
    raise SystemExit(
        f"unknown --sandbox {spec!r} (use 'subprocess' or 'docker:<image>')"
    )


def run(skills_dir: Path, *, allow_host_exec: bool, sandbox=None) -> dict:
    skills = sorted(
        p for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )
    rows = []
    for d in skills:
        spec = ss.detect_self_spec(d)
        res = ss.grade_self_spec(
            d, spec, allow_host_exec=allow_host_exec, sandbox=sandbox
        )
        rows.append(
            {
                "skill": d.name,
                "tier": spec.tier,
                "n_goldens": len(spec.goldens),
                "per_tool": {k: v.value for k, v in res.per_tool.items()},
                "skill_verdict": _skill_verdict(res.per_tool),
                "skipped": spec.skipped,
            }
        )
    return _summarize(rows)


def _summarize(rows: list[dict]) -> dict:
    n = len(rows)
    has_spec = [r for r in rows if r["tier"] != "none"]
    by_tier = Counter(r["tier"] for r in has_spec)
    sv = Counter(r["skill_verdict"] for r in rows)
    return {
        "N": n,
        "A_has_self_spec": len(has_spec),
        "by_tier": dict(by_tier),
        "skill_verdicts": dict(sv),
        "goldens_extracted": sum(r["n_goldens"] for r in rows),
        "skipped_total": sum(len(r["skipped"]) for r in rows),
        "rows": rows,
    }


def _fmt(s: dict) -> str:
    sv = s["skill_verdicts"]
    L = []
    L.append(
        f"SELF-SPEC over {s['N']} skills (each graded against the author's OWN spec)"
    )
    L.append(f"  ships a machine-checkable self-spec:  A = {s['A_has_self_spec']}")
    for tier in ("S-A", "S-B", "S-C"):
        if tier in s["by_tier"]:
            L.append(f"     {tier}  {s['by_tier'][tier]}")
    L.append(
        f"     goldens extracted (S-B/S-C):  {s['goldens_extracted']}  (skipped fail-closed: {s['skipped_total']})"
    )
    L.append("  verdicts:")
    L.append(
        f"     REPRODUCES   R = {sv.get('REPRODUCES', 0)}   (author's bytes reproduce author's spec)"
    )
    L.append(
        f"     CONTRADICTS  C = {sv.get('CONTRADICTS', 0)}   (disclose privately; never name here)"
    )
    unj = sum(v for k, v in sv.items() if k.startswith("UNJUDGEABLE"))
    L.append(f"     UNJUDGEABLE  {unj}")
    for k in sorted(sv):
        if k.startswith("UNJUDGEABLE"):
            L.append(f"        {k}: {sv[k]}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "skills_dir", help="directory of skill subdirs (each with SKILL.md)"
    )
    ap.add_argument(
        "--md", help="write a SELF_SPEC_RUN-style markdown block to this path"
    )
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument(
        "--allow-host-exec",
        action="store_true",
        help="REQUIRED to run anything: your explicit vow that THIS host is "
        "disposable/sandboxed. Without it, every tool is UNJUDGEABLE_NO_SANDBOX "
        "(fail-closed — no untrusted code runs).",
    )
    ap.add_argument(
        "--sandbox",
        metavar="SPEC",
        default=None,
        help="extra isolation for the gate's re-derivation worker: 'subprocess' "
        "(default, weak) or 'docker:<image>' (network off). NOT a substitute for "
        "--allow-host-exec (the preflight runs on the host either way).",
    )
    args = ap.parse_args()
    root = Path(args.skills_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    if not args.allow_host_exec:
        print(
            "[self_spec] FAIL-CLOSED: --allow-host-exec not given, so no skill code "
            "will be executed; every executable tool reports UNJUDGEABLE_NO_SANDBOX.\n"
            "            Pass --allow-host-exec ONLY on a disposable/sandboxed host.",
            file=sys.stderr,
        )
    sandbox = _make_sandbox(args.sandbox)
    summary = run(root, allow_host_exec=args.allow_host_exec, sandbox=sandbox)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(_fmt(summary))
    if args.md:
        Path(args.md).write_text("```\n" + _fmt(summary) + "\n```\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
