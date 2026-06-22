"""config.py — host config for the OpenClaw recall + deliver gates.

The adapter never ships a grader or a reference: both are the consumer's trust
root. The Python gate CLIs (spawned by the TS plugins) read their config from the
environment the plugin sets. The recall gate (input edge) reads the
``RELYABLE_OPENCLAW_*`` namespace; the deliver gate (output edge) reads the
``RELYABLE_OPENCLAW_DELIVER_*`` namespace, so one install can run both with
different graders.

Recall gate:

  * ``RELYABLE_OPENCLAW_GRADER``            -> grader_src (required; a file path)
  * ``RELYABLE_OPENCLAW_REFERENCE``         -> reference_path (optional dir; the
        sealed first-party reference for sealed-reference mode — omit for the
        turnkey recompute mode)
  * ``RELYABLE_OPENCLAW_REFERENCE_ANCHOR``  -> reference_anchor (optional; pins the
        reference's digest, refuse on mismatch)
  * ``RELYABLE_OPENCLAW_PACK_FILENAME``     -> pack_filename (optional)
  * ``RELYABLE_OPENCLAW_NO_RUN``            -> if truthy, permit_execution=False
        (the grader is not run; every note is refused). Default runs the grader,
        because re-deriving a recalled note IS running the consumer's grader.

A note that does not re-derive is refused either way — ``NO_RUN`` is a hard
fail-closed kill-switch, not the normal posture.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class RecallGateConfig:
    """What the OpenClaw recall gate needs, all consumer-owned.

    ``grader_src`` is the consumer's trusted recall grader. ``reference_path`` is
    the sealed first-party reference dir for sealed-reference mode (``None`` for
    recompute mode). ``reference_anchor`` pins that reference. ``permit_execution``
    mirrors veriker (default True: run the grader to re-derive)."""

    grader_src: Path
    reference_path: Path | None = None
    reference_anchor: str | None = None
    permit_execution: bool = True
    pack_filename: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RecallGateConfig:
        e = os.environ if env is None else env
        grader = e.get("RELYABLE_OPENCLAW_GRADER")
        if not grader:
            raise ValueError(
                "RELYABLE_OPENCLAW_GRADER is required: the consumer's trusted recall "
                "grader is the gate's trust root and has no default."
            )
        ref = e.get("RELYABLE_OPENCLAW_REFERENCE") or None
        anchor = e.get("RELYABLE_OPENCLAW_REFERENCE_ANCHOR") or None
        pack = e.get("RELYABLE_OPENCLAW_PACK_FILENAME") or None
        no_run = e.get("RELYABLE_OPENCLAW_NO_RUN", "").strip().lower() in _TRUTHY
        return cls(
            grader_src=Path(grader),
            reference_path=Path(ref) if ref else None,
            reference_anchor=anchor,
            permit_execution=not no_run,
            pack_filename=pack,
        )


@dataclass(frozen=True, slots=True)
class DeliverGateConfig:
    """What the OpenClaw deliver-edge gate needs, all consumer-owned.

    Same trust-root shape as ``RecallGateConfig`` but on the OUTPUT edge: the gate
    re-derives a *deliverable* (a claim the agent is about to send) before it leaves
    the harness, so fabricated output that does not re-derive is suppressed rather
    than delivered (the ``openclaw/openclaw#49876`` fail-closed ask). A separate env
    namespace (``RELYABLE_OPENCLAW_DELIVER_*``) so one install can run the recall and
    deliver gates with different graders.

    ``grader_src`` is the consumer's trusted deliver grader (it re-derives the
    deliverable — recompute mode — or checks it against ``reference_path`` in
    sealed-reference mode). ``permit_execution`` mirrors veriker (default True: run
    the grader to re-derive)."""

    grader_src: Path
    reference_path: Path | None = None
    reference_anchor: str | None = None
    permit_execution: bool = True
    pack_filename: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> DeliverGateConfig:
        e = os.environ if env is None else env
        grader = e.get("RELYABLE_OPENCLAW_DELIVER_GRADER")
        if not grader:
            raise ValueError(
                "RELYABLE_OPENCLAW_DELIVER_GRADER is required: the consumer's trusted "
                "deliver grader is the gate's trust root and has no default."
            )
        ref = e.get("RELYABLE_OPENCLAW_DELIVER_REFERENCE") or None
        anchor = e.get("RELYABLE_OPENCLAW_DELIVER_REFERENCE_ANCHOR") or None
        pack = e.get("RELYABLE_OPENCLAW_DELIVER_PACK_FILENAME") or None
        no_run = (
            e.get("RELYABLE_OPENCLAW_DELIVER_NO_RUN", "").strip().lower() in _TRUTHY
        )
        return cls(
            grader_src=Path(grader),
            reference_path=Path(ref) if ref else None,
            reference_anchor=anchor,
            permit_execution=not no_run,
            pack_filename=pack,
        )
