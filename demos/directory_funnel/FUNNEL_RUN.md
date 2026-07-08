# Directory funnel — captured runs over real ClawHub samples

`funnel.py` sizes, honestly, how much of a skills directory relyable's re-derivation
gate can actually adjudicate. Two captured runs below, both 2026-06-18, openclaw
2026.6.8: a **v1** over a curated 18-skill sample, and a **v2** (bundle-aware funnel)
over a fresh random 58-skill sample.

Reproduce v1: `bash collect_clawhub_sample.sh`. v2 sample = 60 slugs drawn (seed
20260618) from ~400 then-discovered via `openclaw skills search` across a handful of
diverse-domain queries, installed into a scratch home, funnel run over the result (59
installed, 58 with a parseable SKILL.md). ClawHub content drifts upstream.

> **Catalog-size correction (2026-06-19).** That "~400" is the *discovery pool that
> day from a few queries*, NOT the catalog size. ClawHub exposes no
> enumeration/count endpoint, but unioning single-character search queries
> (`a`..`z`, `0`..`9`) surfaces **≥8,939 distinct slugs** (and adding common terms
> pushes the union past 11,000 without plateauing) — so the catalog is at least an
> order of magnitude larger than "~400", true total unknown. The marketplace-scale
> "does a skill ship any checkable spec?" question is measured separately, on a
> random sample drawn from that ~9k frame, in
> [`../self_spec/sample_clawhub.py`](../self_spec/sample_clawhub.py) (≈1% ship one;
> see [`../self_spec/CLAWHUB_SAMPLE_RUN.md`](../self_spec/CLAWHUB_SAMPLE_RUN.md)).

## v2 — bundle-aware funnel, fresh 58-skill sample (the current number)

```
FUNNEL over 58 skills
SKILL-LEVEL:
  N = 58  skills with a SKILL.md
  E = 32  EXECUTABLE skills (≥1 entrypoint-shaped script): 22 single-entrypoint + 10 tool-bundle
      25  prose / instruction / external-CLI (out of scope by design)
TOOL-LEVEL (the unit the gate re-derives — one verdict per tool):
  T = 48  CANDIDATE tools, entrypoint-shaped (19 single + 29 bundle) — of 82 raw scripts
  K =  0  of the single tools auto-scaffold a trust root (T1); the rest need consumer goldens
  NB: entrypoint-shaped is NECESSARY, not sufficient — a network / GUI / side-effecting
      tool passes this check but still has no deterministic oracle.
```

Biggest bundles (entrypoint-shaped / raw scripts): crypto-investment-strategist 8/8,
session-password 4/7, terraform-ai-skills 4/5, html-editor 2/8, social-media-metrics
**1/18** (the other 17 are `platforms/*` modules, utils, and tests — not tools).

## v1 — pre-bundle funnel, curated 18-skill sample (baseline)

```
FUNNEL over 18 skills
  N = 18 ; M = 1 candidate (csv-analyzer) ; K = 0
  OUT OF SCOPE: [AMBIGUOUS_ENTRYPOINT] (2) clean-json-toolkit, json-linter
                [OUT_OF_SCOPE_PROSE_SKILL] (15) case-convert, convert-units, csv, …
```

This is the run that read as "≈5%, dead in the water." Note the two
`AMBIGUOUS_ENTRYPOINT` entries: clean-json-toolkit (7 tools) and json-linter were
**tool bundles the v1 funnel discarded** — counted as un-judgeable rather than as N
re-derivable tools.

## What actually changed, isolated honestly

Two independent things moved between v1 and v2 — keep them separate:

1. **The funnel is now bundle-aware.** On the *same* v2 sample, the old single-
   entrypoint classifier would have dumped all 11 multi-script skills as
   `AMBIGUOUS_ENTRYPOINT`; 10 are real tool bundles contributing **29 entrypoint-shaped
   tools**. So the classifier fix alone moves 10 skills / 29 tools from "out of scope"
   into "judgeable." This is the direct effect of the tool-bundle work.
2. **The sample is broader and less curated.** v1's 18 were prose-heavy (mostly one
   author's reference skills: json/sql/markdown/…). v2 is a random draw across the
   ~400 slugs discovered that day (a discovery pool, not the catalog — see the
   catalog-size correction above), so it carries more script-shipping skills
   independent of the
   classifier change. **Do not attribute the whole jump to the fix** — sample
   composition is a large part of it.

Net, on a representative sample: **executable skills are ~55% (32/58), not ~5%** — the
majority, not a rounding error — and the gate re-derives at the **tool** level (48
candidate tools here), not the skill level.

## The honest haircuts (these stack, and matter)

`T = 48` is a CANDIDATE ceiling, not a "48 skills verified" claim. Three deductions
sit between it and reality, and the project's capability-honesty rule forbids eliding
them:

- **raw 82 → entrypoint-shaped 48.** `enumerate_tools` returns every script (correct
  for packing — a stray bundle is fail-closed harmless), but ~34 of the 82 are library
  modules (`base.py`, `browser.py`, `resolver.py`), lifecycle scripts
  (`setup.js`/`uninstall.js`/`billing.js`), or tests — not invocable tools. The funnel
  now filters these for sizing; the packing path is unchanged.
- **entrypoint-shaped → deterministically re-derivable (a further, un-counted haircut).**
  Many of the 48 are network / GUI / side-effecting: `fetch_crypto_data.py`,
  `comfyui_run.py`, `download_weights.py`, the session-password lifecycle scripts. They
  have an entrypoint but **no clean oracle** to re-derive against held-out goldens. The
  cleanly-gradable count is below 48; pinning it needs per-tool I/O inspection.
- **K = 0.** Still zero tools auto-scaffold a trust root. Every candidate needs
  consumer-authored goldens. **Grader provisioning remains the binding constraint** —
  exactly the v1 finding, unchanged by the bundle work.

## Bottom line for the pitch (don't soften)

- "≈5%, dead in the water" was an artifact of **a prose-heavy curated sample × a
  classifier that threw away bundles**. Corrected, the executable surface is the
  majority of skills and tens of re-derivable tools per ~60-skill sample.
- "**Vet every skill in the marketplace**" is still **not** an honest claim: ~43% of
  this sample is genuinely prose with no oracle (out of scope by design — the gate
  refuses, it does not fabricate), and a chunk of the "executable" tools have no
  deterministic I/O contract.
- The real product limits are now clearly: **(a) grader provisioning** (where do the
  goldens come from — K=0), and **(b) deterministic-oracle availability** among
  executable tools. Skill *volume* and the single-entrypoint blind spot are no longer
  the story.

## Method / honesty notes

- Classification is `relyable.adapters._skillpack.detect_invocation` /
  `enumerate_tools` (the same scope gate the install gate uses) + a local
  entrypoint-shape heuristic (`__main__` / `argparse` / `sys.argv` for py; shebang /
  `$@` / `$1` for sh; `process.argv` / `require.main` / shebang for js), excluding
  `tests/` and `test_*`. Static + heuristic; entrypoint-shaped is **necessary, not
  sufficient** for judgeability.
- v2 surfaced a real robustness fix: a sampled `SKILL.md` carried non-UTF-8 bytes; the
  funnel now reads with `errors="replace"` (it must survey bad files, not crash).
- v1 earlier surfaced + fixed the inline-flow `metadata: {…}` parser crash (the
  `_metadata` helper + `test_inline_json_metadata_does_not_crash`).
