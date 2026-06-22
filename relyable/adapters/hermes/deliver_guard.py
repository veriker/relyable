"""deliver_guard.py — re-derive a Hermes turn's deliverable before it is emitted.

The output-edge sibling of ``guard.py`` (which gates skill ADMISSION). Hermes has no
pre-assistant / before-final plugin hook — its ``VALID_HOOKS`` set is tool/LLM/
session/approval-scoped, and the closest, ``transform_llm_output``, is a non-vetoing
text transformer that swallows exceptions (cannot fail closed). See
``../../../DELIVER_EDGE_DISCOVERY.md``. The convergent output chokepoint is
``agent/turn_finalizer.py::finalize_turn`` — the single point every delivery surface
(CLI, gateway, ACP, ``chat()``) reads ``final_response`` from. Integration is a one-
line source-patch there, after the ``transform_llm_output`` block and before the
result dict is built — ideally landed as a new fail-closed ``pre_final_response``
hook, the artifact Hermes #26742 / #22956 / #16357 ask the project to build, and the
"no model discretion" runtime gate #44637 wants.

Because Hermes is Python, this is a DIRECT in-process call (no subprocess) — relyable
ships as a pip dependency Hermes imports. The guard re-derives the turn's structured
deliverable via the shared relyable primitive (``relyable.memory.admit_note`` ->
``relyable.gate`` -> veriker); a deliverable that re-derives is delivered, one that
does not is suppressed (the integrator replaces ``final_response`` with a fail-closed
message — Hermes has no built-in "deliver nothing").

SCOPE (honest, same as the skills/memory gates): re-derives a STRUCTURED deliverable
``{deliverable_id, payload}`` the integrator extracts from the turn (a claimed
computation -> recompute mode; or a fact checkable against a sealed reference). A
free-text ``final_response`` with no checkable claim has nothing to re-derive and is
passed through (the text-only boundary noted in the discovery doc). A ledger-aware
check (the "claimed success with zero tool calls" mode) feeds the turn's tool records
into the grader's evidence — the grader is the consumer's trust root, supplied here.
"""

from __future__ import annotations

from dataclasses import dataclass

from relyable.memory import ADMIT, admit_note

from .config import HermesDeliverConfig


@dataclass(frozen=True, slots=True)
class DeliverVerdict:
    """One deliverable's verdict. ``admitted`` is True iff it re-derived (deliver);
    its negation is the suppress decision."""

    deliverable_id: str
    verdict: str
    reason_code: str
    detail: str
    rederived: bool

    @property
    def admitted(self) -> bool:
        return self.verdict == ADMIT


def rederive_deliverable(
    deliverable_id: str,
    payload: object,
    config: HermesDeliverConfig,
) -> DeliverVerdict:
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
        kind="deliverable",
    )
    return DeliverVerdict(
        deliverable_id=v.note_id,
        verdict=v.verdict,
        reason_code=v.reason_code,
        detail=v.detail,
        rederived=v.rederived,
    )


def deliver_block_reason(
    deliverable_id: str,
    payload: object,
    config: HermesDeliverConfig,
) -> str | None:
    """``finalize_turn``-shaped guard: ``None`` => deliver as-is (the deliverable
    re-derived), or a reason string => SUPPRESS. This is the one call a Hermes
    integrator adds at ``finalize_turn`` (after ``transform_llm_output``, before the
    result dict). On a non-``None`` return, replace ``final_response`` with a fail-
    closed message (or drop it) rather than delivering output that did not re-derive.
    """
    v = rederive_deliverable(deliverable_id, payload, config)
    if v.admitted:
        return None
    return f"relyable: output did not re-derive [{v.reason_code}]: {v.detail}"
