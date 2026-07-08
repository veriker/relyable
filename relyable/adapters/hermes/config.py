"""config.py — host config for the Hermes skills adapter.

The adapter never ships a grader: the held-out goldens that decide "does this
skill re-derive" are the consumer's trust root and must be the consumer's own. So
the two things the gate needs — ``grader_src`` (the trusted grader) and
``permit_execution`` (the explicit decision to run candidate code to vet it) — are
host config, supplied by Hermes's own config or environment, not by relyable.

``HermesGuardConfig.from_env`` reads:

  * ``RELYABLE_HERMES_GRADER``         -> grader_src (required; a file path)
  * ``RELYABLE_HERMES_PERMIT_EXECUTION`` -> permit_execution ("1"/"true"/"yes" =>
                                          True; default False, fail-closed)
  * ``RELYABLE_HERMES_PACK_FILENAME``  -> pack_filename (optional)
  * ``RELYABLE_HERMES_REQUIRE_SEPARATION`` -> require_separation (truthy; default
                                          False). Opt into separation of duties.
  * ``RELYABLE_HERMES_GRADER_PRINCIPAL`` -> grader_principal (who authored the
                                          grader; consumer config).
  * ``RELYABLE_HERMES_SESSION_PRINCIPAL`` -> session_principal: the HOST-attested
                                          producing principal (e.g. Hermes's current
                                          session model id). When set, the adapter
                                          stamps it as the artifact principal —
                                          overriding (and stronger than) the
                                          producer-supplied skill/meta.json author.
  * ``RELYABLE_HERMES_SANDBOX``        -> isolation for the re-derivation:
                                          "none" (default; the host/CI is the
                                          boundary — right when relyable already runs
                                          inside an isolated CI job or managed agent),
                                          "subprocess" (an extra process boundary, NOT
                                          a security boundary), or "container" (docker
                                          run, network off). On a bare-host in-process
                                          harness (Hermes/OpenClaw default), prefer
                                          "container" or run the whole harness in a
                                          devcontainer.
  * ``RELYABLE_HERMES_SANDBOX_IMAGE``  -> container image (required if SANDBOX is
                                          "container"; must carry relyable + veriker).

Fail-closed by construction: ``permit_execution`` defaults to False, so an
unconfigured deployment runs no candidate code and admits nothing. When
``require_separation`` is on but no principal can be resolved (neither a session
principal nor a grader principal), the gate fails closed (MISSING_PRINCIPAL).

Separation-of-duties trust sources (see the honesty boundary in
``relyable.gate.verify_attested_bundle``): ``session_principal`` is HOST-attested
(L1 — the producer cannot write it), so prefer it. Falling back to the bundle's
meta author is L0 (forgeable); the verdict's ``principal_source`` records which was
used so an L1 guarantee is never read off an L0 signal.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from relyable.verdicts.sandbox import ContainerSandbox, Sandbox, SubprocessSandbox

_TRUTHY = {"1", "true", "yes", "on"}


def _sandbox_from_env(e: Mapping[str, str]) -> Sandbox | None:
    """Build the opt-in re-derivation sandbox from RELYABLE_HERMES_SANDBOX."""
    mode = (e.get("RELYABLE_HERMES_SANDBOX") or "none").strip().lower()
    if mode in ("", "none"):
        return None
    if mode == "subprocess":
        return SubprocessSandbox()
    if mode == "container":
        image = e.get("RELYABLE_HERMES_SANDBOX_IMAGE")
        if not image:
            raise ValueError(
                "RELYABLE_HERMES_SANDBOX=container requires "
                "RELYABLE_HERMES_SANDBOX_IMAGE (an image with relyable + veriker)."
            )
        return ContainerSandbox(image)
    raise ValueError(
        f"RELYABLE_HERMES_SANDBOX must be none|subprocess|container (got {mode!r})"
    )


@dataclass(frozen=True, slots=True)
class HermesGuardConfig:
    """What the Hermes skills gate needs, all consumer-owned.

    ``grader_src`` is the consumer's trusted grader (held-out goldens + reference
    solver). ``permit_execution`` mirrors veriker: False refuses to run untrusted
    candidate code (every skill stays could-not-conclude / unadmitted); True vets
    by running the candidate on a disposable host. ``pack_filename`` overrides the
    grader's in-bundle filename (defaults to the grader's own name).

    ``require_separation`` + ``grader_principal`` + ``session_principal`` opt into
    separation of duties: a skill whose producing principal equals the grader's
    author is dropped before the grader runs. ``session_principal`` (host-attested)
    is preferred over the bundle's meta author; see the module docstring for the
    trust-source ladder.

    ``sandbox`` (opt-in) is the isolation the re-derivation runs behind; None means
    the host/CI is the boundary (the zero-overhead common case). The isolation
    actually used is stamped on each verdict (``isolation_level``)."""

    grader_src: Path
    permit_execution: bool = False
    pack_filename: str | None = None
    require_separation: bool = False
    grader_principal: str | None = None
    session_principal: str | None = None
    sandbox: Sandbox | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> HermesGuardConfig:
        e = os.environ if env is None else env
        grader = e.get("RELYABLE_HERMES_GRADER")
        if not grader:
            raise ValueError(
                "RELYABLE_HERMES_GRADER is required: the consumer's trusted grader "
                "(held-out goldens) is the gate's trust root and has no default."
            )
        permit = (
            e.get("RELYABLE_HERMES_PERMIT_EXECUTION", "").strip().lower() in _TRUTHY
        )
        pack = e.get("RELYABLE_HERMES_PACK_FILENAME") or None
        require_sep = (
            e.get("RELYABLE_HERMES_REQUIRE_SEPARATION", "").strip().lower() in _TRUTHY
        )
        grader_principal = e.get("RELYABLE_HERMES_GRADER_PRINCIPAL") or None
        session_principal = e.get("RELYABLE_HERMES_SESSION_PRINCIPAL") or None
        return cls(
            grader_src=Path(grader),
            permit_execution=permit,
            pack_filename=pack,
            require_separation=require_sep,
            grader_principal=grader_principal,
            session_principal=session_principal,
            sandbox=_sandbox_from_env(e),
        )


@dataclass(frozen=True, slots=True)
class HermesDeliverConfig:
    """What the Hermes deliver-edge guard needs, all consumer-owned.

    The output-edge sibling of ``HermesGuardConfig``. It re-derives a *structured
    deliverable* (a claim the turn is about to emit) via the shared claim-
    re-derivation primitive (``relyable.memory.admit_note``), so its shape is the
    memory-style grader/reference config, not the skills-style sandbox/separation
    config. ``permit_execution`` defaults True because re-deriving a deliverable IS
    running the consumer's grader (same default as the recall/OpenClaw-deliver gates).
    Separate ``RELYABLE_HERMES_DELIVER_*`` namespace so the skills, memory, deliver,
    and goal guards can coexist in one Hermes install with different graders."""

    grader_src: Path
    reference_path: Path | None = None
    reference_anchor: str | None = None
    permit_execution: bool = True
    pack_filename: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> HermesDeliverConfig:
        e = os.environ if env is None else env
        grader = e.get("RELYABLE_HERMES_DELIVER_GRADER")
        if not grader:
            raise ValueError(
                "RELYABLE_HERMES_DELIVER_GRADER is required: the consumer's trusted "
                "deliver grader is the gate's trust root and has no default."
            )
        ref = e.get("RELYABLE_HERMES_DELIVER_REFERENCE") or None
        anchor = e.get("RELYABLE_HERMES_DELIVER_REFERENCE_ANCHOR") or None
        pack = e.get("RELYABLE_HERMES_DELIVER_PACK_FILENAME") or None
        no_run = e.get("RELYABLE_HERMES_DELIVER_NO_RUN", "").strip().lower() in _TRUTHY
        return cls(
            grader_src=Path(grader),
            reference_path=Path(ref) if ref else None,
            reference_anchor=anchor,
            permit_execution=not no_run,
            pack_filename=pack,
        )


@dataclass(frozen=True, slots=True)
class HermesGoalConfig:
    """What the Hermes ``/goal`` completion guard needs, all consumer-owned.

    Same memory-style claim-re-derivation shape as ``HermesDeliverConfig`` but for
    goal *completion*: it re-derives whether a goal's completion claim holds against
    evidence (recompute mode, or a sealed first-party reference) instead of trusting
    the agent's textual "I completed it" — the #18421 false-positive fix. Separate
    ``RELYABLE_HERMES_GOAL_*`` namespace."""

    grader_src: Path
    reference_path: Path | None = None
    reference_anchor: str | None = None
    permit_execution: bool = True
    pack_filename: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> HermesGoalConfig:
        e = os.environ if env is None else env
        grader = e.get("RELYABLE_HERMES_GOAL_GRADER")
        if not grader:
            raise ValueError(
                "RELYABLE_HERMES_GOAL_GRADER is required: the consumer's trusted goal-"
                "completion grader is the gate's trust root and has no default."
            )
        ref = e.get("RELYABLE_HERMES_GOAL_REFERENCE") or None
        anchor = e.get("RELYABLE_HERMES_GOAL_REFERENCE_ANCHOR") or None
        pack = e.get("RELYABLE_HERMES_GOAL_PACK_FILENAME") or None
        no_run = e.get("RELYABLE_HERMES_GOAL_NO_RUN", "").strip().lower() in _TRUTHY
        return cls(
            grader_src=Path(grader),
            reference_path=Path(ref) if ref else None,
            reference_anchor=anchor,
            permit_execution=not no_run,
            pack_filename=pack,
        )
