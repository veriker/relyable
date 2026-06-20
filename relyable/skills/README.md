# relyable.skills — re-derive a skill's claimed verdict before admitting it

> The **skills surface** of the [relyable](../../) agent-trust suite (on the
> veriker substrate). Consumes `relyable.gate`.

An agent (or a registry it pulls skills from) ships a skill body plus an
*asserted* "this passes" label. This binding **never reads that label for the
decision.** It assembles the candidate into a real veriker bundle, pins the
grader to the **consumer's own trusted copy**, and lets veriker's verifier re-run
the candidate against held-out goldens through the gated re-derivation lane. A
skill is usable iff that re-derivation reproduces.

> A poisoned or unverifiable label is **inert** — dropped, never passed through as
> a weak signal. Worst case the registry is empty, never net-negative.

## Why (the evidence)

The ALE experiment line measured what a trust label does to an agent:

- **Exp 3** — where skills *cannot* be cheaply self-vetted, the admission verdict
  is the whole story: gated holds (0.90), ungated collapses (0.00).
- **Exp 4 / 5** — a poisoned or unlabeled registry is *itself harmful* (an agent
  follows a poisoned label blindly; an unlabeled registry scores below baseline).
  **Label integrity must be infrastructure, not recipient diligence.**
- **Exp 6 (powered, n=50)** — the re-derivable label is **harm-neutralization, not
  uplift**: it restores the baseline an unvetted registry erodes.
- **Exp 2 (honest boundary)** — where skills are cheaply self-vettable, the gate is
  **redundant, not harmful**. We disclose this; it sharpens the claim.

The honest one-liner: *"stops your agent from following a poisoned skill label,
and restores the baseline an unvetted registry erodes."*

## Use it

```python
from pathlib import Path
from relyable.skills import admit_directory, usable_skills

# Your own trusted grader: held-out goldens + a reference solver that exits 0
# iff a candidate reproduces. See relyable/skills/examples/interval_grader.py.
grader = Path("my_grader.py")

verdicts = admit_directory(Path("./skills"), grader_src=grader, permit_execution=True)
for v in usable_skills(verdicts):
    ...  # only skills veriker independently re-derived
```

Or as a pipeline / skill-load gate (fail-closed: any rejected candidate is a
non-zero exit):

```bash
relyable-skills admit ./skills --grader ./my_grader.py --run
relyable-skills admit ./skills --grader ./my_grader.py --json
```

`--run` (`permit_execution=True`) vets by running candidates on a disposable host.
Without it the gate won't run untrusted code and every skill is
could-not-conclude / unadmitted.

## The grader is the trust root

You supply the grader; it is pinned (byte-identical digest) into every bundle, so
a producer cannot ship a lying grader and a hand-assembled bundle naming a
different grader fails the pin. The grader owns the held-out goldens and the
reference solver — they are never bundle-supplied. Start from the worked,
stdlib-only `examples/interval_grader.py` and replace its reference
implementations + held-out generation with your domain.

## Scaffolding a grader from a blank page (`relyable-skills init`)

Writing a grader from scratch is the blank-page problem. `init` attacks it: point
it at a skill (and the repo it lives in) and it detects the **cheapest trust-root
rung** that actually applies and scaffolds the matching grader, so you *confirm* a
detected grader instead of authoring one.

```bash
relyable-skills init ./mypkg/skills/foo.py --smoke      # detect + scaffold + check
relyable-skills init ./mypkg/skills/foo.py --out grader.py --json
```

The ladder, cheapest first:

- **T1 — a pre-existing suite the agent didn't author.** The repo already has a
  pytest suite covering the skill → `init` emits a complete, runnable grader (via
  `verdict_grader`) that drops the candidate into place and runs that suite. **The
  only auto-fillable rung** — no human edits.
- **T2 — structured output + schema** → scaffolds a schema-conformance **property**
  template (a PROPOSAL to confirm, not auto-pinned).
- **T0 — a pure deterministic entrypoint** → a determinism template (proves
  reproducibility, never correctness — the weakest root).
- **T5 — nothing detectable** → the general held-out-goldens shape for a human to
  fill (the `interval_grader` template, emptied).

Detection is static and heuristic; every result carries an honest `caveat` naming
what you must still confirm. T0/T2/T5 emit FILL-ME templates — they are scaffolds,
not finished trust roots. A T2 property template is exactly what `prove` (below)
graduates into a certified root.

## Proving a property is non-vacuous (`relyable-skills prove`)

A code skill rarely ships held-out goldens, but its author can PROPOSE a structural
property the output must satisfy — `round_trip`, `idempotence`, `schema_conformance`.
A proposed property is only a trust root once proven **non-vacuous**: a property no
broken candidate can fail asserts nothing. `prove` certifies it the only honest way
— it drives a real mutation engine (mutmut) over the current skill and requires the
property (run as a test) to **kill the mutants**. A survivor is direct evidence the
property asserts too little.

```bash
# spec.json: {"kind": "round_trip",
#             "contract_fn": {"forward": "encode", "inverse": "decode"},
#             "inputs": [["hello"], ["world"]]}
relyable-skills prove ./skills/codec.py --kind round_trip \
    --spec spec.json --grader-out codec_grader.py
```

Exit `0` = certified (the grader is written; pin it as `grader_src`), `1` = vacuous
(survivors listed, **no grader written**), `2` = refused / usage error. The
certificate is **scope-bound**: it records the reference-candidate digest, engine,
floor, mutmut version, and mutant count, so reuse outside that scope is visible.
Needs mutmut on PATH (`pip install relyable[prove]`); it fails **closed** if mutmut
is absent — installing a package is not user friction, hand-authoring criteria is.

> **The honest catch (verbatim on every B surface):** *kills-mutants proves
> NON-VACUOUS, not correct-spec. It's an anti-vacuity gate, not a correctness oracle
> (the property is anchored to the candidate-at-proposal-time as pseudo-ground-truth).
> T2 stays genuinely weaker than T1.*

**`determinism` is deliberately NOT provable.** It near-universally survives
mutation — a wrong-but-deterministic mutant still passes `f(x) == f(x)` — so
`prove --kind determinism` is refused up front. Determinism stays a confirm-by-hand
T0 template (`relyable init`), never a certificate. `invariant` (an arbitrary author
predicate) is deferred to v1.1.

## What this does and does NOT prove

- **Does:** make a skill's claimed verdict un-faked — the consumer's own grader
  re-runs the candidate; the claim is never an input. A poisoned bundle is inert.
- **Does not:** prove a grader is *complete*. A skill that passes the held-out
  goldens can still be wrong on inputs the grader never checks. The grader's
  coverage is the consumer's responsibility — the gate guarantees the verdict was
  *re-derived by your grader*, not that your grader is exhaustive.
- Sandboxing untrusted candidate code is the host's job (`permit_execution=True`
  runs it). Run it where running arbitrary code is acceptable.
