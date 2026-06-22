#!/usr/bin/env python3
"""classify_local.py — pre-filter a fetched skill sample to the ADDRESSABLE slice.

cold_golden's coverage is bounded by more than executability: a tool that calls a live
API, returns a model/LLM completion, or draws randomness has behaviour that is
**exogenous to its own code**, so no re-derivation gate (author golden or cold golden)
can pin it. Measuring cold-golden's real yield therefore needs the right denominator —
the skills it could *possibly* serve, not the whole catalog.

This is a cheap SCREENING pass (Haiku): it reads each skill's `SKILL.md` + tool
filenames and routes it into one category. It is selection only — it picks which skills
the (mechanical, no-LLM-judge) cold-golden grader is even asked to look at; it never
grades behaviour. Prose-only skills are routed for free (no API call) via the same
`_skillpack` entrypoint check cold_golden uses.

Categories:
    PROSE              no executable entrypoint (instruction skill)
    NETWORK            calls an external API / HTTP / cloud service / remote DB
    STOCHASTIC         output is random / ML / LLM-generated / time-dependent
    LIBRARY            importable modules, no documented CLI
    LOCAL_DETERMINISTIC  self-contained CLI: deterministic, no network/credential/LLM dep
                       — the slice cold_golden can actually serve

Output: a JSON summary + (with --link DIR) a directory of symlinks to the
LOCAL_DETERMINISTIC skills, ready to hand to `cold_golden.py`.

    python classify_local.py SAMPLE_DIR [--link FILTERED_DIR] [--model M] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import cold_golden as cg  # noqa: E402  (reuse key loader, http, entrypoint check, json extract)

from relyable.adapters._skillpack import OutOfScope  # noqa: E402

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
CATEGORIES = {"PROSE", "NETWORK", "STOCHASTIC", "LIBRARY", "LOCAL_DETERMINISTIC"}

_SYSTEM = (
    "You route a command-line agent skill into exactly one category, from its "
    "documentation (SKILL.md) and tool filenames only. You are deciding whether the "
    "skill's behaviour could even in principle be re-derived by running it offline and "
    "comparing output — NOT whether it is good.\n\n"
    "Categories (choose ONE):\n"
    "* NETWORK — any tool calls an external API, HTTP endpoint, cloud service, remote "
    "database, or requires an API key / network access to produce its output.\n"
    "* STOCHASTIC — output is random, ML/LLM-generated, image/audio generation, or "
    "otherwise time/seed-dependent and not reproducible byte-for-byte offline.\n"
    "* LIBRARY — the entrypoints are importable modules with no documented standalone "
    "command-line interface (no argv/stdin usage shown).\n"
    "* LOCAL_DETERMINISTIC — a self-contained CLI that transforms its input to output "
    "purely locally and deterministically: no network, no credentials, no randomness, "
    "no LLM. (e.g. a JSON/CSV/text transformer, a linter, a converter, a calculator.)\n"
    "* PROSE — no executable tool at all (you will rarely see this; it is pre-filtered).\n\n"
    "When a skill mixes kinds, pick the one that BLOCKS offline re-derivation if present "
    "(NETWORK or STOCHASTIC dominate LOCAL_DETERMINISTIC). Only answer "
    "LOCAL_DETERMINISTIC if EVERY documented tool could run offline and deterministically.\n\n"
    "Respond with ONLY a JSON object: "
    '{"category": "<one of the five>", "why": "<short reason>"}'
)


def classify_one(skill_dir: Path, api_key: str, model: str) -> dict:
    md_path = skill_dir / "SKILL.md"
    if not md_path.exists():
        return {"slug": skill_dir.name, "category": "PROSE", "why": "no SKILL.md"}
    skill_md = md_path.read_text(encoding="utf-8", errors="ignore")
    try:
        eps = cg._entrypoints(skill_dir)
    except OutOfScope:
        return {
            "slug": skill_dir.name,
            "category": "PROSE",
            "why": "no executable entrypoint",
        }
    runnable = sorted({Path(p).name for p in eps if cg._runner_for(Path(p).name)})
    if not runnable:
        return {
            "slug": skill_dir.name,
            "category": "PROSE",
            "why": "no py/sh/node entrypoint",
        }

    user = (
        "TOOL FILENAMES:\n"
        + "\n".join(f"  - {t}" for t in runnable)
        + "\n\n--- SKILL.md ---\n"
        + skill_md
    )
    payload = {
        "model": model,
        "max_tokens": 512,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        resp = cg._http_post(api_key, payload)
        text = "".join(
            b.get("text", "")
            for b in resp.get("content", [])
            if b.get("type") == "text"
        )
        obj = cg._extract_json(text)
        cat = obj.get("category", "").strip().upper()
        if cat not in CATEGORIES:
            cat = "LIBRARY"  # unparseable category -> conservative non-addressable
        return {
            "slug": skill_dir.name,
            "category": cat,
            "why": obj.get("why", "")[:200],
        }
    except Exception as e:
        return {
            "slug": skill_dir.name,
            "category": "LIBRARY",
            "why": f"classify error: {type(e).__name__}",
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample_dir", type=Path)
    ap.add_argument(
        "--link", type=Path, help="symlink LOCAL_DETERMINISTIC skills into this dir"
    )
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    api_key = cg._load_key()
    dirs = sorted(d for d in args.sample_dir.iterdir() if d.is_dir())
    rows = []
    for d in dirs:
        r = classify_one(d, api_key, args.model)
        rows.append(r)
        print(f"  {r['category']:20} {r['slug']:42} {r['why'][:60]}", file=sys.stderr)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    local = [r["slug"] for r in rows if r["category"] == "LOCAL_DETERMINISTIC"]

    print("\n== classification ==", file=sys.stderr)
    for k in ["LOCAL_DETERMINISTIC", "NETWORK", "STOCHASTIC", "LIBRARY", "PROSE"]:
        if counts.get(k):
            print(f"  {k:20} {counts[k]}", file=sys.stderr)
    print(
        f"\n  addressable (LOCAL_DETERMINISTIC): {len(local)}/{len(rows)}",
        file=sys.stderr,
    )

    if args.link and local:
        args.link.mkdir(parents=True, exist_ok=True)
        for slug in local:
            dest = args.link / slug
            if not dest.exists():
                dest.symlink_to((args.sample_dir / slug).resolve())
        print(
            f"  [linked {len(local)} addressable skills into {args.link}]",
            file=sys.stderr,
        )

    summary = {
        "sample_dir": str(args.sample_dir),
        "model": args.model,
        "counts": counts,
        "local_deterministic": local,
        "rows": rows,
    }
    blob = json.dumps(summary, indent=2)
    if args.out:
        args.out.write_text(blob)
    if args.as_json:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
