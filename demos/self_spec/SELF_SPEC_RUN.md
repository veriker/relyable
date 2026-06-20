# Self-spec re-derivation — every skill graded against ITS OWN committed spec

Captured 2026-06-18, openclaw 2026.6.8 + veriker 0.1.2. The orthogonal axis to
ClawHub `verify`: `verify` confirms the bytes are the real author's (provenance — and
it does that correctly); this asks whether those authentic bytes still reproduce
**the author's own** committed spec — their shipped test suite (S-A), documented
input/output examples (S-B), or example fixtures (S-C). **No goldens authored by us.**
The only thing ever called a contradiction is the author's own test/example, run
deterministically (N=3) and env-clean, disagreeing with the author's own code.

## A. Mechanism — fires on skills that DO ship a checkable example

`run_self_spec.py demos/self_spec/fixtures` — two tiny skills that each ship a
prompt-anchored usage example (a command **and** its output). One tool reproduces
its own example; the other carries a regression that contradicts it.

```
SELF-SPEC over 2 skills (each graded against the author's OWN spec)
  ships a machine-checkable self-spec:  A = 2
     S-B  2
     goldens extracted (S-B/S-C):  4  (skipped fail-closed: 0)
  verdicts:
     REPRODUCES   R = 1   (author's bytes reproduce author's spec)
     CONTRADICTS  C = 1   (disclose privately; never name here)
     UNJUDGEABLE  0
```

`jsonpick-broken` ships the example `… | pick.py .version` → `1.2`, but its tool
`repr()`s the value, so it prints `'1.2'`. The gate re-derives the author's own
documented example and the bytes disagree → **CONTRADICTS**. This is the
responsible-disclosure-class finding (the author's own example, not a spec we
invented) — and it is reproduced through the real veriker gate with the extracted
golden byte-pinned into the grader, exactly like a consumer-graded skill.

## B. Real-world — 18 real ClawHub skills

`run_self_spec.py ~/.openclaw/skills` over the 18 installed ClawHub skills
(case-convert, clean-json-toolkit, convert-units, csv, csv-analyzer,
data-format-converter, expanso-csv-to-json, image, json, json-formatter, json-linter,
markdown, markdown-converter, markdown-table-generator, pandoc-convert-openclaw,
scrape, sql, sql-toolkit):

```
SELF-SPEC over 18 skills (each graded against the author's OWN spec)
  ships a machine-checkable self-spec:  A = 0
     goldens extracted (S-B/S-C):  0  (skipped fail-closed: 2)
  verdicts:
     REPRODUCES   R = 0
     CONTRADICTS  C = 0
     UNJUDGEABLE  18
        UNJUDGEABLE_NO_SPEC: 18
```

## What this establishes (the honest, victim-free finding)

**Not one of the 18 ships a machine-checkable behavioral spec.** Verified directly:

- **0 ship a test suite** (S-A): no `tests/` dir, no `pytest.ini`/`pyproject`/`tox.ini`
  pytest layout in any of the 18.
- **0 ship a documented input→output example** (S-B): the fenced blocks that exist
  document **invocation syntax**, never the output. clean-json-toolkit's "Quick start"
  lists `python3 scripts/query.py data.json '.meta'` with no result shown; csv-analyzer
  uses `{baseDir}` placeholders; sql-toolkit's blocks are raw `sqlite3` CLI usage, not
  the skill's own tool. None pair a command with its expected output. (`prompt_lines=0`
  across all 18 — and the no-prompt blocks have no outputs either, so even a looser
  parser extracts nothing real.)
- **0 ship paired example fixtures** (S-C).

So the gap is **structural and nobody's fault**: there is nowhere — not ClawHub
`verify`, not the authors' own docs — that a skill's behavior is pinned to something
checkable. This is the K=0 finding from the directory funnel deepened: it isn't only
that *consumers* must author goldens; the *authors don't ship a checkable spec either*.
That absence — not "skills are broken" — is the missing layer relyable's
re-derivation axis fills, the moment anyone (author OR consumer) writes down a single
input→output pair.

The mechanism demo (§A) shows the gate does real work the instant a checkable example
exists; the real-world run (§B) shows how rarely one does today.

## Honesty rails (carried verbatim)

- Re-derives the author's OWN oracle — **not** "correct". An author's example can be
  incomplete or itself wrong (the `kills-mutants != correct-spec` caveat).
- Functional-conformance only; ClawHub `verify` is **correct at its job** (provenance).
  Run alongside `verify` / ClawScan, never instead.
- Refusal is integrity: no spec / non-deterministic / env-fail / unparseable →
  **UNJUDGEABLE**, never a fabricated pass and never a fabricated "broken". A
  CONTRADICTS only fires clean+deterministic+env-clean, from authentic bytes.
- No LLM-judge. Extracted goldens are byte-pinned into the grader (SpecAnchor):
  authority on the trusted side, never selected by the producer.

## Method / reproduce

```bash
python demos/self_spec/run_self_spec.py demos/self_spec/fixtures   # §A mechanism
python demos/self_spec/run_self_spec.py ~/.openclaw/skills         # §B real ClawHub
```

- Detection: `relyable.skills.self_spec.detect_self_spec` (S-A via
  `scaffold.detect_rung` T1; S-B `_extract_doc_examples`; S-C `_pair_fixture_files`).
- Grading: `grade_self_spec` — per tool a determinism (N=3) + env preflight, then a
  gate-routed re-derivation through `relyable.skills.gate.rederive` with the extracted
  goldens byte-pinned into a generated stdlib-only grader.
- The S-B parser is deliberately conservative (prompt-anchored `$`/`>` sessions only,
  materializable inputs only, stdout-only, no truncation) — it under-extracts on
  purpose, because a missed example costs a number while a mis-extracted one costs a
  false accusation. `skipped` logs every cell it declined and why.

## Responsible disclosure (only if a real CONTRADICTS appears in the wild)

A wild CONTRADICTS = the author's own test/example disagreeing with their own bytes.
Minimal repro = authentic bytes + the author's own failing example. Notify the author
privately, offer the goldens/fix, wait. A count may be cited publicly; a name only
with consent. This pass is a good-citizen contribution, never a name-and-shame.
