# Netcut — reclaiming a piece of the NETWORK majority (run 2026-06-21)

`COLD_GOLDEN_RUN.md` §11 classified ~69% of *code-bearing* ClawHub skills as NETWORK and
abstained on all of them: "behaviour is exogenous to the code." That verdict was too
coarse. A network skill is a **pipeline**, and only the middle arrow is off-box:

```
build_request(input)  ->  call(remote)  ->  parse/transform(response)  ->  output
   ^deterministic          ^exogenous         ^deterministic
```

The two ends are ordinary local functions — auth-signing, param/amount encoding, field
extraction, scoring, formatting — and that is where the *claimed behaviour* and the bugs
live. This run pins the two deterministic ends by treating the network boundary as frozen.
Harness: `netcut.py` (mechanism proof, executed), `netscan.py` (population sizing, static).

## 1. It works end-to-end — `dex-quote` (executed, `netcut.py`)

`dex-quote` is an OKX DEX aggregator client: HMAC-signed `GET /api/v6/dex/aggregator/quote`
request-build + pure response parsers (`TokenInfo.from_api`, `QuoteResult` assembly +
`summary()`). We froze the clock (the one exogenous input to request-build — the HMAC
timestamp), used fixed dummy credentials, and intercepted the single `session.get` call.

**CUT 1 — request shape (no recorded response):**

