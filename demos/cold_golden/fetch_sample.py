#!/usr/bin/env python3
"""fetch_sample.py — download a fresh random sample of live ClawHub skills to a dir.

``cold_golden.py`` grades a directory of installed skills. This pulls a NEW sample
straight from the ClawHub archive API (no ``openclaw`` install needed) into
``<out>/<slug>/`` so the cold-golden harness can run over a different, larger,
seed-pinned set than the fixed ~/.openclaw sample.

ClawHub has no catalog-count endpoint; the sampling frame is the union of single-
character search queries (the same honest frame ``sample_clawhub.py`` uses) — a frame,
not the whole catalog. Pin ``--seed`` + record the date to make a run reproducible-ish
(upstream content can change).

    python fetch_sample.py OUT_DIR [N] [--seed S] [--slugs a b c]
"""

from __future__ import annotations

import argparse
import io
import json
import random
import string
import sys
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://clawhub.ai"
_UA = {"User-Agent": "relyable-cold-golden-fetch/0.1"}


def _get(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url: str, timeout: int = 40) -> dict:
    return json.loads(_get(url, timeout))


def build_frame() -> list[str]:
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


def fetch_one(slug: str, out_dir: Path) -> tuple[str, str]:
    """Download + extract one skill into out_dir/<slug>/. Returns (slug, status)."""
    try:
        inst = _json(f"{BASE}/api/v1/skills/{urllib.parse.quote(slug)}/install")
        durl = inst.get("archive", {}).get("downloadUrl")
        if not durl:
            return slug, "NO_ARCHIVE"
        if durl.startswith("/"):
            durl = BASE + durl
        z = zipfile.ZipFile(io.BytesIO(_get(durl)))
        names = z.namelist()
        skmd = [n for n in names if n.rstrip("/").split("/")[-1] == "SKILL.md"]
        if not skmd:
            return slug, "NO_SKILL_MD"
        prefix = skmd[0][: -len("SKILL.md")]
        dest = out_dir / slug.replace("/", "__")
        for n in names:
            if n.endswith("/"):
                continue
            rel = n[len(prefix) :] if prefix and n.startswith(prefix) else n
            if not rel:
                continue
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(z.read(n))
        return slug, "OK"
    except Exception as e:
        return slug, f"ERR:{type(e).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("n", type=int, nargs="?", default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--slugs", nargs="*", help="explicit slugs (skips the random frame)"
    )
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.slugs:
        sample = args.slugs
    else:
        print(
            "[building slug frame (query-union; no catalog endpoint)...]",
            file=sys.stderr,
        )
        frame = build_frame()
        print(f"[frame: {len(frame)} distinct slugs]", file=sys.stderr)
        sample = random.Random(args.seed).sample(frame, min(args.n, len(frame)))
    print(f"[fetching {len(sample)} slugs -> {args.out_dir}]", file=sys.stderr)

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed(
            {ex.submit(fetch_one, s, args.out_dir): s for s in sample}
        ):
            slug, status = fut.result()
            key = status if status == "OK" else status.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            if status != "OK":
                print(f"  skip {slug}: {status}", file=sys.stderr)
    print(f"[done] {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
