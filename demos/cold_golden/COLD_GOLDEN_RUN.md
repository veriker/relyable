# Cold-golden run — captured 2026-06-21

Model: `claude-sonnet-4-6` (cold constructor). Sample: the 18 real ClawHub skills
already installed at `~/.openclaw/skills` (+1 non-skill backup dir). Harness:
`cold_golden.py`. Raw: `COLD_GOLDEN_RUN.json`, `CONTROL_RUN.json`.

## 1. Control — does the mechanism have teeth? (`demos/self_spec/fixtures`)

Two crafted skills that pin behaviour with a documented I/O example. The cold
constructor builds **novel** inputs from the description and the code is run on them:

| skill | verdict | detail |
|---|---|---|
| `jsonpick-honest` | **PASS** | 3/3 cold goldens reproduced, mutation **kill=100%** (load-bearing) |
| `jsonpick-broken` | **DIVERGED** | cold goldens diverged from the code — caught the `repr()` regression that makes `.version` print `'1.2'` not `1.2` (review signal, not an accusation — see §3c) |

So: where the description determines output, a cold agent re-derives a golden that
**passes honest code and flags sabotaged code**, and the pass survives mutation. The
mechanism works.

## 2. Real ClawHub sample (18 skills) — what does it actually cover?

| verdict | n | which |
|---|---|---|
| `OUT_OF_SCOPE` | 16 | 15 prose-only skills (no executable oracle) + 1 backup dir (no `SKILL.md`) |
| `ABSTAIN` | 2 | `clean-json-toolkit`, `csv-analyzer` — executable, but the docs never pin exact output format |
| `PASS` | 1 | `json-linter` — 6/6 cold goldens reproduced, mutation **kill=33%** (load-bearing, partial) |
| `DIVERGED` | 0 | — |
| `PASS_VACUOUS` | 0 | (the vacuity guard fired before any vacuous pass could land — see §3) |

**Read the numbers honestly:**

- **The dominant wall is executability, not our cleverness.** 15 of 18 real skills are
  **prose instructions for the agent**, not code — there is no deterministic oracle to
  re-derive. This is the *same* wall `self_spec` hits; cold-construction does not move
  it. Cold-golden only ever applies to the executable slice (3 of 18 here).
- **Of the 3 executable skills, the cold agent honestly abstained on 2** because their
  docs describe *what* each tool computes but never pin the *exact bytes* (indentation,
  key order, decimal precision, column layout). That is the fail-closed discipline
  working, not a failure — a guessed expected value is a false accusation.
- **1 load-bearing PASS** (`json-linter`): its docs pin a JSON report with concrete
  fields (`total_files`, `invalid_files`, `errors[]`), so the cold agent re-derived
  substantive goldens (e.g. an invalid file ⇒ `"invalid_files": 1` and `broken.json`
  in `errors`). kill=33% says the goldens constrain real behaviour but cover only part
  of it — disclosed, not hidden.
- **Zero false greens.** No `PASS_VACUOUS` — and that took work (§3).

## 3. The integrity catch that mattered

On the first pass `json-linter` came back `PASS`, then `PASS_VACUOUS`. Its output
carries a `scanned_at` **timestamp** the constructor cannot predict, so it had reached
for `expected_stdout="" , match="contains"` — which is `'' in anything` ⇒ **always
true**. Two layers caught it:

1. the **mutation gate** flagged the pass as vacuous (kill=0%); then
2. a **structural guard** (`_vacuous_by_construction`) now drops empty-substring
   goldens *before* they count, turning the verdict into an honest `ABSTAIN`
   ("output not deterministically pinned"). On the final run the constructor instead
   built substantive substring goldens on the non-timestamp fields ⇒ a real,
   load-bearing PASS.

This is the whole thesis in miniature: the easy "coverage" was a lie, and the
discipline (fail-closed abstention + anti-vacuity) is what converts the mechanism from
a rubber stamp into graded coverage with honest holes.

## 3b. Second sample — 40 random skills from the full catalog

