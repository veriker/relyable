#!/usr/bin/env bash
# run_prove.sh — certify a PROSE-STATED property of a REAL ClawHub skill, no goldens.
#
# clean-json-toolkit's SKILL.md says flatten.py is "Reversible with --unflatten.
# Roundtrip-safe." That prose claim is a `round_trip` PROPERTY. `relyable-skills
# prove` certifies it the only honest way — it drives mutmut over the real functions
# and requires the property (as a test) to KILL the mutants. A survivor = the claim
# asserts too little (vacuous), no grader written. No consumer goldens involved; the
# anti-vacuity gate is the oracle.
#
# This is the "compromise" for prose skills: a class of prose claims (roundtrip /
# idempotence / schema-conformance) about a skill's BUNDLED TOOLS are machine-provable
# even though the skill's advice prose is not. Out of scope: the advice itself.
#
# The candidate is EXTRACTED VERBATIM from the installed skill (the two pure functions
# flatten_obj/unflatten_obj), dropping only flatten.py's unused `from _common import`
# CLI plumbing — we vendor nothing; we prove the real source.
#
# Requires: `relyable-skills` (set RELYABLE_SKILLS to its path) with mutmut installed
# (`pip install relyable[prove]`), python3, and the clean-json-toolkit skill installed
# (`openclaw skills install clean-json-toolkit --global`) or CLEAN_JSON_FLATTEN set.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVE="${RELYABLE_SKILLS:-relyable-skills}"
# Default: the roundtrip-safe claim. Override to reproduce the boundary probe, e.g.
#   KIND=schema_conformance SPEC=spec_schema_loose.json bash run_prove.sh
#   KIND=schema_conformance SPEC=spec_schema_tight.json bash run_prove.sh
KIND="${KIND:-round_trip}"
SPEC="${SPEC:-spec.json}"
case "$SPEC" in /*) :;; *) SPEC="$HERE/$SPEC";; esac
# prove resolves the `mutmut` binary off PATH; if RELYABLE_SKILLS is an explicit
# venv path, put its bin dir first so the co-installed mutmut (not a stray ~/.local
# one) is the one that runs — otherwise mutmut can silently produce 0 mutants.
case "$PROVE" in */*) export PATH="$(cd "$(dirname "$PROVE")" && pwd):$PATH";; esac
FLATTEN="${CLEAN_JSON_FLATTEN:-$HOME/.openclaw/skills/clean-json-toolkit/scripts/flatten.py}"
WORK="$(mktemp -d -t prove-rt-XXXX)"

if [ ! -f "$FLATTEN" ]; then
  echo "flatten.py not found at $FLATTEN" >&2
  echo "install it: openclaw skills install clean-json-toolkit --global   (or set CLEAN_JSON_FLATTEN)" >&2
  exit 2
fi

echo "== extracting flatten_obj/unflatten_obj VERBATIM from the real skill =="
python3 - "$FLATTEN" > "$WORK/candidate.py" <<'PY'
import ast, sys
src = open(sys.argv[1], encoding="utf-8").read()
tree = ast.parse(src)
want = {"flatten_obj", "unflatten_obj"}
segs = [ast.get_source_segment(src, n) for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in want]
assert len(segs) == 2, f"expected 2 functions, found {len(segs)}"
print("# extracted verbatim from clean-json-toolkit/scripts/flatten.py (MIT)")
print("from __future__ import annotations")
print("import json, re, sys")
print("from pathlib import Path")
print("from typing import Any, Dict, List")
print()
print("\n\n".join(segs))
PY
echo "  candidate: $WORK/candidate.py ($(wc -l < "$WORK/candidate.py") lines)"

echo "== prove --kind $KIND --spec $(basename "$SPEC") (mutmut must die) =="
set +e
"$PROVE" prove "$WORK/candidate.py" --kind "$KIND" \
    --spec "$SPEC" --grader-out "$WORK/flatten_grader.py"
rc=$?
set -e
echo
if [ "$rc" -eq 0 ]; then
  echo "RESULT: CERTIFIED (exit 0) — the prose 'roundtrip-safe' claim is NON-VACUOUS."
  echo "  grader written: $WORK/flatten_grader.py ($(wc -l < "$WORK/flatten_grader.py") lines)"
elif [ "$rc" -eq 1 ]; then
  echo "RESULT: VACUOUS (exit 1) — survivors listed above; NO grader written (honest)."
else
  echo "RESULT: REFUSED/usage (exit $rc)."
fi
echo "[scratch: $WORK]"
exit "$rc"