| check | result |
|---|---|
| request-build deterministic (2 runs byte-identical) | PASS |
| hits documented host `web3.okx.com` | PASS |
| hits documented path `/api/v6/dex/aggregator/quote` | PASS |
| builds documented params `{chainIndex, fromTokenAddress, toTokenAddress, amount, swapMode}` | PASS |
| HMAC signature matches an **independent** re-derivation (our own code, OKX's documented `b64(HMAC-SHA256(secret, ts+method+path))`) | PASS |

**CUT 2 — response parse (boundary-pinned to one cassette):** the recorded OKX response
parses to the documented `QuoteResult` and `summary()` (1 ETH → 3,498.20 USDC, fee $2.10,
Uniswap V3 route).

**Anti-vacuity (mutation) gate — `kill 4/4`:** mutate `_sign` (drop method from prehash) →
signature diverges; mutate `to_raw_amount` (10× error) → request `amount` diverges; mutate
`TokenInfo.from_api` (wrong field) and drop `tradeFee` → summary diverges. Every golden is
load-bearing, not vacuous.

So a network skill's request-construction (incl. HMAC signing and amount conversion) and
its response parsing are **deterministically re-derivable offline**, with mutation teeth.
What is *not* reclaimed: whether OKX is live, authentic, or returns honest prices — that is
provenance + a contract test, a different axis (ClawHub `verify`), not re-derivation.

## 1b. Second demonstrator, different shape — `kalshalyst` (executed, `netcut_parse.py`)

`dex-quote`'s re-derivable surface is dominated by request SIGNING. To show the cut is not
one lucky shape, the second demonstrator is the opposite: `kalshalyst`, a Kalshi
prediction-market BI tool with **no HMAC and no client class** — its re-derivable surface
is a layer of pure module-level functions that normalize/filter/classify fetched market
data (`_normalize_market`, `_is_blocked`, `_is_sports`, `_is_noise_market`). This is the
"applies scoring algorithms to live data" case. No network interception is even needed —
the parse layer is directly importable; we run it over ONE recorded Kalshi `/markets`
payload (cassette).

| check | result |
|---|---|
| v3 dollar-strings → integer cents (documented `round(float×100)`) | PASS (0.4500→45, 0.4800→48, …) |
| `*_fp` strings → integers | PASS |
| clean politics market NOT blocked | PASS |
| weather market blocked (by category) | PASS |
| sports market detected (by phrase "super bowl") | PASS |

**Anti-vacuity — `kill 3/3`** (mutate `_dollars_to_cents` ×100; drop `"weather"` from the
blocked-category set; drop the `"super bowl"` phrase → each golden diverges).

**The gate caught a real over-determination on the way.** The first cassette used a weather
market whose ticker ALSO had a blocked prefix (`KXTEMP…`) and a sports title that matched
both the phrase AND the single word "nba" — so two of the three classify-mutations
**SURVIVED** (the verdict was blocked/detected for a *second*, un-mutated reason). That is
exactly the vacuity relyable's anti-vacuity gate exists to flag: a golden that doesn't
isolate the path it claims to check. Fixing the cassette to isolate one code path each
(non-prefixed weather ticker; a phrase-only sports title) turned 1/3 → 3/3. The discipline
worked on the demo author, not just the skill.

**Honest boundary, stated in the demo:** `kalshalyst`'s FINAL output is a Claude contrarian
estimate — model output, NOT re-derivable, and not claimed. What re-derives is the
deterministic normalization + filtering pipeline that *feeds* the model. This is
**intermediate re-derivation**: pin the deterministic stages even when the last stage is a
model. (It is also why `netscan.py` §2 correctly EXCLUDES kalshalyst from the strict parse
count — its end-product is model output — while its request + normalization stay
re-derivable.)

## 2. How common is the structure? (n=62 NETWORK skills, static, `netscan.py`)

Mechanical scan (no LLM, no spend) of the 62 NETWORK-classified skills in the seed-11 /
194-skill pool, splitting boilerplate util files out and **excluding model-generated
output** from the parse count (an LLM/vision skill's "answer" is exogenous even though its
request is not):

| cut | k/62 | rate | what it buys |
|---|---|---|---|
| **request-build re-derivable** (signed or param/URL assembly) | 40 | **65%** | request-shape golden, **no cassette needed** |
|   — of which carry request **signing** (HMAC etc.) | 17 | 27% | highest-value: signing bugs are real & invisible today |
| **parse re-derivable** (real local transform, NOT model output) | 19 | **31%** | cassette parse golden |
|   — BOTH halves (dex-quote-like, strongest) | 14 | 23% | full boundary re-derivation |
| reclaimable at all (request OR parse) | 43 | 69% | some deterministic check exists |
| passthrough (verbatim body) — reclaim nothing | 2 | 3% | stays in provenance's lane |
| no local boundary code detected | 17 | 27% | thin wrappers / shell-outs |

**11 further skills** had parse-shaped code but emit **model output** (smyx AI-vision
diagnosis, kalshalyst's Claude estimation, the byted subtitlers) — correctly **excluded**
from parse-reclaim; their request half still counts.

### Honest scope of §2

- This is a **structural upper bound** (regex over source), not a per-skill re-derivation.
  `dex-quote` is the executed existence proof (§1) that the structure pays out; the other
  39 request-reclaimable / 18 parse-reclaimable skills are *candidates*, not confirmed.
- The **request cut (65%) is the robust, generalizable one**: even an LLM/vision skill
  builds a deterministic, re-derivable request. The **parse cut (31%) is narrower and
  softer** — it was the one inflated by shared-template boilerplate (`smyx_common` casing/
  http helpers) before the util-split + model-output exclusion, which is why those two
  filters matter.
- A request-shape golden is a **weaker claim** than full behaviour re-derivation: it
  certifies "the code builds the request the docs describe" (endpoint, params, correct
  signing), not "the answer is right about the world." It is exactly the un-checked-today
  surface for an integration whose docs say "calls the X API with your key and a query."

## 2b. POWERED — actually executing the request cut (n=40, `netpower.py`)

§2 was structural (regex). This POWERS it: for each of the 40 request-reclaimable skills,
an LLM constructor (one direct-API call, like cold_golden) reads SKILL.md + the entry
script and emits a runnable offline invocation (entry, two argv variants differing in one
user value, fake-cred env) + the doc-claimed request; the skill is then **executed** under
an injected `sitecustomize.py` that freezes the clock, no-ops sleeps, intercepts every HTTP
egress (requests/urllib/http.client/httpx) and **hard-blocks real sockets** as a backstop.
Verdict per skill from the captured request:

  RE-DERIVED = determinism (same input ×2 → identical request) ∧ sensitivity (different
  input → request changes — anti-vacuity) ∧ conformance (host/path/params match the docs).

| verdict | k/40 | rate |
|---|---|---|
| **RE-DERIVED** (deterministic, input-sensitive, doc-conformant, fully automated) | 5 | **12%** |
| WEAK (ran + built a deterministic offline request, missed ≥1 criterion) | 4 | 10% |
| ABSTAIN (couldn't be driven to an offline request) | 31 | 78% |
| — conditional on the skill RUNNING to a request (9) | 5/9 | **56% RE-DERIVED** |
| — of those that ran, carried an auth/signature header | 7/9 | 78% |

The 5 RE-DERIVED are real, varied, hand-verified: `dex-quote` (OKX, HMAC-signed),
`deep-research-v50` (NCBI PubMed), `dota2-coach` (OpenDota), `huawei-cloud-cce…` (Huawei ECS,
signed), `xclawskill` (signed agent-discovery). Each built a deterministic, input-sensitive
request to the documented endpoint **offline, with zero hand-tailoring**.

### The honest reading — structural 65% vs powered 12%

The gap is the whole finding. **Code-presence (§2, 65%) is cheap; driving a skill to its
network call with NO author-provided inputs is expensive.** The 31 ABSTAINs break down as:
~19 the constructor declined (needs a real input file / a Solana keypair / an interactive
OAuth dance / no argv interface / hardcoded inputs), ~10 ran but never reached a request
(vision skills needing a real image, tools needing a config file), ~1 harness/JSON error.
None of those is proof the request code *isn't* re-derivable — it is proof that **automatic,
zero-input re-derivation is thin**, exactly as cold_golden found for the local slice
(~1.7% auto-confirm). The binding constraint is the same: the author shipping a runnable
invocation + a fixture. That is the golden-convention ask, now quantified from two angles.

Caveats (state them): the constructor is stochastic, so the headline moves ±1–2 skills
run-to-run (e.g. `wutrix` re-derived on one run, WEAK on another — it uses a placeholder
host the constructor fills differently each time). "RE-DERIVED" here is request-SHAPE
conformance + determinism + input-sensitivity — weaker than netcut's independent HMAC
re-derivation (§1), which is per-skill and not automated. Python-primary skills only; the
5 JS skills abstain. Mechanical artifacts: `NETPOWER_RUN.json`, `_netpower_hooks/`.

**Bottom line of the powered run:** the auto-confirm layer for network request-build is
**~12% (CI-wide, ~1 in 8) of request-reclaimable skills, ~56% of those you can actually
run** — thin by nature, signed in ~4 of 5 cases, and gated by author-provided drivability,
not by absence of re-derivable code. Map + thin auto-confirm + on-ramp, same shape as the
local slice.

## 3. What this does to the funnel

Prior (`COLD_GOLDEN_RUN.md`): ~47% code-bearing; of code-bearing, NETWORK ~69% was treated
as entirely unreachable, leaving the deterministic-checkable surface at ~11% of the catalog
(the LOCAL_DETERMINISTIC slice). Folding in the network request cut:

```
random ClawHub skill                                n = 242 (powered) / 194 (classified)
  ships functional code                ~47%
    LOCAL_DETERMINISTIC (full re-derivation)         ~11% of catalog
    NETWORK request-build re-derivable   0.65 × (0.69 × 47%) ≈ ~21% of catalog (request-shape golden)
    NETWORK both-halves (dex-quote-like) 0.23 × (0.69 × 47%) ≈ ~7%  of catalog (full boundary re-derivation)
```

So the deterministically-checkable surface is **not ~11% — it is ~30%+ of the catalog**
once you count the request skeleton of the network majority, with a smaller dex-quote-like
core (~7%) that re-derives both halves. The "NETWORK = unreachable" line was wrong; the
honest line is "the *live call* is unreachable, but the request the code builds around it,
and often the parse, are not."

## 4. For the ClawHub conversation

- Pre-empts the obvious objection ("isn't most stuff just API calls?"). Answer: an API
  skill is *build-request → call → parse*; we can't re-derive the call, but we **can**
  re-derive that the code builds the documented request (right endpoint, right params,
  correct signing) and parses the response as documented — against a recorded boundary.
- Strengthens the **golden-convention ask**: a blessed format that supports a recorded-
  fixture / cassette field (and a request-shape assertion) covers integrations too, not
  just pure local functions — i.e. ~30% of the catalog, not ~11%.
- Hold the honesty line: request-shape ≠ correctness; the cassette is author-attested
  input like any golden; provenance/liveness is a separate axis we do not claim.

Artifacts: `netcut.py` (dex-quote, request+parse, 4/4 kill), `netcut_parse.py` (kalshalyst,
parse/transform, 3/3 kill), `netscan.py` + `NETCUT_SCAN.json` (n=62 structural scan),
`netpower.py` + `_netpower_hooks/` + `NETPOWER_RUN.json` (n=40 POWERED execution run).
Caveat vs the §10–§12 powered numbers: §2 here is a static structural scan, not a powered
per-skill re-derivation. A confirmatory run would harness a random sample of the 40
request-reclaimable skills the way `netcut` harnesses `dex-quote`.
