# Prose-property prove — certifying a stated property of a real ClawHub tool

The third demo in the trio (see [`../README.md`](../README.md)). It tests the
"prose-skill compromise": a skill's advice prose isn't re-derivable, but **property
claims** its prose makes about its bundled tools (roundtrip / idempotence /
schema-conformance) sometimes are — via `relyable-skills prove`, which proves a
property NON-VACUOUS by mutation (no consumer goldens).

We point it at a **real ClawHub skill**: `clean-json-toolkit`'s `flatten.py`, whose
SKILL.md claims it is *"Roundtrip-safe."*

## Run

```bash
openclaw skills install clean-json-toolkit --global          # get the real skill
RELYABLE_SKILLS=/path/to/venv/bin/relyable-skills \
    bash run_prove.sh                                        # needs relyable[prove]
```

`run_prove.sh` extracts `flatten_obj`/`unflatten_obj` **verbatim** from the installed
skill (no vendoring), then runs `prove --kind round_trip` against the `spec.json`
inputs.

## Outcome (see `PROVE_RUN.md`)

`prove` returns **VACUOUS** — 43/107 mutants survive, so it **refuses to certify** the
prose claim via `round_trip` and writes no grader. That refusal is the honest, correct
behavior, and inspection shows *why*: `round_trip` only pins the composition
`unflatten(flatten(x))==x`, never the intermediate key format, so format-changing
mutations (and equivalent mutants) survive — and enriching inputs doesn't change it.

**The honest lesson:** the prose-property path is real machinery that fails closed
correctly, but it only certifies properties strong enough to pin behavior. For
`flatten`, that means a tighter property (`schema_conformance` on the flat form) or the
consumer's goldens (the executable I/O gate) — both existing relyable surfaces. The
prose-property compromise **narrows** the prose-skill trust question; it does not
rescue "vet every skill."
