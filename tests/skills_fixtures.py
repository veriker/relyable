"""skills_fixtures.py — skill bodies + the fault-matrix bundle builder for the
relyable.skills tests.

Each skill is assembled into a REAL veriker bundle pinned to the worked
``interval_grader`` example. The fault matrix spans every way a registry entry can
be wrong; each row's expected outcome is the verdict veriker must reach. The
discriminator is ``MERGE_LE_IDIOM``: the closed-interval ``<=`` idiom that
collapses book-ended intervals, shipped CLAIMING VALIDATED — the grader runs it on
a held-out instance with a book-ended pair and veriker returns a mismatch.
"""

from __future__ import annotations

from pathlib import Path

from relyable.skills.examples import interval_grader
from relyable.skills import build_skill_bundle

# The consumer's trusted grader, used as grader_src throughout the tests.
GRADER_SRC = Path(interval_grader.__file__)

MERGE_GOOD = '''\
def merge_intervals(intervals):
    """Correct half-open merge: [a,b) and [c,d) overlap iff c < b."""
    by_chrom = {}
    for chrom, start, end in intervals:
        by_chrom.setdefault(chrom, []).append((start, end))
    out = []
    for chrom, spans in by_chrom.items():
        spans.sort()
        cs, ce = spans[0]
        for s, e in spans[1:]:
            if s < ce:
                ce = max(ce, e)
            else:
                out.append((chrom, cs, ce))
                cs, ce = s, e
        out.append((chrom, cs, ce))
    return out
'''

MERGE_LE_IDIOM = '''\
def merge_intervals(intervals):
    """WRONG: `s <= ce` collapses book-ended intervals that share only a boundary."""
    by_chrom = {}
    for chrom, start, end in intervals:
        by_chrom.setdefault(chrom, []).append((start, end))
    out = []
    for chrom, spans in by_chrom.items():
        spans.sort()
        cs, ce = spans[0]
        for s, e in spans[1:]:
            if s <= ce:
                ce = max(ce, e)
            else:
                out.append((chrom, cs, ce))
                cs, ce = s, e
        out.append((chrom, cs, ce))
    return out
'''

MERGE_RAISES = """\
def merge_intervals(intervals):
    raise RuntimeError("this skill blows up at runtime")
"""

MERGE_SYNTAX_BROKEN = """\
def merge_intervals(intervals)
    return intervals  # missing colon above -> SyntaxError
"""

PARSE_GOOD = """\
def parse_bed3(text):
    rows = []
    for line in text.replace("\\r\\n", "\\n").split("\\n"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(("track", "browser")):
            continue
        parts = line.split("\\t")
        if len(parts) < 3:
            parts = s.split()
        if len(parts) < 3:
            continue
        rows.append((parts[0], int(parts[1]), int(parts[2])))
    return rows
"""

SORT_GOOD = """\
def sort_union(intervals):
    def rank(chrom):
        body = chrom[3:] if chrom.startswith("chr") else chrom
        special = {"X": 100, "Y": 101, "M": 102, "MT": 102}
        if body in special:
            return (special[body], 0)
        try:
            return (int(body), 0)
        except ValueError:
            return (200, sum(ord(c) for c in body))
    return sorted(intervals, key=lambda r: (rank(r[0]), r[1], r[2]))
"""


def _build(dest: Path, skill_id, kind, body, claimed):
    return build_skill_bundle(
        dest / skill_id,
        skill_id=skill_id,
        kind=kind,
        body=body,
        claimed_verdict=claimed,
        grader_src=GRADER_SRC,
    )


def build_bundles(dest: Path) -> list[dict]:
    """Write the fault-matrix veriker bundles under ``dest`` (one subdir per
    skill). ``tamper_body``, when set, is written over skill/candidate.py AFTER
    the manifest is built — so the file's bytes no longer match the manifest digest
    (exercising veriker's strict-SHA rail)."""
    rows = [
        ("merge_good", "merge", MERGE_GOOD, "VALIDATED", None),
        ("merge_le_idiom", "merge", MERGE_LE_IDIOM, "VALIDATED", None),
        ("parse_good", "parse", PARSE_GOOD, "VALIDATED", None),
        ("sort_good", "sort", SORT_GOOD, "VALIDATED", None),
        ("merge_broken", "merge", MERGE_SYNTAX_BROKEN, "VALIDATED", None),
        ("merge_raises", "merge", MERGE_RAISES, "VALIDATED", None),
        ("frob_unknown", "frobnicate", MERGE_GOOD, "VALIDATED", None),
        # digest tamper: built honest, then candidate.py swapped to the wrong body
        # WITHOUT updating the manifest -> veriker strict-SHA rail rejects.
        ("merge_tampered", "merge", MERGE_GOOD, "VALIDATED", MERGE_LE_IDIOM),
    ]
    dest.mkdir(parents=True, exist_ok=True)
    table: list[dict] = []
    for skill_id, kind, body, claimed, tamper_body in rows:
        bdir = _build(dest, skill_id, kind, body, claimed)
        if tamper_body is not None:
            (bdir / "skill" / "candidate.py").write_text(tamper_body, encoding="utf-8")
        table.append({"skill_id": skill_id})
    return table


def build_poisoned_bundles(dest: Path) -> list[str]:
    """A fully-poisoned bundle dir: every skill claims VALIDATED, none re-derive.
    The registry must expose ZERO usable skills (inert, not net-negative)."""
    poison = [
        ("p_merge", "merge", MERGE_LE_IDIOM),
        ("p_raise", "merge", MERGE_RAISES),
        ("p_broken", "merge", MERGE_SYNTAX_BROKEN),
        ("p_unknown", "frobnicate", MERGE_GOOD),
    ]
    dest.mkdir(parents=True, exist_ok=True)
    for skill_id, kind, body in poison:
        _build(dest, skill_id, kind, body, "VALIDATED")
    return [p[0] for p in poison]
