"""relyable.memory — re-derive a recalled note at recall, never trust it remembered.

The memory binding of relyable. A persistent agent recalls a stored note (a cached
result, a derived value, a fact). This binding never lets the agent use that note
on the strength of its being remembered — at recall, the note must **re-derive**,
or it is refused. There are two modes, by how the note re-derives:

**1. Recompute (turnkey, no external authority).** When the note is a cached
computation, the grader re-runs the computation from the note's own inputs; the
authority is determinism, so there is nothing to curate and ``reference_path`` is
not needed. This is the mode that fits a solo user.

    from relyable.memory import admit_note, ADMIT

    v = admit_note("agg", {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}},
                   grader_src=recompute_grader)     # no reference_path
    if v.verdict == ADMIT:
        use(...)          # the cached result still recomputes from its inputs

**2. Sealed reference (for a fact you can't recompute).** The grader checks the
note against a sealed first-party reference the consumer controls, imported via the
gate-set PYTHONPATH (``reference_path``), **never from the bundle** — so a poisoned
note that ships its own fake reference cannot override the real one. This mode is
**only as strong as the reference is authoritative and out-of-band from the
agent** — but the load-bearing part is *separation, not authorship*: a consumer
may point it at a source they already own (an internal feed, a registry, the live
environment) OR have an LLM build the reference in a separate pass, then commit and
pin it before recall. Not an oracle (it inherits creation-time error), but a large
step up from trusting a remembered value.

    v = admit_note("pkg", {"package": "acme", "version": "1.4.2"},
                   grader_src=my_grader, reference_path=sealed_ref_dir)

Evidence: ALE Exp M (recompute/safe-lift — verified-good memory lifts at zero
wrapper cost, the same gate refuses poison), F2 (calibration pointer), H3
(poisoning axis, powered — and notably the agent's own re-check *amplifies* poison,
so a deterministic re-derivation beats "let the agent verify itself"),
D/E/persistent-E (recover-to-baseline across real multi-session drift). The honest
claim is bounded: where the channel carries truth an agent's own verification can
match the gate (H3 V_faithful); the gate's value is re-deriving without depending
on the channel — and, in mode 2, it is no stronger than the reference it is given.
"""

from __future__ import annotations

from .anchor import (
    ReferenceAnchorMismatch,
    compute_reference_anchor,
    verify_reference_anchor,
)
from .bundle import build_note_bundle, render_candidate
from .gate import ADMIT, REJECT, RecallVerdict, admit_note

__all__ = [
    "ADMIT",
    "REJECT",
    "RecallVerdict",
    "ReferenceAnchorMismatch",
    "admit_note",
    "build_note_bundle",
    "compute_reference_anchor",
    "render_candidate",
    "verify_reference_anchor",
]
