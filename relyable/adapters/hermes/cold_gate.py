"""cold_gate.py — manufacture a re-derivation check for a skill at admission time.

Thin Hermes binding over the shared engine ``relyable.skills.cold_golden`` (the
engine was LIFTED from this module 2026-07-08 so the scan surface could use the
same methodology without importing through the Hermes adapter; the constructor
prompt, verdict taxonomy, anti-vacuity discipline, and DIVERGED-never-accuses
rail are unchanged — see demos/cold_golden/COLD_GOLDEN_RUN.md).

This binding contributes exactly one thing: the LLM call. Inside Hermes the
constructor call goes through ``auxiliary_client`` (task="cold_constructor", so
the provider/model resolves from auxiliary.cold_constructor config). The cold
context (description-only, never source) makes same-model honest. Standalone
(tests), the constructor is unavailable and the lane reports ABSTAIN — the gate
is a no-op.

The gate is purely additive at admission: no verdict drops a skill. PASS is an
affirmative trust signal; everything else is honest holes. The drop decision
stays with the existing security scan.
"""

from __future__ import annotations

from pathlib import Path

# Re-exported for existing/planned Hermes callers — the public surface of this
# module is unchanged by the engine lift.
from relyable.skills.cold_golden import (  # noqa: F401
    ColdGateResult,
    GoldenResult,
    adjudicate_cold as _adjudicate_cold,
    run_golden,
)

# ── Optional Hermes integration ──────────────────────────────────────────
try:
    from agent.auxiliary_client import call_llm as _call_llm  # type: ignore
except ImportError:
    _call_llm = None  # standalone / test


def _hermes_llm_call(system: str, user: str, timeout: float) -> str:
    """Adapt Hermes' auxiliary_client to the engine's (system, user, timeout)."""
    resp = _call_llm(
        task="cold_constructor",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=4096,
        timeout=int(timeout),
    )
    if resp is None or not getattr(resp, "choices", None):
        raise RuntimeError("constructor call returned no response")
    return resp.choices[0].message.content or ""


def adjudicate_cold(skill_dir: Path, *, do_mutate: bool = True) -> ColdGateResult:
    """Entry point called from Hermes' ``_security_scan_skill`` after the
    existing injection scan passes. Purely additive — no return from this
    function causes the caller to drop the skill."""
    llm = _hermes_llm_call if _call_llm is not None else None
    return _adjudicate_cold(
        skill_dir,
        llm_call=llm,
        model_label="hermes:auxiliary.cold_constructor" if llm else "",
        do_mutate=do_mutate,
    )
