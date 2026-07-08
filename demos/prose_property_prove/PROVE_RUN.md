# Proving a prose-stated property on a real ClawHub skill — captured run

The "prose-skill compromise": a skill's *advice* prose isn't re-derivable, but some
prose **property claims** about its bundled tools are. `clean-json-toolkit`'s SKILL.md
says `flatten.py` is *"Reversible with `--unflatten`. Roundtrip-safe."* That is a
`round_trip` property. `relyable-skills prove` is the honest test of it — drive a real
mutation engine (mutmut) over the tool and require the property to **kill the mutants**.
No consumer goldens; the anti-vacuity gate is the oracle.

Reproduce: `RELYABLE_SKILLS=/path/to/venv/bin/relyable-skills bash run_prove.sh`
(needs `relyable[prove]` → mutmut, and the skill installed). The candidate is the two
functions extracted **verbatim** from the real installed `flatten.py` (MIT) — we vendor
nothing.

## Result: prove REFUSES to certify (VACUOUS) — and that is the honest, correct outcome

```
== prove --kind round_trip (mutmut must die) ==
VACUOUS (rejected)  kind=round_trip  engine=mutmut 3.6.0
  64/107 mutants killed; 43 survived (<= max 0)
  reason: 43 survivor(s) > max 0 — property is vacuous
RESULT: VACUOUS (exit 1) — NO grader written (honest).
```

`prove` did **not** rubber-stamp the prose claim. 43 of 107 mutants survive, so the
`round_trip` property — *as a non-vacuity proof for this tool* — asserts too little, and
no certified grader is written. This is relyable's whole thesis enacted on real code:
it refuses rather than emit a "verified" it can't back.

## Why it's vacuous (verified, not asserted)

Two things, both established empirically:

1. **It is structural, not a coverage gap.** Re-running with deliberately enriched
   inputs (deep nesting, lists-of-lists, empties, nulls/bools, dotted keys — 11 cases vs
   5) produced the **identical 43 survivors**. More inputs do not help.

2. **Inspecting the survivors (`mutmut show`) shows two kinds:**
   - **round_trip-invisible mutations** — e.g. `index_style="dot"` → `"XXdotXX"`, or
     passing `index_style=None` in the recursion. `round_trip` only checks
     `unflatten(flatten(x)) == x`; it never pins the *intermediate flat-key format*, so
     a mutation that changes how keys are formatted survives as long as `unflatten`
     still parses it back. The composition guarantee is blind to the representation.
   - **equivalent mutants** — e.g. `unflatten`'s list-slot init `{}/[]` → `None`, which
     the very next line overwrites. No test can kill an equivalent mutant.

## What this means for the prose-skill compromise (the honest boundary)

- The machinery is **real and applies to a real skill**: a prose property claim was
  turned into a deterministic, goldens-free re-derivation attempt. That part of the
  compromise stands.
- But on the **first real tool we tried, the natural property (`round_trip`) is too weak
  to certify.** Certifying `flatten` would need a **tighter property** —
  `schema_conformance` pinning the flat-key format (so the intermediate is constrained,
  not just the composition) — or simply the **consumer's goldens** (the executable I/O
  gate from the other demos). Both route back to existing relyable surfaces.
- So the prose-property path **narrows** the prose-skill question rather than rescuing
  it: it converts "is this skill good?" (un-answerable) into "does this specific stated
  property of this bundled tool hold non-vacuously?" — answerable, fail-closed, but only
  for properties strong enough to pin behavior, which `round_trip`-on-`flatten` is not.

The honest one-liner: **prove works, and here it correctly says "I can't certify this
claim this way" — which is the product, not a failure of it.**

## Boundary probe: does a property that pins the INTERMEDIATE certify? (no)

`round_trip` is composition-only, so we tested `schema_conformance` — which checks the
*output* against a schema — to see if pinning flatten's flat form certifies where
round_trip couldn't. It does not, and the trend is the actual finding:

| property / schema | mutants killed (of 107) | verdict |
|---|---|---|
| `round_trip` (composition `unflatten(flatten(x))==x`) | 64 | VACUOUS (43 survive) |
| `schema_conformance`, schema `{"type":"object"}` | 4 | VACUOUS (103 survive) |
| `schema_conformance`, schema pinning ONE input's exact flat keys+types | 16 | VACUOUS (91 survive) |

Why none certify, and why the trend is the point:

- relyable's `_conforms` is a minimal JSON-Schema subset (type / required / properties /
  items). It **cannot express** "every value is a scalar" or "keys match the dot-format"
  — the invariants that actually distinguish a correct `flatten` from a broken or
  format-mutated one. So a loose schema is satisfied by any dict (4 killed).
- Tightening the schema to name a specific input's exact flat keys + types kills more
  (16) — but that schema **only fits that one input shape**. To pin `flatten` across its
  input space (dicts, nested dicts, lists, lists-of-dicts, empties) you would need one
  expected shape per input class — which **is a full golden set**. Tightening
  `schema_conformance` toward certification *degenerates into the consumer-goldens path*
  (the executable I/O gate from the sibling demos).

**Boundary, stated cleanly:** `flatten` is **not certifiable by any of prove's
property kinds** — `round_trip` is composition-blind, `schema_conformance`'s schema
language can't pin the flat form, and `idempotence` doesn't apply. It is certifiable
**only** via the consumer's goldens. The prose-property path certifies properties that
*pin behavior on their own* (e.g. a true codec, where relyable's own live test
`tests/test_anti_vacuity.py::test_live_round_trip_kills_all_mutants` certifies and
passes) — `flatten` is not such a tool. So the line between "prose-property certifiable"
and "needs goldens" runs **right through this skill**, on the goldens side.
