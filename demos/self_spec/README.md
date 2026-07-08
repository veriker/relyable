# Self-spec re-derivation — grade a skill against ITS OWN committed spec

ClawHub `verify` answers "are these the real author's bytes?" (provenance — and it
answers it correctly). This demo asks the orthogonal question: **do those authentic
bytes still reproduce what the author themselves documented?** It needs no
consumer-authored goldens — the oracle is the author's own shipped test suite,
documented input/output examples, or example fixtures.

This is the author-grounded companion to [`directory_funnel`](../directory_funnel/)
(which measures the consumer-goldens surface and found K=0) and
[`tool_bundle_rederive`](../tool_bundle_rederive/) (per-tool re-derivation on a real
bundle).

## Run it

Grading EXECUTES the skill's (untrusted) code, so it is **fail-closed**: without
`--allow-host-exec` nothing runs and every executable tool reports
`UNJUDGEABLE_NO_SANDBOX`. Pass the flag only on a disposable/sandboxed host (it's your
explicit vow); `--sandbox docker:<image>` additionally isolates the gate's
re-derivation worker (network off).

```bash
# Mechanism — fires on skills that ship a checkable example (R=1, C=1).
# --allow-host-exec REQUIRED to run anything (these fixtures are trusted/in-repo):
python run_self_spec.py fixtures --allow-host-exec

# Real ClawHub skills you have installed — run on a DISPOSABLE host, or add a sandbox:
python run_self_spec.py ~/.openclaw/skills --allow-host-exec --sandbox docker:python:3.12-slim

# Marketplace-scale: a random sample of LIVE ClawHub skills (detection only, no exec):
python sample_clawhub.py 1000 --seed 20260619     # ~1% ship any checkable spec
```

## The self-spec ladder (strongest first)

| Tier | Author artifact | Oracle |
|---|---|---|
| **S-A** | shipped pytest **suite** (`tests/` + a pytest layout) | run the suite on authentic bytes |
| **S-B** | **documented I/O example** — a `$`/`>`-anchored command + its shown output | re-run the command, compare stdout |
| **S-C** | example **fixtures** (`examples/`/`fixtures/`, `*.in`/`*.out`) | re-run on the input, compare |

## Verdicts

`REPRODUCES` · `CONTRADICTS` · `UNJUDGEABLE_{NO_SPEC,NONDET,ENV,UNPARSE,NO_SANDBOX}`. A
**CONTRADICTS** is the only publishable "fail" and fires only when the author's own
oracle disagrees with the authentic bytes **clean, deterministic (N=3), and
env-clean** — anything uncertain is UNJUDGEABLE, never a fabricated pass or a
fabricated "broken". **`UNJUDGEABLE_NO_SANDBOX`** is the fail-closed refusal: execution
was not authorized (no `--allow-host-exec`, no container), so the skill was not run.

## What the captured runs show

See [`SELF_SPEC_RUN.md`](SELF_SPEC_RUN.md). In short: the gate does real work the
instant a checkable example exists (the fixtures: one tool reproduces its own
example, one contradicts it) — but across 18 installed ClawHub skills, **none ship a
machine-checkable spec at all** (no suites, no command+output examples, no fixtures).

That 18-skill run is a tiny local sample; [`sample_clawhub.py`](sample_clawhub.py)
generalizes it honestly across a **random sample of ~1,000 live ClawHub skills** and
finds **about 1 in 100 ship any checkable spec** (≈0.93%, 95% CI 0.49–1.76%; ~99%
ship none — see [`CLAWHUB_SAMPLE_RUN.md`](CLAWHUB_SAMPLE_RUN.md)). The missing layer
isn't "skills are broken"; it's that behavior is pinned nowhere — not by `verify`,
not by the authors' own docs.

## Honesty rails

Functional-conformance only; `verify` is correct at its job (provenance) — run
alongside it, never instead. Re-derives the author's OWN oracle, not "correct" (an
author's example can be incomplete). No LLM-judge; extracted goldens are byte-pinned
into the grader. **Execution is fail-closed:** the grader runs the skill's untrusted
code, so it refuses to run anything without an explicit `--allow-host-exec` vow (the
entrypoint lives outside any per-call mount, so the honest control is operator-level,
not per-call containment); `--sandbox docker:<image>` isolates the gate worker on top.
A wild CONTRADICTS is a responsible-disclosure lead (notify the author, offer the
fix), never a name-and-shame.
