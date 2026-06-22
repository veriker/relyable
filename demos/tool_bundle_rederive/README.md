# Tool-bundle re-derivation — N bundled tools, one verdict each

The [directory funnel](../directory_funnel/) found that real ClawHub **tool bundles**
— one `SKILL.md` routing to several bundled `scripts/*.py`, each a small CLI — were
false-rejected by the install gate as `AMBIGUOUS_ENTRYPOINT`, because the scope gate
modeled exactly **one** entrypoint. This demo runs the N-tool generalization end to
end on the real [`clean-json-toolkit`](https://clawhub.ai/gopendrasharma89-tech/clean-json-toolkit)
(7 tools: `inspect`/`query`/`flatten`/`validate`/`merge`/`patch` + `check_deps.sh`).

It **enumerates** the bundle's tools, packs **one re-derivable veriker bundle per
tool** (each carrying the whole skill tree, so the shared `_common.py` the tools
import travels with every one), and re-derives each against a **consumer** grader
([`json_toolkit_grader.py`](../../relyable/skills/examples/json_toolkit_grader.py))
that ships held-out goldens for two of them (`query`, `flatten`).

## Run it

```bash
# In-process (pack per tool -> admit_directory -> install-policy decision):
python rederive_bundle.py                       # honest clean-json-toolkit
python rederive_bundle.py --break query         # sabotage one tool -> REJECT / BLOCK
python rederive_bundle.py --json

# Live, through a REAL `openclaw skills install` (openclaw 2026.6.8):
bash run_live.sh
```

If the skill is absent: `cd /tmp/oclive && npx openclaw skills install
clean-json-toolkit --global --force`.

## What it shows — "K of N tools re-derive"

| tool class | verdict | why |
|---|---|---|
| consumer-graded + reproduces goldens (`query`, `flatten`) | **ADMIT** | the tool does what the consumer's spec needs, un-fakeably |
| consumer has no goldens (`inspect`/`validate`/`merge`/`patch`/`check_deps`) | **UNJUDGEABLE** | the grader fails closed (`no_goldens_for_kind`) — never a fabricated pass |
| graded tool that runs but **contradicts** the goldens (`--break query`) | **REJECT** | a genuine re-derivation mismatch |

The honest report is **"2 of 7 tools re-derive"** — *not* "the skill is verified". The
gate speaks only to the tools the consumer actually grades; the rest are out of its
claim by design.

## Install-gate decision (per-tool, aggregated)

`installpolicy.run` now adjudicates the bundle class: on `AMBIGUOUS_ENTRYPOINT` it
re-derives one bundle per tool and aggregates —

- a graded tool that **contradicts** its goldens → **block** (the reason names the tool);
- else ≥1 graded tool re-derived → **allow** (ungraded tools don't block);
- no tool had goldens / execution off → **unjudgeable** per `ON_UNJUDGEABLE`.

So the honest `clean-json-toolkit` **installs** (query+flatten conform; the 5 ungraded
tools are unjudgeable, not contradictions), and a copy with a broken `query` is
**blocked by real OpenClaw** — see [`LIVE_RUN.md`](LIVE_RUN.md). The
no-goldens-vs-contradicted split is read from the grader's `no_goldens_for_kind`
marker in the verdict detail (veriker maps every non-zero pack exit to `MISMATCH`, so
that marker is what tells "I don't grade this tool" apart from "this tool is broken").

## Honesty rails (shared with the other demos)

Functional-conformance only (not security, not prose-quality — run alongside
ClawScan/VirusTotal). The **consumer's** grader is the trust root; goldens are
consumer-supplied, never bundle-supplied. No LLM-judge anywhere — an un-grounded
verdict is the poisoned-label failure the ALE line warns against. A tool the gate
cannot re-derive is refused, never fabricated. See [`TOOL_BUNDLE_RUN.md`](TOOL_BUNDLE_RUN.md)
for captured runs and the strategic reading.
