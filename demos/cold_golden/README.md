# cold_golden — manufacture a re-derivation check for a skill that ships no spec

`self_spec` re-runs the **author's own** committed oracle (shipped tests / documented
I/O). It is the strongest grounding relyable has, but it is rare: ~1% of live ClawHub
skills ship any checkable spec (see `../self_spec`).
This demo asks the question for the other ~99%:

> Can a cold agent that reads only a skill's **description** manufacture *some*
> re-derivation coverage — without the author providing a golden?

## The mechanism

1. **Construct (cold, direct API).** A fresh-context model reads ONLY the skill's
   `SKILL.md` (the human-facing docs) plus the tool filenames — **never the source**.
   It emits novel `(input → expected_stdout)` goldens, or **abstains**. Direct API
   with a neutral system prompt, never the local CLI/Agent tool, so no CLAUDE.md
   policy contaminates the cold context (the experiment-harness direct-API rule).
2. **Run.** The skill's actual code is executed on those inputs (`_skillpack`
   entrypoint enumeration + runner).
3. **Compare (mechanical).** Byte/JSON compare — **no LLM judge**. The golden is
   byte-pinned *before* the code runs, so this is re-derivation, not self-verification
   (relyable's re-derivation experiments: re-derivation recovers where self-verify recovers 0.00).

## What a PASS means — and does not

A PASS certifies **description-conformance** (the code does what its docs say), **not
correctness**. The anchor is the author's own description; if docs and code agree but
are both wrong about the world, this passes green. That is the consistency-vs-spec
axis (consistency, not truth) — *weaker* grounding than an author golden, named as
such, never sold as truth. Its value is independence on the **implementation** axis:
the golden is built blind to the code, so it cannot inherit the code's bugs.

## The two disciplines that keep it from being theatre

- **Abstention is fail-closed.** "This description does not pin behaviour" is a
  reported HOLE, never a pass.
- **Anti-vacuity.** Two layers: (a) goldens that are always-true *by construction*
  (empty-expected + substring match — the constructor's cop-out for non-deterministic
  output like a timestamp) are dropped structurally; (b) every surviving PASS is
  **mutation-tested** — a golden set that survives every mutation of the code proved
  nothing and is reported `PASS_VACUOUS`. (CLI-level sibling of the `prove`/mutmut
  gate that backs relyable's `prove` ladder.)

## Verdict taxonomy

| verdict | meaning |
|---|---|
| `OUT_OF_SCOPE` | no executable entrypoint (prose-only skill) — nothing to re-derive |
| `ABSTAIN` | constructor could not pin behaviour from the description (fail-closed) |
| `UNJUDGEABLE` | constructed goldens but the tool errored / was non-deterministic |
| `DIVERGED` | tool output differed from a cold golden — **UNCONFIRMED, never an accusation**: the expected bytes were inferred from prose, not author-pinned, so a divergence is as likely a format guess as a defect. A real CONTRADICTS needs the author's own documented example (`self_spec`). |
| `PASS` | tool reproduced every cold golden, and the goldens killed ≥1 mutant |
| `PASS_VACUOUS` | reproduced, but the goldens survived every mutation (not load-bearing) |

## Run it

```bash
# Controlled positive/negative pair (proves the mechanism has teeth):
python demos/cold_golden/cold_golden.py demos/self_spec/fixtures
#   jsonpick-honest -> PASS  (kill=100%)
#   jsonpick-broken -> DIVERGED (cold goldens catch the repr() regression — review, not accuse)

# Real ClawHub sample you already have installed:
python demos/cold_golden/cold_golden.py ~/.openclaw/skills --out COLD_GOLDEN_RUN.json

# Fresh random sample straight from the ClawHub archive API (no openclaw install):
python demos/cold_golden/fetch_sample.py /tmp/sample 40 --seed 7
python demos/cold_golden/cold_golden.py /tmp/sample --out COLD_GOLDEN_SAMPLE2.json

# The addressable cut: screen to local-deterministic skills, then grade that slice:
python demos/cold_golden/classify_local.py /tmp/sample --link /tmp/addressable
python demos/cold_golden/cold_golden.py /tmp/addressable          # exact-match mode

# Metamorphic mode — engineer around the doc-determinism wall (format-proof checks):
python demos/cold_golden/metamorphic.py /tmp/addressable --out METAMORPHIC_ADDRESSABLE.json
#   axiom-url-canonicalizer -> HOLDS (6 load-bearing invariance/idempotence relations)
```

## Two modes

- **Exact-match (`cold_golden.py`)** — predicts exact output bytes. Strongest when the
  docs pin output; abstains (a lot) when they don't. Verdicts: `PASS` (mutation-load-
  bearing) / `ABSTAIN` / `DIVERGED` (review) / `OUT_OF_SCOPE`.
- **Metamorphic (`metamorphic.py`)** — engineers around the doc-determinism wall: checks
  a doc-implied *relation* between the tool's own outputs (`invariance`, `idempotence`)
  output-to-output, so format cancels. Recovers the normalizer/canonicalizer subclass
  exact-match can only abstain on. Verdicts: `HOLDS` (the win) / `ABSTAIN` / `DIVERGED`
  (review, never an accusation — output noise defeats violation detection) / `HOLDS_VACUOUS`.

Captured runs: `CONTROL_RUN.json`, `COLD_GOLDEN_RUN.json`, and the narrative in
`COLD_GOLDEN_RUN.md`. Requires `ANTHROPIC_API_KEY` in `.env/MASTER.env` and the
`anthropic` SDK; the constructor is an LLM, so runs are reproducible-*ish* (pin the
model; expect small run-to-run variation in which cases it constructs).
