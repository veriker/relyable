# Marketplace-scale: how often does a ClawHub skill ship ANY checkable spec?

Captured 2026-06-19, against the live ClawHub API (`clawhub.ai`), using the SAME
detector relyable uses everywhere else
(`relyable.skills.self_spec.detect_self_spec`). This is the marketplace-scale
companion to [`SELF_SPEC_RUN.md`](SELF_SPEC_RUN.md): that run grades skills you have
installed; this one asks, across a random sample of *live* skills, what fraction
ship a machine-checkable behavioral spec at all.

Reproduce: `python sample_clawhub.py 1000 --seed 20260619 --json`.

## The headline

```
CLAWHUB SAMPLE — ships a machine-checkable self-spec?  (frame=8939 slugs, N=1000, seed=20260619)
  gradeable skills (downloaded + has SKILL.md):  966
  ships ANY self-spec:  A = 9   (0.93%   95% CI 0.49–1.76%)
  ships nothing checkable:  99.07%
  by tier (of the A): {'S-A': 7, 'S-B': 2}
```

**About 1 in 100 live ClawHub skills ship anything that pins their behavior** — a
test suite (S-A), a documented command+output example (S-B), or example fixtures
(S-C). ~99% ship none. (A confirming N≈400 run the same day landed at 9/389 = 2.3%,
95% CI 1.2–4.3%; the point estimate wanders with such a rare event, but both runs sit
well under 2% and the CIs overlap.)

## How the sample is drawn (and the honest caveats)

- **No catalog-count endpoint exists.** ClawHub search requires a query term, is
  relevance-ranked, and returns only `results` — no total, no list-all. So the
  sampling **frame** is built as the union of single-character queries (`a`..`z`,
  `0`..`9`) → 8,939 distinct slugs. That is a *frame, not the catalog*: adding common
  words (`agent`, `data`, `ai`, `mcp`, …) pushes the union past 11,000 without
  plateauing, so the true catalog is larger and unknown. The reported rate is "of the
  sampled, gradeable skills."
- **`A` = SHIPS a detectable spec, not "passes" it.** Measuring whether the bytes
  actually reproduce the spec at scale means executing untrusted code; that is the
  separate, sandboxed `run_self_spec.py` pass, deliberately not run here. Detection
  is safe (no execution), which is what lets this sweep cover ~1,000 skills.
- **Not perfectly reproducible.** ClawHub content drifts and individual fetches
  occasionally fail (transient HTTP / timeouts → counted, never crash the sweep), so
  *which* skills land in the gradeable set — and therefore the exact S-A/S-B split and
  the specific spec-shippers named — vary run to run. The stable, citable result is
  the **rate and its CI**, not the membership list.
- **The 9 are real.** Spot-checked: the S-A hits ship genuine `tests/test_*.py`
  suites (e.g. `polymarket-combo-builder/tests/test_combo_builder.py`,
  `a-share-daily-report/tests/test_analyzer.py`), not detector false positives.

## What it establishes

The installed-skills run ([`SELF_SPEC_RUN.md`](SELF_SPEC_RUN.md)) found A=0 over 18
skills — a true but tiny, non-random local sample. This generalizes it honestly:
across a random ~1,000-skill draw, **behavior is pinned in roughly 1% of skills**.
The gap the self-spec axis fills — "there is no second party whose job is to
re-derive what a skill actually does" — is a marketplace-wide structural fact, not an
anecdote. Framed as gravity, not accusation: the skills aren't broken; behavior is
simply pinned nowhere, by anyone, until someone writes down one input→output pair.

## Honesty rails (carried from the self-spec line)

Functional-conformance only; ClawHub `verify` is correct at its job (provenance) —
this runs alongside it, never instead. `A` counts a *shipped* spec, never a "verified"
or "correct" one. No name-and-shame: a count is citable, a name is not.
