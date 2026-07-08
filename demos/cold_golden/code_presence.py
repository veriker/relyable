#!/usr/bin/env python3
"""code_presence.py — measure how many ClawHub skills ship deterministic CODE at all.

The converter-family slice (COLD_GOLDEN_RUN.md §9) found that even skills NAMED like
deterministic converters mostly ship no executable — they are prose instructions to the
LLM. That relocated the re-derivation wall to a gate UPSTREAM of "ships a checkable spec":
*does the skill ship runnable code at all?* re-derivation (ours or anyone's) needs an
artifact to run; a prose/agentic skill has nothing to re-derive at the code level.

This sizes that gate on a powered, seed-pinned random sample — and it is **purely
mechanical**: no LLM call, no API spend. For each fetched skill it reports two measures:

  ships_any_script        the loose gate: >=1 .py/.sh/.js/.mjs file anywhere in the bundle
                          (matches the recursive file-listing used for the §9 tally).
  declares_runnable_tool  the strict, re-derivation-relevant gate: the harness's own
                          enumerate_tools resolves a runnable entrypoint (i.e. cold_golden
                          would NOT short-circuit to OUT_OF_SCOPE_PROSE_SKILL). This is the
                          exact slice the cold mechanisms can even attempt.

Both proportions carry a Wilson 95% CI. Run fetch_sample.py first to populate the dir:

    python fetch_sample.py /tmp/clawhub_powered 250 --seed 20260621
    python code_presence.py /tmp/clawhub_powered --out CODE_PRESENCE_POWERED.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import cold_golden as cg  # noqa: E402

from relyable.adapters._skillpack import OutOfScope  # noqa: E402

_SCRIPT_EXTS = {".py", ".sh", ".js", ".mjs"}


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion. Returns (p, lo, hi)."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class SkillCode:
    slug: str
    ships_any_script: bool
    declares_runnable_tool: bool
    detail: str = ""


def classify(skill_dir: Path) -> SkillCode:
    slug = skill_dir.name
    # Loose gate: any runnable-extension file anywhere in the bundle.
    scripts = [
        p for p in skill_dir.rglob("*") if p.is_file() and p.suffix in _SCRIPT_EXTS
    ]
    ships_any = len(scripts) > 0

    # Strict gate: the harness resolves a runnable entrypoint (same path cold_golden
    # takes before it would emit OUT_OF_SCOPE_PROSE_SKILL).
    declares = False
    detail = ""
    md = skill_dir / "SKILL.md"
    if not md.exists():
        detail = "no SKILL.md"
    else:
        try:
            eps = cg._entrypoints(skill_dir)
            tool_names = sorted({Path(p).name for p in eps})
            runnable = [t for t in tool_names if cg._runner_for(t)]
            declares = bool(runnable)
            detail = (
                f"runnable entrypoint(s): {runnable}"
                if runnable
                else "entrypoints declared but no known runner"
            )
        except OutOfScope as e:
            detail = f"prose / no entrypoint ({e.reason_code})"
        except Exception as e:  # never let one malformed skill abort the sweep
            detail = f"enumerate error: {type(e).__name__}: {e}"
    return SkillCode(slug, ships_any, declares, detail)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("skills_dir", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    dirs = sorted(d for d in args.skills_dir.iterdir() if d.is_dir())
    records = [classify(d) for d in dirs]
    n = len(records)
    n_script = sum(1 for r in records if r.ships_any_script)
    n_tool = sum(1 for r in records if r.declares_runnable_tool)

    p_s, lo_s, hi_s = _wilson(n_script, n)
    p_t, lo_t, hi_t = _wilson(n_tool, n)

    for r in records:
        flag = "CODE" if r.ships_any_script else "prose"
        tool = "tool" if r.declares_runnable_tool else "----"
        print(f"  {flag:5} {tool:5} {r.slug:34} {r.detail}", file=sys.stderr)

    print("\n== code-presence (mechanical; no LLM) ==", file=sys.stderr)
    print(f"  n = {n}", file=sys.stderr)
    print(
        f"  ships_any_script       {n_script}/{n} = {p_s:.1%}  "
        f"(95% Wilson CI {lo_s:.1%}-{hi_s:.1%})",
        file=sys.stderr,
    )
    print(
        f"  declares_runnable_tool {n_tool}/{n} = {p_t:.1%}  "
        f"(95% Wilson CI {lo_t:.1%}-{hi_t:.1%})",
        file=sys.stderr,
    )

    summary = {
        "skills_dir": str(args.skills_dir),
        "n": n,
        "ships_any_script": {
            "k": n_script,
            "p": p_s,
            "ci95": [lo_s, hi_s],
        },
        "declares_runnable_tool": {
            "k": n_tool,
            "p": p_t,
            "ci95": [lo_t, hi_t],
        },
        "records": [asdict(r) for r in records],
    }
    if args.out:
        args.out.write_text(json.dumps(summary, indent=2))
        print(f"\n[wrote {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
