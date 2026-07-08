#!/usr/bin/env python3
"""rederive_bundle.py — per-tool re-derivation of a real ClawHub TOOL BUNDLE.

The directory funnel found that real ClawHub "tool bundles" — one SKILL.md routing
to several bundled ``scripts/*.py``, each a small CLI — were false-rejected by the
install gate as AMBIGUOUS_ENTRYPOINT, because the scope gate modeled exactly one
entrypoint. This demo runs the tool-BUNDLE generalization end to end on the real
``clean-json-toolkit`` (7 tools): it enumerates the bundle's tools, packs ONE
re-derivable veriker bundle per tool, and re-derives each against a CONSUMER grader
(``json_toolkit_grader.py``) that ships held-out goldens for two of them
(``query``, ``flatten``).

Honest framing — "K of N tools re-derive":
    * tools the consumer grades AND that reproduce the goldens   -> ADMIT
    * tools the consumer has no goldens for                      -> UNJUDGEABLE
      (fail-closed: the grader returns no_goldens_for_kind, never a fabricated pass)
    * a tool that runs but contradicts the goldens              -> REJECT

It then drives the SAME decision through the live OpenClaw ``security.installPolicy``
adapter (``installpolicy.run``) to show the install gate now adjudicates the bundle
class (allow when the graded tools conform) instead of declaring it unjudgeable.

Usage:
    python rederive_bundle.py [SKILL_DIR]            # default: ~/.openclaw/skills/clean-json-toolkit
    python rederive_bundle.py --break query [SKILL_DIR]   # sabotage one tool -> watch it REJECT / install BLOCK
    python rederive_bundle.py --json [SKILL_DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))

DEFAULT_SKILL = Path.home() / ".openclaw" / "skills" / "clean-json-toolkit"
GRADER = PRODUCT_ROOT / "relyable" / "skills" / "examples" / "json_toolkit_grader.py"
NO_GOLDENS = "no_goldens_for_kind"


def _slug_of(skill_dir: Path) -> str:
    from relyable.adapters._skillpack import _slug, parse_frontmatter

    md = skill_dir / "SKILL.md"
    fm = parse_frontmatter(md.read_text(encoding="utf-8")) if md.is_file() else {}
    return _slug(str(fm.get("name") or skill_dir.name))


def _break_tool(skill_dir: Path, tool: str, work: Path) -> Path:
    """Copy the skill and sabotage one tool's behavior (query's --raw stops
    stripping quotes), so it runs cleanly but contradicts the consumer goldens."""
    dst = work / skill_dir.name
    shutil.copytree(skill_dir, dst)
    f = dst / "scripts" / f"{tool}.py"
    src = f.read_text(encoding="utf-8")
    if tool == "query":
        broken = src.replace('out.write(r + "\\n")', 'out.write(repr(r) + "\\n")')
    else:
        broken = src + "\nimport sys as _s; _s.exit(0)\n"  # generic no-op sabotage
    if broken == src:
        raise SystemExit(f"--break {tool}: sabotage pattern not found in {f}")
    f.write_text(broken, encoding="utf-8")
    return dst


def run(skill_dir: Path, break_tool: str | None) -> dict:
    from relyable.adapters._skillpack import (
        enumerate_tools,
        pack_native_tool_bundles,
        parse_frontmatter,
    )
    from relyable.adapters.installpolicy import run as installpolicy_run
    from relyable.skills import ADMIT, admit_directory

    with tempfile.TemporaryDirectory(prefix="tool-bundle-demo-") as td:
        work = Path(td)
        target = _break_tool(skill_dir, break_tool, work) if break_tool else skill_dir
        slug = _slug_of(target)
        fm = parse_frontmatter((target / "SKILL.md").read_text(encoding="utf-8"))
        invs = enumerate_tools(target, fm)

        bundles_root = work / "tools"
        pack_native_tool_bundles(
            target, bundles_root, grader_src=GRADER, kind_prefix=slug
        )
        verdicts = admit_directory(
            bundles_root, grader_src=GRADER, permit_execution=True
        )

        tools = []
        for v in sorted(verdicts, key=lambda v: v.kind):
            if v.verdict == ADMIT:
                status = "ADMIT"
            elif v.rederived_label == "REJECTED" and NO_GOLDENS not in v.detail:
                status = "REJECT"
            else:
                status = "UNJUDGEABLE"
            tools.append({"kind": v.kind, "status": status, "reason": v.reason_code})

        # The same decision through the live OpenClaw install-policy adapter.
        req = json.dumps(
            {
                "protocolVersion": 1,
                "openclawVersion": "2026.6.8",
                "targetType": "skill",
                "targetName": slug,
                "sourcePath": str(target),
                "sourcePathKind": "directory",
                "origin": {"type": "clawhub", "slug": slug},
                "request": {"kind": "install"},
            }
        )
        decision = installpolicy_run(
            req, {"RELYABLE_INSTALLPOLICY_GRADER": str(GRADER)}
        )

    admitted = [t["kind"] for t in tools if t["status"] == "ADMIT"]
    return {
        "skill": slug,
        "n_tools": len(invs),
        "tools": tools,
        "k_admitted": len(admitted),
        "admitted": admitted,
        "install_decision": decision,
        "broke": break_tool,
    }


def _goldens_summary() -> dict:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_jtg", GRADER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {k: len(v) for k, v in mod.GOLDENS.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("skill_dir", nargs="?", default=str(DEFAULT_SKILL))
    ap.add_argument("--break", dest="break_tool", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    skill_dir = Path(args.skill_dir)
    if not (skill_dir / "SKILL.md").is_file():
        print(
            f"no SKILL.md under {skill_dir} — install with:\n"
            "  cd /tmp/oclive && npx openclaw skills install clean-json-toolkit "
            "--global --force",
            file=sys.stderr,
        )
        return 2

    result = run(skill_dir, args.break_tool)
    if args.json:
        print(json.dumps({**result, "consumer_goldens": _goldens_summary()}, indent=2))
        return 0

    goldens = _goldens_summary()
    print(f"Skill: {result['skill']}   tools: {result['n_tools']}")
    if result["broke"]:
        print(f"(sabotaged tool: {result['broke']})")
    print(f"Consumer grader: {GRADER.name}")
    print("  held-out goldens:")
    for kind, n in sorted(goldens.items()):
        print(f"    {kind:32s} {n} cell(s)")
    print("\nPer-tool re-derivation:")
    for t in result["tools"]:
        print(f"    {t['kind']:32s} {t['status']:12s} {t['reason']}")
    print(
        f"\nK of N: {result['k_admitted']} of {result['n_tools']} tools re-derive "
        f"-> {result['admitted']}"
    )
    print(f"OpenClaw install-policy decision: {result['install_decision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
