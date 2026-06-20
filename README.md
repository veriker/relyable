# relyable

> **Your agent wrote a skill, graded its own work, and installed it on itself. Who checked the behavior?**

A self-improving agent distills a skill from its own successful turns and can apply it
on the next turn with no human in between (OpenClaw's `approvalPolicy: 'auto'`; the
Hermes skill auto-creation loop). The same model wrote the skill, ran it, and judged
whether it works — it is the **author, executor, and quality inspector of its own
skills, with no external validation point.**

The one check that ships today is **provenance, not behavior.** `openclaw skills verify`
confirms the bytes are authentically the author's and unmodified — and it does that job
correctly. It says nothing about whether those bytes still do what they claim.

And behavior is pinned almost nowhere else either. Across a random sample of ~1,000 live
ClawHub skills, **about 1 in 100 ship any checkable behavioral spec** — a test suite, a
documented command→output example, or fixtures (9 of 966; 95% CI 0.5–1.8%). The other
~99% pin behavior nowhere — not by `verify`, not by the authors' own docs.

**relyable is the missing second party.** Before your agent admits a skill, recalls a
note, or trusts an "all tests pass," relyable **re-derives the claim itself** — it runs
the suite, re-runs a skill against a checkable spec, recomputes a recalled value. The
agent's word is never an input. Built on the
[veriker](https://pypi.org/project/veriker/) re-derivation substrate. Apache-2.0, `v0.x`
experimental.

> **See it in 30 seconds** → [`demos/`](demos/): point the detector at your own installed
> skills (`demos/self_spec/sample_clawhub.py`), then watch the gate catch a skill that
> contradicts its own documented example.

## What's in the box

relyable is one gate (`relyable.gate`) with three surfaces over it:

| Surface | Re-derives… | Built for |
|---|---|---|
| **`relyable.verdicts`** | "all tests pass" — the gate runs the suite; the agent's prose isn't an input | any agent or CI (MCP / JUnit-XML / in-process) |
| **`relyable.skills`** | a skill's claimed verdict *before* it's admitted | **Hermes** self-created skills |
| **`relyable.memory`** | a recalled note *at recall* | **OpenClaw** auto-recall memory |

One principle underneath all three — **the trust layer for a self-improving agent: a
claim is never trusted, it is re-derived.** A skill, note, or verdict is usable iff
re-running it reproduces; anything that can't re-derive is dropped, never passed through
as a weak signal.

## Install

```bash
pip install relyable            # the suite (verdicts + gate + skills + memory)
pip install "relyable[mcp]"     # + the MCP server shell
```

relyable is the first product built on the
[veriker](https://pypi.org/project/veriker/) substrate, which it pulls in as a
dependency.

## `relyable.verdicts` — un-fakeable "all tests pass"

Make a coding agent's **"all tests pass"** un-fakeable and its suite un-gameable.
The gate *owns test execution*: the agent requests a run, the gate runs it and
returns the real verdict — framework-agnostic via JUnit-XML. Four ratchets
(`no_shrink`, `no_new_skip`, `diff_coverage`, `mutation`) catch the gaming a green
verdict alone can't: deleted tests, new skips, uncovered diffs, assertion-free
tests. Run it in CI, or expose it as the agent's **only** test tool over MCP so it
can't self-assert outcomes.

→ **[`relyable/verdicts/README.md`](relyable/verdicts/README.md)** — CI usage, the
MCP tool, the config anchor, the ratchets, and re-derivable audit-bundle
attestation.

## `relyable.skills` — don't install a skill that lies about passing · Hermes

A self-improving agent creates skills from experience and ships each with an
*asserted* "this passes" label — it is simultaneously the author, executor, and
inspector of its own skills. relyable's skills binding **never reads that label
for the decision.** It re-runs the candidate against **your own** held-out goldens
through veriker's gated re-derivation lane; a skill is usable iff that
re-derivation reproduces. A poisoned or unverifiable label is **inert — dropped,
never passed through.** (Worst case the registry is empty, never net-negative.)

The grader is the trust root — but you shouldn't have to write it from a blank
page. Two commands lower that bar: **`relyable-skills init`** detects the cheapest
applicable trust-root rung for a skill (a pre-existing suite > a schema property >
determinism > held-out goldens) and scaffolds the grader; **`relyable-skills
prove`** lets an agent *propose* an acceptance property (`round_trip` /
`idempotence` / `schema_conformance`) and certifies it is **non-vacuous** by
driving real mutation testing — the property must KILL the mutants or it is
rejected. The honest catch, carried on every surface: kills-mutants proves
non-vacuous, **not** correct-spec.

**Author-grounded mode (`self_spec`).** When a skill ships its *own* committed standard
— a test suite, a documented command→output example, or example fixtures — relyable
grades it with no consumer goldens at all: re-derive the author's own oracle against the
authentic bytes (`REPRODUCES` / `CONTRADICTS` / `UNJUDGEABLE`). It's how we measured the
gap in the hero — [`demos/self_spec/`](demos/self_spec/) runs it over real ClawHub
skills, and [`sample_clawhub.py`](demos/self_spec/sample_clawhub.py) reproduces the ~1%
figure on a random live sample.

→ **[`relyable/skills/README.md`](relyable/skills/README.md)** — the
grader-as-trust-root, the `relyable-skills` CLI (`admit` / `init` / `prove`), and
the experiment evidence behind the claim.

## `relyable.memory` — don't recall a note that can't re-derive · OpenClaw

A persistent agent recalls long-term memory before each turn — a cached result, a
derived value, a fact. relyable's memory binding **never lets the note be used on
the strength of being remembered.** At recall it must re-derive: **recompute** the
cached value from its own inputs (turnkey, no external authority), or **match a
sealed first-party reference** the recall-time agent can't rewrite. A poisoned
note — including one smuggling its own fake reference — is refused.

→ **[`relyable/memory/README.md`](relyable/memory/README.md)** — both modes,
reference anchoring (`relyable-memory anchor`), and the experiment evidence.

## Adapters: Hermes + OpenClaw

relyable wires the same gate into both harnesses, on both the skill-admission and
memory-recall edges (and the output edge):

| Edge | Hermes (`adapters/hermes/`) | OpenClaw (`adapters/openclaw/`) |
|---|---|---|
| **Skill admission** | skill-write guard `_security_scan_skill` — a skill that doesn't re-derive is dropped on write (`None` admits, a reason string rejects) | `security.installPolicy` command (`relyable-installpolicy`) — a staged skill is packed and re-derived before the install proceeds; allow/block |
| **Memory recall** | a `MemoryProvider` (`prefetch`) — only notes that re-derive are returned for the turn | `before_prompt_build` plugin — only notes that re-derive are prepended; everything else returns `undefined` |
| **Output edge** | re-derive a turn's deliverable before it's emitted | `message_sending` plugin — an outbound payload that doesn't re-derive is suppressed (`{cancel: true}`) |

(Hermes also gets a `/goal`-completion gate: re-derive a goal's "done" from evidence,
not the agent's say-so.)

Integration mode follows what each harness exposes. **OpenClaw** has plugin hooks
(`before_prompt_build`, `message_sending`) and a policy-command seam
(`security.installPolicy`), so relyable drops in as plugins / a policy command — no
fork. **Hermes** exposes a clean `MemoryProvider` ABC, but has no skill-lifecycle or
before-final plugin hook, so those adapters are a one-line call added at the real
chokepoint (relyable ships as a pip dependency Hermes imports). relyable is an
independent project; each adapter's `DISCOVERY.md` pins the exact upstream seam it was
verified against.

## How it works: re-derive, don't trust

Every surface runs the same play. The producer's claim — verdict, skill label, or
recalled note — is **re-derived** by a trusted side the producer doesn't control:

- **The agent can't author the thing that judges it.** The grader (skills) is
  byte-pinned into every bundle; the config (verdicts) is pinned to an out-of-band
  anchor; the reference (memory) is anchored and sealed. Tampering trips a
  fail-closed mismatch *before* any verdict — the veriker **SpecAnchor** pattern:
  authority is supplied by the trusted side, never selected by the producer.
- **The claim is never an input.** A re-stamped tree, a poisoned label, a fake
  reference — none of them move the verdict, because the verdict is recomputed,
  not read.

## What it does and does NOT prove

- **Does:** an agent can't produce a green verdict without the suite passing under
  the gate, can't admit a skill its claimed grader doesn't actually re-derive, and
  can't recall a note that doesn't recompute or match a sealed reference — even
  with a fully re-stamped tree.
- **Does not:** make *all* gaming impossible. A tautological test the agent wrote,
  a grader that isn't exhaustive, or a reference that's itself wrong are the
  consumer's responsibility — the gate guarantees the claim was *re-derived
  against your authority*, not that your authority is complete. The mutation
  ratchet is the strongest lever, not a completeness proof.
- **Sandboxing untrusted code is the host's job.** Skill/memory vetting runs
  candidate code when you opt in (`permit_execution=True`); run it where that's
  acceptable.

## Status

`v0.x` — **experimental**, honestly framed: relyable rides the veriker substrate
and carries the same experimental frame (no "production / verified" claims on
light testing). Engine + CLI + MCP tool, all four ratchets, audit-bundle emission,
and both the Hermes and OpenClaw adapters — including the author-grounded `self_spec`
axis — are implemented and tested (293 passing tests; `pytest` in `tests/`). The verdict re-derivation path itself is stdlib-only
— a test verdict can be re-derived with no third-party trust. Apache-2.0.

---

relyable is built and maintained by the team at Nexi Technologies, Inc., on the
open veriker (https://github.com/veriker/veriker) substrate. We also build
NEXIVERIFY (https://nexiverify.com), a commercial audit-trail product for
regulated teams. relyable is and remains free and open under Apache-2.0 — see
our no-relicense pledge (NO-RELICENSE.md).
