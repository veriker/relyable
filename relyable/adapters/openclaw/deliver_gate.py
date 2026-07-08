"""deliver_gate.py — gate OpenClaw outbound output through relyable's re-derivation.

The OUTPUT-edge mirror of ``recall_gate.py``. OpenClaw's ``message_sending`` hook
(in a TS plugin) fires once per outbound payload, *after* the model produces it and
*before* it is sent to the user/channel, and supports ``{cancel: true}`` suppression
(verified seam — see ``../../../DELIVER_EDGE_DISCOVERY.md``). This gate re-derives a
**deliverable** (the claim the agent is about to deliver) and suppresses any that do
not hold, so fabricated "I did X" output is dropped instead of delivered — the
fail-closed posture ``openclaw/openclaw#49876`` asks for ("if the task cannot be
verified as complete → deliver nothing").

It adds no trust logic: it re-derives each deliverable with the same shared relyable
primitive the memory binding uses (``relyable.memory.admit_note`` -> ``relyable.gate``
-> veriker). The deliverable's ``payload`` is the value being delivered; it is never
trusted as a value — the grader re-derives it (recompute mode: re-run the claimed
computation from its inputs) or checks it against a sealed first-party reference
(sealed-reference mode). A free-text output with no checkable claim has nothing to
re-derive and is out of scope for this gate (the plugin passes it through; see the
discovery note's text-only caveat).

A candidate is ``{"deliverable_id": str, "payload": <json>}``.
"""

from __future__ import annotations

from dataclasses import dataclass

from relyable.memory import ADMIT, admit_note

from .config import DeliverGateConfig


@dataclass(frozen=True, slots=True)
class DeliverGateResult:
    """One deliverable's verdict. ``admitted`` is True iff it re-derived;
    ``cancelled`` is its negation — the deliver-edge action the plugin takes."""

    deliverable_id: str
    verdict: str
    reason_code: str
    detail: str
    rederived: bool

    @property
    def admitted(self) -> bool:
        return self.verdict == ADMIT

    @property
    def cancelled(self) -> bool:
        return not self.admitted


def gate_deliverable(
    deliverable_id: str,
    payload: object,
    config: DeliverGateConfig,
) -> DeliverGateResult:
    """Re-derive one outbound deliverable. ADMIT (deliver) iff it re-derives against
    the grader (recompute) or the sealed reference; otherwise REJECT (suppress)."""
    v = admit_note(
        deliverable_id,
        payload,
        grader_src=config.grader_src,
        reference_path=config.reference_path,
        reference_anchor=config.reference_anchor,
        permit_execution=config.permit_execution,
        pack_filename=config.pack_filename,
    )
    return DeliverGateResult(
        deliverable_id=v.note_id,
        verdict=v.verdict,
        reason_code=v.reason_code,
        detail=v.detail,
        rederived=v.rederived,
    )


def gate_deliverables(
    candidates: list[dict],
    config: DeliverGateConfig,
) -> list[DeliverGateResult]:
    """Gate a batch of candidate deliverables. Returns one result per candidate
    (admitted and suppressed alike) for the audit trail. A candidate missing a
    ``payload`` is suppressed, not skipped (fail-closed: a malformed deliverable
    does not silently pass through to delivery)."""
    out: list[DeliverGateResult] = []
    for i, cand in enumerate(candidates):
        deliverable_id = str(
            cand.get("deliverable_id") or cand.get("id") or f"deliverable_{i}"
        )
        if "payload" not in cand:
            out.append(
                DeliverGateResult(
                    deliverable_id,
                    "REJECT",
                    "MALFORMED_CANDIDATE",
                    "candidate has no 'payload' to re-derive",
                    rederived=False,
                )
            )
            continue
        out.append(gate_deliverable(deliverable_id, cand["payload"], config))
    return out


def admitted_deliverable_ids(results: list[DeliverGateResult]) -> list[str]:
    """The deliverable_ids the plugin may send: those that re-derived."""
    return [r.deliverable_id for r in results if r.admitted]


def cancelled_deliverable_ids(results: list[DeliverGateResult]) -> list[str]:
    """The deliverable_ids the plugin must suppress: those that did not re-derive."""
    return [r.deliverable_id for r in results if r.cancelled]