The §2 sample was a fixed, toolkit-weighted slug list. To avoid cherry-picking, a
second run drew **40 slugs at random (seed 7) from the 8,848-slug query-union frame**
(`fetch_sample.py`, fetched 2026-06-21; `COLD_GOLDEN_SAMPLE2.json`):

| verdict | n |
|---|---|
| `OUT_OF_SCOPE` (prose-only) | 18 |
| `ABSTAIN` | 22 |
| `PASS` / `DIVERGED` | 0 |

Zero load-bearing passes — and the **abstentions exposed a deeper ceiling than §2**.
There, executable skills merely failed to pin their output *format*. Here, ~half the
abstentions (11 of 22) are executable skills that **wrap a live external service** —
Alibaba Cloud RDS, Azure DevOps, OECD SDMX, Snyk, GitHub, the Grok/X API, AI-vision
endpoints — plus stochastic ones (`quantum-portfolio` simulated annealing), library-not-CLI
modules (`c-support`, `oecd-search`), and write-HTML-to-file tools. Their behaviour is
**exogenous to the code** (it lives on a remote server, behind a key, or in an LLM call),
so **no** re-derivation gate — author golden or cold golden — can pin it. The constructor
failed closed on every one, with an accurate reason each time.

The addressable surface for *any* functional re-derivation is therefore narrower than
"executable skills": it is "executable **and** deterministic **and** self-contained
(no network / credential / LLM dependency)." On a random 40, that intersection was ~0.

## 3c. The sharper cut — measure only the slice the gate CAN serve

§2/§3b mixed prose and live-service skills into the denominator. To size cold-golden on
its *addressable* surface, a Haiku screening pass (`classify_local.py`) routed a fresh
**194-skill random pool** (seed 11) into categories, and cold-golden ran on the
`LOCAL_DETERMINISTIC` slice only.

Pool classification (194 skills): **PROSE 104 · NETWORK 62 · STOCHASTIC 7 ·
LOCAL_DETERMINISTIC 21**. So the addressable surface — executable, local, deterministic,
self-contained — is **~11% of the catalog**; the other ~89% is prose or behaviour that
lives off-box (API / model / random), which no re-derivation gate can reach.

cold-golden over the 21 addressable skills:

| verdict | n |
|---|---|
| `ABSTAIN` | 18 |
| `DIVERGED` (unconfirmed) | 2 |
| `UNJUDGEABLE` (transient API 529) | 1 |
| `PASS` | **0** |

**Two findings, both load-bearing:**

1. **Even on local-deterministic CLIs, the constructor abstains 18/21 — and the reason
   is always the same: the docs describe behaviour qualitatively but never pin the exact
   output bytes.** "version could print `v2.0.0` or `Data Labeler v2.0.0`"; "status
   described high-level with no format"; stateful tools whose output depends on a log
   file + timestamps. This is the deepest finding of the whole exercise: the binding
   constraint is not prose, not networking — it is that **skill docs are not written to
   the byte.** A description-only reader cannot manufacture a golden the author never
   committed. *This is precisely the gap author goldens (self_spec) fill — the author
   knows the exact output; the cold reader can only guess.*

2. **Both apparent "contradictions" were FALSE POSITIVES — and that changed the design.**
   `axiom-url-canonicalizer` produced the *correct* canonical URL but wrapped it
   `Original:…\nCanonical:…`; `rename-session` emitted the *correct* error text on
   stderr with an `ERROR:` prefix and a formatted `--list` table. In every case the
   logic was right and the constructor had **guessed an output format the docs never
   pinned**. A cold-inferred golden is not the author's, so a divergence from it cannot
   be a publishable accusation — that violates relyable's own rail ("the only thing we
   ever call a contradiction is the author's own documented example"). The `FLAG` verdict
   was therefore **removed**: cold-golden now emits `DIVERGED` (a non-accusatory review
   signal), never an accusation. Its only trustworthy verdicts are `PASS`
   (mutation-load-bearing) and `ABSTAIN`/`OUT_OF_SCOPE`. **The sharper cut earned a
   safety fix the first two samples couldn't surface.**

## 4. What this means for the ClawHub conversation

Cold-golden is a real **Tier-1 on-ramp** under author goldens (Tier 0), not a
replacement:

