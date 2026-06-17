# relyable.memory — re-derive a recalled note at recall

> The **memory surface** of the [relyable](../../) agent-trust suite (on the
> veriker substrate). Consumes `relyable.gate`.

A persistent agent recalls a stored note — a cached result, a derived value, a
fact. This binding **never lets the agent use that note on the strength of its
being remembered.** At recall, the note must **re-derive**, or it is refused.

There are two modes, by *how* the note re-derives. Pick by what the note is.

## Mode 1 — Recompute (turnkey; no external authority)

When the note is a **cached computation**, the grader re-runs the computation from
the note's own inputs and admits only if the cached result reproduces. The
authority is **determinism** — there is nothing to curate or seal, and you don't
pass a `reference_path`. This is the mode that fits a solo user.

```python
from pathlib import Path
from relyable.memory import admit_note, ADMIT
from relyable.memory.examples import recompute_grader

note = {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}}
v = admit_note("agg", note, grader_src=Path(recompute_grader.__file__))   # no reference
if v.verdict == ADMIT:
    use(note["result"])      # still recomputes from its inputs — safe to reuse
```

A poisoned cached result (a `sum` the items don't add up to) is refused: the cached
value is *compared against*, never trusted. Replace the grader's `_recompute` with
your own pure function. **This is the broad case** — any value an agent caches that
is cheaper to keep than to recompute every time, but cheap enough to recompute
*once* before reuse.

## Mode 2 — Sealed reference (a fact you can't recompute)

When the note is a **fact** (a version recommendation, a policy value), there's
nothing to recompute — it has to be checked against a source of truth. The grader
checks it against a sealed first-party reference, imported via the gate-set
PYTHONPATH (`reference_path`), **never from the bundle** — so a poisoned note that
ships its own fake reference cannot override the real one.

```python
v = admit_note("pkg", {"package": "acme-http", "version": "1.4.2"},
               grader_src=Path("recall_grader.py"),
               reference_path=Path("sealed_reference/"))
```

> **Honest scope of mode 2.** The load-bearing requirement is **separation, not
> human authorship**: the reference must be established *out-of-band from the recall
> loop* and live where the recall-time agent can't rewrite it. It does not have to
> be hand-maintained, and it does not have to be perfect to help — it is **only as
> strong as it is authoritative**, but a separately-established, immutable reference
> is a large step up from trusting a remembered value.

**Where the reference comes from.** A consumer who already owns a source of truth
the agent can't rewrite — an internal advisory feed, a package registry, the live
environment (`pip list`, your lockfile), a database view — points the grader at it
and is done. But you don't need a pre-existing one: **having an LLM build the
reference in a separate pass, then committing and pinning it before the agent
recalls against it, is a legitimate and broadly-available way to get one.** It is
not an oracle — a reference inherits any error or poison present *when it was
built*, and an LLM-built one can be wrong — but separating its creation from the
recall loop breaks the exact failure this gate targets: a poison injected at recall
can't rewrite a reference that already exists, and the recalled value can't vouch
for itself. **Significantly more robust than nothing.** What matters:
> 1. build it in a **separate context** from the recall loop;
> 2. **pin** it (see below) so tampering is caught;
> 3. keep it where the **recall-time agent has no write access**.

**Pin the reference (enforced, not advice).** Point #2 is a real mechanism, not a
discipline you have to remember. Anchor the reference once, out-of-band, and pass
the digest in: the gate recomputes the reference tree's digest and **refuses,
fail-closed, before any verify** if it changed.

```bash
relyable-memory anchor ./sealed_reference        # -> a sha; store it in CI / env
```
```python
admit_note(note_id, payload, grader_src=g,
           reference_path=ref, reference_anchor="<the sha>")   # tamper -> REFUSED
```

So the LLM-bootstrap workflow becomes first-class: **generate the reference → anchor
it → and any later edit of the reference is caught** (`REFERENCE_ANCHOR_MISMATCH`),
even if the edited version would have admitted the note. With no anchor the behavior
is unchanged (advisory). The anchor pins the *reference*; the grader is already
byte-pinned into every bundle independently.

See `relyable/memory/examples/` for both graders (`recompute_grader.py`;
`recall_grader.py` + the stand-in `safe_versions.py`).

## Why (the evidence)

- **Exp M (powered, n=50)** — verified-good memory is a **safe lift at zero wrapper
  cost**, and the same gate refuses the poison (the recompute / safe-reuse case).
- **Exp H3 (powered, n=60/cell/tier)** — against corroborated poisoning the gate
  holds attack-success at **0.000**; notably the agent's *own* optional re-check
  **amplifies** the poison, so a deterministic re-derivation beats "let the agent
  verify itself."
- **Exp D / E / persistent-E** — recover-to-baseline across a **real** multi-session
  drift: a gated memory stays correct while raw memory goes silently stale.

Bounded claim: where the channel already carries truth, an agent's own verification
can match the gate (H3 V_faithful). The gate's value is re-deriving *without
depending on the channel* — and, in mode 2, no stronger than the reference given.

## What this does and does NOT prove

- **Does:** make a recalled note un-faked — it must recompute (mode 1) or match an
  out-of-band reference (mode 2); the recalled value is never an input. A poisoned
  note (including one smuggling a fake reference) is refused.
- **Does not:** make a note correct that your *reference* gets wrong, or that your
  recompute function gets wrong. The gate guarantees the note re-derived against
  *your* authority, not that the authority is complete. Keeping the reference sealed
  and authoritative is the consumer's responsibility.
- Sandboxing untrusted candidate code is the host's job (`permit_execution=True`
  runs the grader, which execs the recalled payload).
