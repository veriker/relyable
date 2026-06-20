"""goal_guard.py — re-derive a Hermes ``/goal``'s completion from evidence.

The fix for Hermes #18421: the ``/goal`` judge (``hermes_cli/goals.py::judge_goal``,
driven by ``evaluate_after_turn``) marks a goal DONE from the agent's *textual*
response alone — it receives only ``goal`` + ``last_response`` + ``subgoals``, with no
``messages``, tool outputs, filesystem, or ledger (see ``../../../DELIVER_EDGE_DISCOVERY.md``).
So a turn that says "file created successfully" is marked DONE even when the write
silently failed. This guard re-derives the *completion claim* against evidence and
reports done **only when it affirmatively re-derives** — the integrator gates the
existing judge on this (a goal is not DONE unless the evidence re-derives), or
replaces the text-judge for evidence-checkable goals.

Direct in-process call (Hermes is Python). The completion claim is a structured
deliverable ``{goal_id, payload}`` the integrator builds from the turn: ``payload``
carries the claim + the inputs the grader re-derives against (e.g. the target path so
a recompute/filesystem grader can confirm the artifact actually exists with the
expected content). Re-derives via the shared relyable primitive
(``relyable.memory.admit_note`` -> ``relyable.gate`` -> veriker). A goal with no
checkable completion evidence is out of scope (the integrator falls back to the
text-judge for those) — the gate's value is exactly the evidence-checkable goals that
#18421 is about.
"""

from __future__ import annotations

from dataclasses import dataclass

from relyable.memory import ADMIT, admit_note

from .config import HermesGoalConfig


@dataclass(frozen=True, slots=True)
class GoalVerdict:
    """A goal's re-derived completion verdict. ``done`` is True iff the completion
    claim affirmatively re-derived against evidence."""

    goal_id: str
    done: bool
    reason_code: str
    detail: str
    rederived: bool


def rederive_goal_completion(
    goal_id: str,
    payload: object,
    config: HermesGoalConfig,
) -> GoalVerdict:
    """Re-derive a goal's completion claim. ``done`` iff it re-derives against the
    grader (recompute / filesystem evidence) or the sealed reference; otherwise not
    done — the fail-closed answer to the #18421 false positive."""
    v = admit_note(
        goal_id,
        payload,
        grader_src=config.grader_src,
        reference_path=config.reference_path,
        reference_anchor=config.reference_anchor,
        permit_execution=config.permit_execution,
        pack_filename=config.pack_filename,
        kind="goal_completion",
    )
    return GoalVerdict(
        goal_id=v.note_id,
        done=v.verdict == ADMIT,
        reason_code=v.reason_code,
        detail=v.detail,
        rederived=v.rederived,
    )


def goal_done(
    goal_id: str,
    payload: object,
    config: HermesGoalConfig,
) -> bool:
    """``evaluate_after_turn``-shaped guard: True ONLY when the goal's completion
    claim re-derives from evidence — never from the agent's text claim alone. The one
    call a Hermes integrator adds to gate the existing judge: mark a goal DONE only if
    ``goal_done(...)`` is True (AND, optionally, the text-judge agrees)."""
    return rederive_goal_completion(goal_id, payload, config).done
