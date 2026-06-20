#!/usr/bin/env python3
"""sample_clawhub.py — measure how often ClawHub skills ship ANY checkable spec.

``run_self_spec.py`` grades a directory of skills you already have installed. This
companion answers the *marketplace-scale* question behind it: across a random sample
of live ClawHub skills, what fraction ship a machine-checkable behavioral spec at
all — a shipped test suite (S-A), a documented command+output example (S-B), or
example fixtures (S-C)?

It uses the SAME detector the rest of relyable does
(``relyable.skills.self_spec.detect_self_spec``) — this is detection only, so it
measures whether a spec is *shipped*, not whether the bytes *pass* it. Measuring
"passes" at scale means executing untrusted code; that is a separate, sandboxed run
(``run_self_spec.py`` with ``permit_execution``), deliberately not done here.

    python sample_clawhub.py [N] [--seed S] [--json] [--out FILE]

Honest framing carried in the output:
- ClawHub exposes **no catalog-enumeration / count endpoint**. The sampling frame is
  built as the union of single-character search queries (``a``..``z``, ``0``..``9``),
  which surfaces ~9k distinct slugs but is a FRAME, not the whole catalog — the true
  total is larger and unknown. The reported rate is "of the sampled, gradeable
  skills", and the frame's search-union bias is disclosed, not hidden.
- ``A`` = ships a detectable self-spec. NOT "verified", NOT "passes".
- Network + upstream content can change; pin ``--seed`` and record the date to make a
  run reproducible-ish (slugs can be added/removed upstream between runs).
"""

from __future__ import annotations

import argparse
import io
import json
import random
import string
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Run from the repo without an install: add the package root to sys.path.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from relyable.skills import self_spec as ss  # noqa: E402

BASE = "https://clawhub.ai"
_UA = {"User-Agent": "relyable-sample-clawhub/0.1"}


def _get(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url: str, timeout: int = 40) -> dict:
    return json.loads(_get(url, timeout))


def build_frame() -> list[str]:
    """Union of single-character search queries → a large (but not exhaustive) set of
    distinct slugs. ClawHub has no list-all endpoint, so this is the honest frame."""
    slugs: set[str] = set()
    for term in list(string.ascii_lowercase) + list("0123456789"):
        try:
            res = _json(f"{BASE}/api/v1/search?q={term}&limit=100000").get(
                "results", []
            )
        except Exception:
            continue
        for it in res:
            if it.get("slug"):
                slugs.add(it["slug"])
    return sorted(slugs)


def detect_one(slug: str) -> tuple[str, str, str | None]:
    """Download a skill archive, extract it, run the real detector. Returns
    (slug, status, tier) where status is OK / NO_ARCHIVE / NO_SKILL_MD / ERR:*."""
    try:
        inst = _json(f"{BASE}/api/v1/skills/{urllib.parse.quote(slug)}/install")
        durl = inst.get("archive", {}).get("downloadUrl")
        if not durl:
            return slug, "NO_ARCHIVE", None
        if durl.startswith("/"):
            durl = BASE + durl
        z = zipfile.ZipFile(io.BytesIO(_get(durl)))
        names = z.namelist()
        skmd = [n for n in names if n.rstrip("/").split("/")[-1] == "SKILL.md"]
        if not skmd:
            return slug, "NO_SKILL_MD", None
        # Strip a single top-level archive folder if present.
        prefix = skmd[0][: -len("SKILL.md")]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for n in names:
                if n.endswith("/"):
                    continue
                rel = n[len(prefix) :] if prefix and n.startswith(prefix) else n
                if not rel:
                    continue
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(z.read(n))
            spec = ss.detect_self_spec(root)
            return slug, "OK", spec.tier
    except Exception as e:  # network / zip / parse — count, never crash the sweep
        return slug, f"ERR:{type(e).__name__}", None


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((center - margin) / denom, (center + margin) / denom)


def measure(n: int, seed: int, workers: int = 12) -> dict:
    print(
        "[building slug frame (no catalog-count endpoint; query-union)...]", flush=True
    )
    frame = build_frame()
    print(f"[frame: {len(frame)} distinct slugs]", flush=True)
    rng = random.Random(seed)
    sample = rng.sample(frame, min(n, len(frame)))
    print(f"[sampling N={len(sample)} seed={seed}]", flush=True)
    rows: list[tuple[str, str, str | None]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(detect_one, s): s for s in sample}
        for f in as_completed(futs):
            rows.append(f.result())
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(sample)}", flush=True)

    status = Counter(r[1] for r in rows)
    ok = [r for r in rows if r[1] == "OK"]
    tiers = Counter(r[2] for r in ok)
    n_ok = len(ok)
    a = sum(1 for r in ok if r[2] != "none")
    lo, hi = _wilson(a, n_ok)
    return {
        "frame_size": len(frame),
        "N_sampled": len(sample),
        "seed": seed,
        "fetch_status": dict(status),
        "n_gradeable": n_ok,
        "A_ships_self_spec": a,
        "A_pct": round(100 * a / n_ok, 2) if n_ok else None,
        "ships_nothing_pct": round(100 * (n_ok - a) / n_ok, 2) if n_ok else None,
        "wilson95_A_pct": [round(100 * lo, 2), round(100 * hi, 2)],
        "by_tier": {k: v for k, v in tiers.items() if k != "none"},
        "examples_with_spec": sorted(r[0] for r in ok if r[2] != "none"),
    }


def _fmt(s: dict) -> str:
    L = [
        f"CLAWHUB SAMPLE — ships a machine-checkable self-spec?  (frame={s['frame_size']} slugs, "
        f"N={s['N_sampled']}, seed={s['seed']})",
        f"  gradeable skills (downloaded + has SKILL.md):  {s['n_gradeable']}",
        f"  ships ANY self-spec:  A = {s['A_ships_self_spec']}  "
        f"({s['A_pct']}%  95% CI {s['wilson95_A_pct'][0]}–{s['wilson95_A_pct'][1]}%)",
        f"  ships nothing checkable:  {s['ships_nothing_pct']}%",
        f"  by tier (of the A): {s['by_tier'] or '(none)'}",
        f"  fetch status: {s['fetch_status']}",
        "  A = SHIPS a detectable spec, not 'passes'. Frame = search-union, not full catalog.",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "n", nargs="?", type=int, default=1000, help="sample size (default 1000)"
    )
    ap.add_argument(
        "--seed", type=int, default=20260619, help="RNG seed for the sample"
    )
    ap.add_argument("--workers", type=int, default=12, help="concurrent downloads")
    ap.add_argument("--json", action="store_true", help="print full result as JSON")
    ap.add_argument("--out", help="write the JSON result to this path")
    args = ap.parse_args()
    result = measure(args.n, args.seed, args.workers)
    print("\n==== RESULT ====")
    print(json.dumps(result, indent=2) if args.json else _fmt(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
