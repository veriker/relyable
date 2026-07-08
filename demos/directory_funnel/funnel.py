#!/usr/bin/env python3
"""funnel.py — honest sizing of a skills directory's re-derivable surface.

Point it at a directory of native skills (one subdir each, with a SKILL.md) — e.g.
a set installed from ClawHub — and it reports the funnel that actually governs how
much of a marketplace relyable's install gate can adjudicate:

    N skills in the directory
      → M with a runnable entrypoint + I/O contract     (re-derivation CANDIDATES)
          → of M, K where a trust root AUTO-scaffolds    (T1: a pre-existing suite)
            vs need consumer-authored goldens            (T0/T2/T5)
      → (N - M) prose / instruction / external-CLI skills
          (no deterministic oracle — OUT OF SCOPE for re-derivation, by design)

This is deliberately conservative and honest: a *detected entrypoint* is a NECESSARY
precondition, not proof a skill is judgeable — a clean deterministic I/O contract +
the consumer's held-out goldens are still required. The gate never fabricates a
verdict for a skill it cannot re-derive; this script never claims coverage it can't.

Usage:
    python funnel.py /path/to/skills_dir
    python funnel.py /path/to/skills_dir --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))


def _entrypoint_shaped(path: Path) -> bool:
    """Heuristic: does this script look like an INVOCABLE entrypoint (a CLI), vs a
    library module or test file? ``enumerate_tools`` returns every script (correct for
    PACKING — a fail-closed extra bundle is harmless), but for honest SIZING we must
    not count a base class / util module / test as a re-derivable 'tool'. This is the
    necessary-not-sufficient filter: entrypoint-shaped is still only a CANDIDATE; a
    deterministic I/O contract + consumer goldens are the real bar (a network/GUI/
    side-effecting entrypoint passes this shape check but still has no clean oracle)."""
    if (
        "tests" in path.parts
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    ):
        return False
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if path.suffix == ".py":
        return "__main__" in txt or "argparse" in txt or "sys.argv" in txt
    if path.suffix == ".sh":
        return txt.lstrip().startswith("#!") or "$@" in txt or "$1" in txt
    if path.suffix in (".js", ".mjs"):
        return "process.argv" in txt or "require.main" in txt or txt[:3] == "#!/"
    return False


def classify(skill_dir: Path) -> dict:
    """Bucket one native skill. Returns {name, bucket, detail, runner?, rung?,
    auto_fillable?}."""
    from relyable.adapters._skillpack import (
        AMBIGUOUS_ENTRYPOINT,
        OutOfScope,
        detect_invocation,
        enumerate_tools,
        parse_frontmatter,
    )

    md = skill_dir / "SKILL.md"
    # errors="replace": real ClawHub SKILL.md in the wild carry non-UTF-8 bytes;
    # the funnel must survey them, not crash on one bad file.
    fm = (
        parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        if md.is_file()
        else {}
    )
    try:
        inv = detect_invocation(skill_dir, fm)
    except OutOfScope as e:
        if e.reason_code != AMBIGUOUS_ENTRYPOINT:
            # Genuinely no oracle (prose / instruction / external-CLI).
            return {"name": skill_dir.name, "bucket": e.reason_code, "detail": e.detail}
        # AMBIGUOUS is NOT prose — it is a tool BUNDLE (one SKILL.md routing to N
        # bundled scripts). Enumerate its tools; count the entrypoint-shaped ones as
        # the honest candidate set (raw enumerate also returns library modules + tests
        # — harmless for packing, over-counting for sizing).
        invs = enumerate_tools(skill_dir, fm)
        eps = [
            i.entrypoint for i in invs if _entrypoint_shaped(skill_dir / i.entrypoint)
        ]
        return {
            "name": skill_dir.name,
            "bucket": "BUNDLE",
            "raw_tools": len(invs),
            "n_tools": len(eps),  # entrypoint-shaped only
            "tools": eps,
            "detail": f"{len(eps)} entrypoint tools (of {len(invs)} scripts): {eps}",
        }

    # Stage 2: a single-entrypoint candidate. How cheap is a trust root for it?
    row = {
        "name": skill_dir.name,
        "bucket": "CANDIDATE",
        "n_tools": 1,
        "entrypoint_shaped": _entrypoint_shaped(skill_dir / inv.entrypoint),
        "detail": f"entrypoint={inv.entrypoint} runner={inv.runner}",
        "runner": inv.runner,
    }
    if inv.runner == "python":
        from relyable.skills.scaffold import detect_rung

        try:
            det = detect_rung(skill_dir / inv.entrypoint, project_root=skill_dir)
            row["rung"] = det.rung
            row["auto_fillable"] = det.auto_fillable
        except Exception as e:  # detection is best-effort; never crash the funnel
            row["rung"] = "?"
            row["auto_fillable"] = False
            row["detail"] += f" (rung-detect skipped: {type(e).__name__})"
    else:
        row["rung"] = "manual"  # non-Python entrypoint: no AST-based scaffolding
        row["auto_fillable"] = False
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "skills_dir", help="directory of skill subdirs (each with SKILL.md)"
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.skills_dir).expanduser()
    skills = sorted(
        p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )
    if not skills:
        print(f"no skills (subdir with SKILL.md) under {root}", file=sys.stderr)
        return 2

    rows = [classify(s) for s in skills]
    singles = [r for r in rows if r["bucket"] == "CANDIDATE"]
    bundles = [r for r in rows if r["bucket"] == "BUNDLE"]
    # A bundle with zero entrypoint-shaped scripts is effectively not executable for
    # sizing (all its scripts are modules/tests); keep it labelled but count it out.
    bundles_live = [r for r in bundles if r["n_tools"] > 0]
    executable = singles + bundles_live
    prose = [r for r in rows if r["bucket"] not in ("CANDIDATE", "BUNDLE")]
    auto = [r for r in singles if r.get("auto_fillable")]
    singles_ep = [r for r in singles if r.get("entrypoint_shaped")]
    # Tool-level: entrypoint-shaped tools only (single = 1 if shaped; bundle = its
    # shaped tools). raw_tools is the un-filtered script count, kept for honesty.
    bundle_tools = sum(r["n_tools"] for r in bundles)
    tool_candidates = len(singles_ep) + bundle_tools
    raw_scripts = len(singles) + sum(r.get("raw_tools", 0) for r in bundles)

    if args.json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "n_skills": len(rows),
                    "executable_skills": len(executable),
                    "single_entrypoint": len(singles),
                    "single_entrypoint_shaped": len(singles_ep),
                    "bundles": len(bundles),
                    "tool_candidates_entrypoint_shaped": tool_candidates,
                    "raw_script_count": raw_scripts,
                    "prose_out_of_scope": len(prose),
                    "rows": rows,
                },
                indent=2,
            )
        )
        return 0

    n = len(rows)
    print(f"\nFUNNEL over {n} skills in {root}\n" + "─" * 72)
    print("SKILL-LEVEL:")
    print(f"  N = {n:>3}  skills with a SKILL.md")
    print(
        f"  E = {len(executable):>3}  EXECUTABLE skills (≥1 entrypoint-shaped script): "
        f"{len(singles)} single-entrypoint + {len(bundles_live)} tool-bundle"
    )
    print(
        f"      {len(prose):>3}  prose / instruction / external-CLI (out of scope by design)"
    )
    print("TOOL-LEVEL (the unit the gate re-derives — one verdict per tool):")
    print(
        f"  T = {tool_candidates:>3}  CANDIDATE tools, entrypoint-shaped "
        f"({len(singles_ep)} single + {bundle_tools} bundle) — of {raw_scripts} raw "
        f"scripts (rest are library modules / tests, not invocable tools)"
    )
    print(
        f"  K = {len(auto):>3}  of the single tools auto-scaffold a trust root (T1); "
        f"the rest need consumer goldens"
    )
    print(
        "  NB: entrypoint-shaped is NECESSARY, not sufficient — a network / GUI / "
        "side-\n      effecting tool passes this check but still has no deterministic "
        "oracle.\n      The cleanly-re-derivable count is a further haircut on T."
    )
    print("─" * 72)

    print("\nEXECUTABLE — single entrypoint (still need a consumer grader):")
    if not singles:
        print("  (none)")
    for r in singles:
        rung = r.get("rung", "?")
        auto_s = "AUTO(T1)" if r.get("auto_fillable") else f"manual[{rung}]"
        print(f"  • {r['name']:<28} {r['detail']:<34} trust-root: {auto_s}")

    print("\nEXECUTABLE — tool bundles (entrypoint-shaped tools / raw scripts):")
    if not bundles:
        print("  (none)")
    for r in sorted(bundles, key=lambda r: -r["n_tools"]):
        print(
            f"  • {r['name']:<30} {r['n_tools']:>2}/{r.get('raw_tools', 0):<2} tools: "
            f"{r['tools']}"
        )

    print("\nOUT OF SCOPE (no deterministic oracle to re-derive):")
    by_reason: dict[str, list[str]] = {}
    for r in prose:
        by_reason.setdefault(r["bucket"], []).append(r["name"])
    for reason, names in sorted(by_reason.items()):
        print(f"  [{reason}] ({len(names)})")
        print("    " + ", ".join(sorted(names)))

    print(
        "\nHonest reading: re-derivation vetting addresses the EXECUTABLE slice — skills\n"
        "with a runnable entrypoint and a definable I/O contract, counted at the TOOL\n"
        "level because a tool bundle is N independently re-derivable tools, not one\n"
        "ambiguous reject (the pre-bundle funnel under-counted these). A detected\n"
        "entrypoint is NECESSARY, not sufficient: a clean I/O contract + the consumer's\n"
        "held-out goldens are still required, and grader provisioning is the real\n"
        "constraint. The prose/instruction majority stays out of scope BY DESIGN — the\n"
        "gate refuses rather than fabricate a verdict.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
