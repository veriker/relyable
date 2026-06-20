#!/usr/bin/env python3
"""interval_grader.py — a worked re-derivation GRADER for skill admission.

This is a relyable.skills grader (installed into a bundle's ``re_derive/`` and run
by veriker's re-derivation lane under the consumer's ``permit_execution``
decision). It runs in a subprocess with a timeout and exits 0 iff the committed
candidate skill reproduces the reference golden on the grader's held-out
instances. Per the auditor-independence contract: NO veriker import here, stdlib
only.

WHY THIS IS NOT "the producer grading its own homework": the skills binding
INSTALLS this exact file (the consumer's own trusted copy) into every bundle's
re_derive/ when it assembles the bundle — the producer's bundle supplies ONLY the
candidate skill body (digest-bound by the manifest). So the held-out seeds, the
reference solver, and the comparison are all consumer-distribution; the bundle
cannot ship a lying grader, and a hand-assembled bundle naming a different grader
fails the digest-pin.

It grades three example skill "kinds" over genomics intervals (parse / merge /
sort). Replace the reference implementations + held-out generation with your own
domain to make a real grader. Re-derivation steps:
  1. Read skill/meta.json  -> {skill_id, kind}.
  2. Read skill/candidate.py -> the candidate body; exec it (gated: this lane IS
     veriker's bundle-code-exec path) and pull the kind's contract function.
  3. For each pinned held-out seed: synthesize the instance, compute the golden
     from the reference solver, run the candidate, compare exactly.
  4. Exit 0 on full match; exit 1 with [SKILL_REDER_FAIL] <reason> on stderr.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

# --- consumer-distribution authority (pinned HERE, never bundle-supplied) ------
CONTRACT_FN = {"parse": "parse_bed3", "merge": "merge_intervals", "sort": "sort_union"}
HOLDOUT_SEEDS = {"parse": (4001, 4002), "merge": (4001, 4002), "sort": (4001, 4002)}


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


# --- reference implementations (the GOLDEN source) ----------------------------
def parse_bed3(text):
    rows = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(("track", "browser")):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            parts = s.split()
        if len(parts) < 3:
            continue
        rows.append((parts[0], int(parts[1]), int(parts[2])))
    return rows


def merge_intervals(intervals):
    """Half-open merge: [a,b) and [c,d) overlap iff c < b; abutting NOT merged."""
    by_chrom = {}
    for chrom, start, end in intervals:
        by_chrom.setdefault(chrom, []).append((start, end))
    merged = []
    for chrom, spans in by_chrom.items():
        spans.sort()
        cs, ce = spans[0]
        for s, e in spans[1:]:
            if s < ce:
                ce = max(ce, e)
            else:
                merged.append((chrom, cs, ce))
                cs, ce = s, e
        merged.append((chrom, cs, ce))
    return merged


def _chrom_rank(chrom):
    body = chrom[3:] if chrom.startswith("chr") else chrom
    special = {"X": 100, "Y": 101, "M": 102, "MT": 102}
    if body in special:
        return (special[body], 0)
    try:
        return (int(body), 0)
    except ValueError:
        return (200, sum(ord(c) for c in body))


def sort_union(intervals):
    return sorted(intervals, key=lambda r: (_chrom_rank(r[0]), r[1], r[2]))


# --- held-out generation (deterministic; structural merge discriminator) -------
def _prng(seed):
    state = hashlib.sha256(str(seed).encode()).digest()
    while True:
        for b in state:
            yield b
        state = hashlib.sha256(state).digest()


def gen_holdout(seed):
    """Held-out instance as {filename: BED text}. STRUCTURALLY guarantees a
    correct half-open solver and a ``<=``-idiom solver diverge: chr1 carries ONLY
    the book-ended pair (random fill is confined to chrX, so nothing bridges the
    chr1 boundary); chr2 carries only a truly-overlapping pair (the agree case)."""
    gen = _prng(seed)
    base = 10_000 + seed * 137
    files = {"intervals_a.bed": [], "intervals_b.bed": []}
    for i in range(6):
        start = base + next(gen) * 7 + i * 500
        end = start + 40 + next(gen) % 60
        fname = "intervals_a.bed" if i % 2 == 0 else "intervals_b.bed"
        files[fname].append(("chrX", start, end))
    p = base + 3000
    files["intervals_a.bed"].append(("chr1", p, p + 50))
    files["intervals_b.bed"].append(("chr1", p + 50, p + 90))
    q = base + 5000
    files["intervals_a.bed"].append(("chr2", q, q + 80))
    files["intervals_b.bed"].append(("chr2", q + 30, q + 120))
    return {
        f: "".join(f"{c}\t{s}\t{e}\n" for c, s, e in rows) for f, rows in files.items()
    }


def _pooled(holdout):
    rows = []
    for text in holdout.values():
        rows.extend(parse_bed3(text))
    return rows


def _as_rows(rows):
    return [(str(r[0]), int(r[1]), int(r[2])) for r in rows]


def _cells(kind):
    """Synthesize this kind's held-out cells (args + golden + compare mode)."""
    cells = []
    for seed in HOLDOUT_SEEDS[kind]:
        inst = gen_holdout(seed)
        if kind == "parse":
            text = inst["intervals_a.bed"]
            cells.append(
                (
                    f"parse_s{seed}",
                    (text,),
                    [list(t) for t in parse_bed3(text)],
                    "exact",
                )
            )
        elif kind == "merge":
            pooled = _pooled(inst)
            cells.append(
                (
                    f"merge_s{seed}",
                    ([list(t) for t in pooled],),
                    [list(t) for t in merge_intervals(pooled)],
                    "set",
                )
            )
        elif kind == "sort":
            pooled = _pooled(inst)
            union = merge_intervals(pooled)
            scrambled = list(reversed(union))
            cells.append(
                (
                    f"sort_s{seed}",
                    ([list(t) for t in scrambled],),
                    [list(t) for t in sort_union(union)],
                    "exact",
                )
            )
    return cells