- It **manufactures a check where the author shipped none** — but its grounding is
  description-conformance (consistency), weaker than an author golden, and its reach is
  bounded by three walls, each measured: (a) **prose** (≈54% of the catalog — no
  executable), (b) **off-box behaviour** (≈36% — live API / LLM / random; ~11% of the
  whole catalog is the addressable local-deterministic slice), and (c) **doc-determinism**
  (even inside that slice, 18/21 skills don't document output to the byte → abstain).
  Net load-bearing PASS rate: 1/18 curated, 0/40 random, 0/21 addressable.
- Its value at scale is **not the pass count** — it is that every `ABSTAIN` /
  `OUT_OF_SCOPE` is precisely the signal "this skill pins nothing checkable," which is
  the argument that drives authors to ship a Tier-0 golden. It maps the coverage gap
  instead of papering over it.
- **It must never accuse.** The addressable cut proved both observed divergences were
  correct-logic / unpinned-format false positives, so `DIVERGED` is a review signal, not
  a `CONTRADICTS`. A real contradiction needs the author's own documented example —
  `self_spec`'s job, not cold-golden's.

Bottom line for the registry ask — "prove results without re-running the evals":
a registry CAN auto-manufacture a behavioural check, but honestly it is a **thin** layer
— the addressable surface is ~11% of the catalog and most of that isn't documented
precisely enough to pin. The real product is the **map**: which skills are checkable,
and the precise reason each un-checkable one isn't (prose / off-box / not-pinned). That
map is the argument for getting authors to ship goldens — which is where the durable
coverage lives. Cold-golden is the on-ramp and the gap-finder, not the gate.

## 5. Engineering around the doc-determinism wall — metamorphic mode

Finding #1 (§3c) said exact-match abstains because docs aren't written to the byte. The
fix is to stop pinning bytes: a cold agent (`metamorphic.py`) proposes a METAMORPHIC
RELATION the docs *imply* — `invariance` (two equivalent inputs → identical output) or
`idempotence` (`f(f(x))==f(x)`) — checked **output-to-output**, so the format cancels.
This is the CLI/process-level analog of relyable's T2 PROVABLE_KINDS
(`property_grader.py`), with the same anti-vacuity mutation gate.

Re-running the 21 addressable skills in metamorphic mode:

| verdict | n |
|---|---|
| `HOLDS` (load-bearing) | **2** |
| `ABSTAIN` | 17 |
| `UNJUDGEABLE` | 2 |
| `DIVERGED` | 0 |

**It works — for one subclass.** Both `HOLDS` are canonicalizers
(`axiom-url-canonicalizer`: 6 load-bearing relations — host-lowercasing, param-sorting,
port-stripping, tracking-strip, idempotence; `axiom-json-canonicalizer`: idempotence
load-bearing). These are skills exact-match could only abstain on; metamorphic mode
*confirms* them, format-free, with mutation proving the relations constrain the code.
Positive coverage on the addressable slice went 0 → 2.

**But it's a subclass, not a general escape.** The other 17 abstained because they have
no doc-implied metamorphic relation: stateful CRUD tools, side-effecting setup scripts,
loggers, pass/fail validators. Metamorphic relations fit *normalizers/canonicalizers/
formatters* — real, but a slice of a slice (2 of 21 addressable, ~2 of 194 catalog).

**Two engineering lessons, both about NOT accusing.** Building this surfaced the same
trap twice: output-to-output comparison is defeated by run-specific noise the output
embeds. Every "violation" investigated was an artifact — the tool *echoing its input*
(`Original: <input>`), or embedding the *absolute cwd/tempdir path*, or a non-reproducible
proposer fluke — never a real defect. Two guards were added (mask each run's own input
strings; mask the cwd path), but the noise space is open-ended, so the violation verdict
was **downgraded to a non-accusatory `DIVERGED`**. Same rail as exact-match: cold
mechanisms *confirm* (`HOLDS`) and *map* (`ABSTAIN`); they never accuse.

**Honest ceiling.** A `HOLDS` verifies the structural invariants the docs imply, not
correctness — a *stably-wrong* canonicalizer still passes idempotence (the low kill-rates,
0.08–0.18, confirm each relation is a narrow check). So metamorphic mode converts part of
the doc-determinism wall into real, certifiable, format-free coverage — for the
normalizer/canonicalizer subclass — but it neither reaches the stateful majority nor
substitutes for an author golden's correctness grounding.

## 6. Lever A — format-tolerant predicates in exact-match (re-run 2026-06-21)

§3c diagnosed *why* exact-match abstains: docs pin a **value** (a canonical URL, a version
string, a JSON field) but never its **wrapper** (the `Original:`/`Canonical:` labels, the
line order). Pinning bytes false-accuses; abstaining drops the case. Lever A adds a
structured-predicate vocabulary to the exact-match constructor so it can pin the value
without the wrapper: `last-token-equals`, `json-field-equals` (dotted path),
`regex-capture-equals` (one capture group). Same fail-closed posture — each new mode has a
structural vacuity guard (empty expected, empty path, an anything-matching `(.*)` group are
dropped) on top of the mutation gate.

Re-running the 21 addressable skills in exact-match with predicates:

| verdict | before (exact-only) | after (Lever A) |
|---|---|---|
| `PASS` (load-bearing) | **0** | **1** |
| `ABSTAIN` | 18 | 16 |
| `UNJUDGEABLE` | 1 | 4 |
| `DIVERGED` | 2 | 0 |

The single `PASS` is `axiom-url-canonicalizer` (5/5 cold goldens reproduced, mutation
**kill=27%** — load-bearing, not vacuous). This is exactly the case exact-match used to
**falsely DIVERGE** on: the constructor predicts the canonical value correctly from the docs
(`https://example.com/?a=1&b=2` for a sorted/lowercased input), but the tool prints it as
`Original: <input>` / `Canonical: <value>`. A bare-value `exact` match diverged on the
label; `last-token-equals` isolates the canonical value and the match holds. **Net: the
predicate vocabulary turned a format false-positive into a real, mutation-backed PASS.**

**The constructor needed a concrete tell, not just permission.** The first re-run still chose
bare-value `exact` and produced the false DIVERGED — the predicates existed but weren't
selected. The fix was an operational instruction (most CLIs label/echo output, so a
predicted single value is almost never printed bare → don't use `exact` on it). That is a
general CLI pattern, not skill-specific.

**Same narrow-subclass story as §5, same honest ceiling.** Predicates recover the
*value-in-a-wrapper* subclass; the other 16 skills still abstain because their stdout is
genuinely undocumented — side-effecting setup scripts, stateful CRUD, loggers, validators
with no pinned output. (The `UNJUDGEABLE` rise is the constructor reaching for more goldens
that then error on invocation — noise, not false greens.) And a predicate `PASS` is still
DESCRIPTION-CONFORMANCE, not correctness: it certifies the code prints the value the docs
describe, in a format the docs left open — never that the value is right about the world.

## 7. `round_trip` — the third metamorphic relation (added 2026-06-21)

Metamorphic mode (§5) shipped two relation kinds (`invariance`, `idempotence`). Tier 5
adds the third PROVABLE_KIND from relyable's T2 vocabulary: `round_trip` — a FORWARD tool
followed by its INVERSE returns the original input, `inverse(forward(x)) == x`
(encode/decode, serialize/parse, flatten/unflatten). The proposer must name both the
forward and inverse tool and quote the doc basis for reversibility; the checker runs the
forward, feeds its output to the inverse, and compares the result to the original payload —
**semantic JSON-equality when both parse** (a reversible JSON tool may re-serialize with
different key order / whitespace and still be lossless), byte-equality otherwise. The
anti-vacuity gate mutates **both** legs (forward and inverse source); a relation that
survives mutation of either is not load-bearing.

**It fires, load-bearing, on the canonical demonstrator.** None of the 21 addressable-slice
skills ship an inverse pair (every proposer correctly abstained on round_trip there, citing
"no reversible/round-trip pair documented"). The relation's real target lives in the
installed `clean-*` family: `clean-json-toolkit`'s `flatten.py`, documented "Reversible with
`--unflatten`. Roundtrip-safe." Running it:

| skill | relation | verdict | kill-rate |
|---|---|---|---|
| `clean-json-toolkit` | `round_trip` (`flatten.py` ⇄ `flatten.py --unflatten`) | **HOLDS** | 0.22 |

A fresh nested JSON flattened to dot-notation and unflattened back recovers the original
(semantic-equal), and mutating `flatten.py` breaks the round-trip in 22% of applicable
mutations — so the relation genuinely constrains the code. This is the same forward/inverse
demonstrator the production prove gate (`relyable/skills/property_grader.py`) certifies at
the Python-function level, here proven black-box at the CLI level (Tier 6 is the open
decision on whether to unify the two surfaces).

**A file-IO channel had to be added.** `flatten.py` is file-in/file-out
(`flatten.py in.json out.json [--unflatten]`), not stdout — so `run_golden`/`run_capture`
gained an optional `capture_file` to read a tool's named output file from the run tempdir
(additive; stdout tools are unchanged). round_trip threads it for both the forward output
and the inverse output.

**Slice re-run, same accusation discipline.** The addressable slice in metamorphic mode now
reads HOLDS 1 / DIVERGED 1 / ABSTAIN 18 / UNJUDGEABLE 1. `axiom-url-canonicalizer` still
HOLDS (4 load-bearing relations). The single `DIVERGED` (`axiom-json-canonicalizer`, a
proposer-noise flip from §5's HOLDS) was **hand-verified before trusting**: run directly,
the canonicalizer produces byte-identical output for two inputs differing in whitespace AND
key order — the "violation" was a proposer feeding one variant on a channel the tool does
not read (empty output), not a defect. Downgraded to non-accusatory `DIVERGED` as designed.
Every cold divergence this project has produced, across all three modes, has been an
artifact; none has been shipped as an accusation.

## 8. Tier 6 decision — keep the CLI and function prove surfaces parallel (2026-06-21)

This demo and the production prove gate (`relyable/skills/property_grader.py` +
`anti_vacuity.py`) share a vocabulary (`round_trip` / `idempotence` / `schema_conformance`)
and a doctrine ("kills-mutants ≠ correct-spec, but survives-all-mutants == vacuous"), so
the natural question is whether to unify them behind one engine. **Decision: keep them as
parallel surfaces** (Max, 2026-06-21). They answer different questions and the impedance is
load-bearing, not incidental:

* **This demo is black-box.** It models the ClawHub reality — you have the skill's *docs*
  and its *binary*, and you never import its code. It runs the tool as a subprocess and
  compares outputs. Manufacturing coverage *without trusting or importing the skill code*
  is the whole point.
* **The production gate is white-box.** `property_grader` imports the skill's Python
  function and calls `f(x)`; `anti_vacuity` drives mutmut over that source in-process.

Building a CLI→callable adapter so the CLI relations flow through the real mutmut gate would
**re-import / exec the skill code inside the prove process** — reintroducing exactly the
execution-trust problem the black-box demo exists to avoid, and blurring its distinct claim.
If the two surfaces are ever unified it should be through a **shared reporting/verdict
schema**, not a shared mutation engine — a reporting bridge, deferred until there is a
consumer that needs both verdicts in one place. No `relyable/skills/` change is made here.

## 9. Converter-family slice — the wall is upstream of "no spec" (run 2026-06-21)

Every prior slice (§2–§5) was a **random** catalog pull, so the addressable subclass our
mechanisms serve (normalizers / formatters / converters / encode-decode pairs) was always a
thin minority drowned in stateful junk. This slice tests the opposite: run metamorphic mode
over a deliberately **converter-curated** set — the 18 skills installed in
`~/.openclaw/skills` (`json-formatter`, `case-convert`, `convert-units`,
`data-format-converter`, `markdown-converter`, `csv`/`sql` toolkits, `clean-json-toolkit`,
`json-linter`, …). Hypothesis: this is where `invariance` / `idempotence` / `round_trip`
should fire hardest.

The result **inverted the hypothesis, usefully**:

| verdict | n | of 18 |
|---|---|---|
| `HOLDS` (load-bearing) | 1 | `clean-json-toolkit` (round_trip) |
| `ABSTAIN` | 2 | `csv-analyzer`, `json-linter` |
| `OUT_OF_SCOPE` (prose skill, no executable) | 15 | the rest |

**Only 3 of 18 converter-NAMED skills ship any runnable code at all.** `json-formatter`,
`data-format-converter`, `convert-units`, `case-convert`, `markdown-converter`,
`sql-toolkit` … contain only `SKILL.md` + metadata — zero scripts (verified by recursive
file listing, not just the harness verdict). They are **prose instructions to the LLM**, or
thin wrappers around external binaries (`markitdown`, `sqlite3`, `psql`) they assume are
installed. There is nothing bundled to re-derive against.

> **Scope caveat (added after §10).** This is a real property of *this curated set of 18
> official converter-named skills* — it does **not** generalize to the marketplace. The
> powered random measurement in §10 finds ~47% of skills ship functional code. Treat the
> "3/18" here as an anecdote about official-converter skills (which happen to be LLM-prose
> wrappers), not a population rate. §10 is the load-bearing number.

This relocates the wall. The earlier finding was "~1% of skills ship a checkable spec";
this sharpens it to a prior gate — **does the skill ship deterministic code at all?** On a
converter-named sample, only ~17% (3/18) do. Code-level re-derivation — ours or anyone's —
fundamentally needs an artifact to run; a prose/agentic skill's "behavior" is whatever the
LLM does with the instructions, which is exactly the non-deterministic surface no
re-derivation mechanism can pin. `OUT_OF_SCOPE` is the honest verdict, not a harness gap: it
marks the boundary of what the re-derivation axis can address. The prose majority needs a
*different* trust mechanism (behavioral evaluation), not re-derivation.

Category-conditional, among the 3 code-bearing skills: 1 earned a load-bearing confirm
(`clean-json-toolkit`), and 2 honestly abstained (`csv-analyzer` is analysis with no implied
relation; `json-linter` emits a timestamped, filesystem-stateful report). So even after you
filter to the right *name*, the funnel is two-staged — ships-code, then implies-a-relation —
and the honest manufacturable-confirm rate stays small.

## 10. Powered code-presence — ~half the marketplace ships code (n=242, 2026-06-21)

§9 floated a generalization — "a marketplace whose bulk is prose" — off a curated n=18.
That deserved a powered test, and the test **walks the generalization back.** A fresh
seed-pinned random pull (`fetch_sample.py … 250 --seed 20260621`, 242 usable after fetch
failures; sampling frame = 8,850 distinct slugs from the query-union) was scored by
`code_presence.py` — a **purely mechanical** classifier, no LLM, no API spend:

| gate | k/n | rate | 95% Wilson CI |
|---|---|---|---|
| ships ≥1 functional script (.py/.sh/.js/.mjs) | 115/242 | **47.5%** | 41.3% – 53.8% |
| harness resolves a runnable entrypoint | 115/242 | 47.5% | 41.3% – 53.8% |

Two robustness checks held: the two gates land on the **exact same 115 skills** (no skill
ships code the harness fails to see, and none declares a tool it doesn't ship), and **zero**
of the 115 ship *only* boilerplate (`install.sh`/`check_deps.sh`) — every one has a real
functional script. So 47.5% is honest functional-code presence, not an installer artifact.

**The correction:** roughly **half** of random ClawHub skills ship runnable code — the
marketplace is *not* mostly prose. The §9 "3/18" was a property of that specific set of
official converter-named skills (which happen to delegate to the LLM or to external bins),
not the population. The wall §9 named is real but sits much lower than 17%: about **half**
the catalog clears the first (code-presence) gate.

**What this does and does not say.** Code-presence is the **outer** gate — necessary, not
sufficient, for re-derivation. The cold mechanisms still need the code to be *deterministic
and local* (not network/stochastic) and to carry a *checkable contract* (a pinnable value or
a doc-implied relation). Those inner gates are where the yield thins — on the random
addressable-21 (§3c/§5/§6) the manufacturable-confirm count was ~1–3 of 21. So the funnel,
with the now-powered outer gate, reads:

  ships functional code ~47% (95% CI 41–54%)  ⊋  deterministic + local + checkable contract
  (a minority of those)  ⊋  cold-manufacturable confirm (smaller still)  ⊋  author's own
  committed spec ~1% (self_spec).

The on-ramp framing survives and is *stronger* for being correctly sized: re-derivation is
the high-assurance gate for the **code-bearing ~half** of the marketplace — a far larger
addressable surface than §9 implied — narrowing to a smaller confirmable core, with the
prose ~half needing behavioral evaluation instead. Mechanical artifact:
`CODE_PRESENCE_POWERED.json`.

## 11. Powered inner yield — attempting the code-bearing ~half (n=242, 2026-06-21)

§10 sized the *outer* gate; this measures the *inner* one. Both cold modes were run over the
same powered sample (the 127 prose skills short-circuit to `OUT_OF_SCOPE` with **no** API
call, so the spend lands only on the 115 code-bearing skills): metamorphic
(`METAMORPHIC_POWERED.json`) and exact-match Lever A (`COLD_GOLDEN_POWERED.json`).

| mode | load-bearing confirm | vacuous (caught) | DIVERGED | ABSTAIN | UNJUDGEABLE |
|---|---|---|---|---|---|
| metamorphic | **2** HOLDS | 1 HOLDS_VACUOUS | 3 | 107 | 2 |
| exact-match (Lever A) | **0** PASS | 1 PASS_VACUOUS | 2 | 110 | 2 |

**Combined funnel, all gates now powered:**

```
random ClawHub skill                       n = 242
  ships functional code        115/242 = 47.5%   (95% CI 41.3–53.8%)   [outer, §10]
    cold-confirmable             2/115 =  1.7%   (95% CI  0.5– 6.1%)   [inner, this run]
  = of ALL sampled              2/242 =  0.8%   (95% CI  0.2– 3.0%)
```

The two confirmed skills are both genuine, hand-checked normalization relations:
`kai-business-blueprint` (a `normalize.py` idempotence, kill=0.167) and `ppt-generator-skill`
(a hex-color sanitization invariance — `#`-prefix stripped, kill=0.091). No exact-match PASS
survived the anti-vacuity gate.

**Why the inner gate is so tight — and it is the honest answer, not a harness limit.** Of
the 115 code-bearing skills, the large majority `ABSTAIN` because they are **network / live-
data** (ticket search, web search, news fetch, business-intelligence queries against live
inventory) or **stochastic / stateful** (AI-insight note-takers, timestamped loggers,
LLM-content generators). None of those carries a deterministic contract a cold reader can
re-derive, and every proposer said so explicitly. The cold mechanism's value here is as much
the honest `ABSTAIN`/`OUT_OF_SCOPE` map as the 2 confirms: it tells you precisely which
skills are even checkable.

**Zero accusations, gate worked.** Five `DIVERGED` events fired across both modes; every one
was hand-verified to be an artifact, none a defect: `daily-ai-news` (live-API non-determinism
— `error 1102` vs a server message), `jd-link-converter` (empty `original` field — the URL
never reached the channel the tool reads), `axiom-luhn-check` ×2 (the Luhn logic is correctly
space/dash-invariant — run directly, `valid`/`luhn_ok`/`digits` are identical; only the
echoed `original` field differs), `moving-checklist` (constructor guessed `--json` output;
the tool prints a text checklist). And the anti-vacuity gate caught the one hollow green
(`trtc-ai-customer-service`: a scaffolder's `✅ …已生成到: <dir>` success echo that prints
regardless of logic, kill=0% → `PASS_VACUOUS`, not counted).

**Bottom line.** Cold, zero-author-input re-derivation confirms a **small, high-assurance
core (~1.7% of code-bearing skills, ~0.8% of all skills)** with no false accusations. This
powered number corroborates the earlier qualitative read ("the re-derivation surface is
small; grader-provisioning is the constraint"): the auto-confirm layer is thin by nature, so
the product is *map + thin confirm + on-ramp to author-declared specs* (`self_spec`, the ~1%
who ship a committed oracle and the path to grow it) — never an auto-flagger. The 47%
code-bearing surface is the **addressable** market for that on-ramp; the ~1.7% is what
falls out for free today with nothing but the docs.

## 12. The prose half — can we verify it too? (mechanical sizing, n=127, 2026-06-21)

The natural follow-up: the prose skills (§10's no-bundled-code ~half) still *claim* a
behavior — couldn't we extract that claim as a spec, **execute the skill**, and verify? Yes,
but "execute" means different things, and reading prose skills by hand surfaced three
execution models with very different verifiability:

* **delegates to a local deterministic bin** — the SKILL.md's documented path is a real CLI
  (`uvx markitdown input.pdf`, `pandoc`, `jq`). **Fully recoverable** by cold-golden with an
  external-command entrypoint: the bin is a fixed artifact, the check is deterministic, not
  circular. (`markdown-converter` is the clean example — but it lives in the curated/installed
  set, not the random sample.)
* **LLM-executed** — no command at all; the prose *is* the program and the agent runs it
  (`case-convert` spells out the casing algorithm in English). "Executing" = running an LLM,
  so only a **behavioral eval** applies: instruction-determinism, **partly circular** (the
  spec-writer and the executor are the same class of system), non-deterministic, model-
  dependent. A genuine quality signal, but a weaker and different claim than artifact
  re-derivation — the *behavior axis*, not re-derivation.
* **network API** — the documented execution calls a remote service (`curl https://…`) or
  fetches/installs (`npm i`, `clawhub install`). Out of scope for offline re-derivation.

`classify_prose.py` sizes these mechanically (no LLM) over the powered sample's 127 prose
skills, judging each shell command by its **program** (first token, past env-assignments and
`uvx`-style wrappers), folding `\`-continuations:

| execution model | k/127 | rate | 95% Wilson CI |
|---|---|---|---|
| **delegates to local deterministic bin** | **0** | **0.0%** | 0.0% – 2.9% |
| network API / fetch-install | 35 | 27.6% | 20.5% – 35.9% |
| other command (manual-checked: none recoverable) | 14 | 11.0% | 6.7% – 17.7% |
| LLM-executed (no command block) | 78 | 61.4% | 52.7% – 69.4% |

> **Self-correction.** A first mechanical cut reported 38.6% "delegates to a bin" — and it
> was **wrong**, an artifact of two classifier bugs: multi-line `curl … \ -H … \ -d …` got
> split so the flag-continuation lines (no `curl`/`http` on them) counted as non-network
> commands, and a bin name matched *anywhere* in a line (an incidental `grep`/`node` in an
> example). Folding continuations and judging the command's first-token program collapsed it
> to 0%. The same "verify before trusting a positive" rule the cold mechanisms apply to skills
> caught it here applied to my own tool. The 14 `OTHER_COMMAND` were then hand-checked — all
> remote DBs (`mysql -h <host>`), LLM-driven editors (`nano-pdf … "fix the typo"`), hardware
> monitors, `cp`/`mkdir`, TTS, or niche unknown CLIs — **none** a clean deterministic local
> converter.

**The answer to "can we verify the prose half too":** in principle yes, but the *strong*
(deterministic, non-circular) path — delegate-to-local-bin — is **<3% of prose skills** at
95% confidence, essentially absent in the random catalog despite existing as a clean pattern
(`markdown-converter`). The prose majority is **LLM-executed (~61%)**, reachable only by a
**behavioral eval** with real honesty caveats (fixed executor model, multi-sample pass-rate,
report "instruction-determinism" not "correctness", never let the spec-writer self-judge —
the self-verification trap), plus **~28% network** that is simply out of scope. So extending
re-derivation into the prose half buys almost nothing; covering it means a *separate
behavior-axis product*, deliberately built and labelled as such — not a quiet extension of
the golden check. (Hypothesis, not measured: delegate-to-local-bin likely clusters in the
popular/official tier — `markdown-converter`, `pandoc-convert` both sat in the installed set
— so a popularity-weighted frame might show a few percent rather than ~0. The long tail does
not.) Mechanical artifact: `PROSE_EXECUTION_MODEL.json`.