def _match(compare, got, golden):
    try:
        g = _as_rows(got)
    except (TypeError, ValueError, IndexError):
        return False, "shape"
    want = _as_rows(golden)
    if compare == "set":
        return set(g) == set(want), "set"
    return g == want, "exact"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    args = ap.parse_args()
    bundle = Path(args.bundle_dir)

    try:
        meta = json.loads((bundle / "skill" / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"meta_unreadable: {e}")
    kind = meta.get("kind")
    if kind not in CONTRACT_FN:
        return _fail(f"unknown_kind: {kind!r}")

    try:
        body = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    except OSError as e:
        return _fail(f"candidate_unreadable: {e}")
    try:
        ast.parse(body)
    except SyntaxError as e:
        return _fail(f"parse_fail: {e}")
    ns: dict = {}
    try:
        exec(body, ns)  # noqa: S102 — bundle-code-exec; THIS is veriker's gated lane
    except Exception as e:  # noqa: BLE001
        return _fail(f"import_fail: {type(e).__name__}: {e}")
    fn = ns.get(CONTRACT_FN[kind])
    if not callable(fn):
        return _fail(f"no_contract_fn: {CONTRACT_FN[kind]!r}")

    cells = _cells(kind)
    if not cells:
        return _fail(f"no_holdout_cells: {kind!r}")  # fail-closed, never all([])->pass
    for hid, call_args, golden, compare in cells:
        try:
            got = fn(*[json.loads(json.dumps(a)) for a in call_args])
        except Exception as e:  # noqa: BLE001
            return _fail(f"{hid}: runtime_fail: {type(e).__name__}: {e}")
        ok, _ = _match(compare, got, golden)
        if not ok:
            return _fail(f"{hid}: mismatch ({compare})")
    return 0  # full match -> RE_DERIVED


if __name__ == "__main__":
    sys.exit(main())
