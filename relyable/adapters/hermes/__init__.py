"""relyable.adapters.hermes — wire relyable into Hermes's admission + output edges.

A thin shim, no trust logic of its own. Four guards across the agent's edges, each a
DIRECT in-process call (Hermes is Python — relyable is a pip dependency it imports):

  * **skills (admission)** — ``rederive_skill_guard`` matches Hermes's
    ``_security_scan_skill`` chokepoint (``None`` => admit, error string => drop), so
    one call drops into ``tools/skill_manager_tool.py``; ``usable`` is the batch form.
    ``rederive_learned_skill_guard`` is the same-chokepoint variant for ``/learn``
    (#51506) skills, where the dir is a RAW ``SKILL.md`` tree, not a pre-built bundle:
    it packages the tree, lifting the self-authored ``## Verification`` section as an
    UNTRUSTED hint, then re-derives (see ``learn_guard.py`` + ``LEARN_INTEGRATION_SCOPE.md``).
  * **memory (recall)** — ``RelyableMemoryProvider`` gates auto-recall through the
    ``MemoryProvider`` ABC (only re-deriving notes injected).
  * **deliver (output)** — ``deliver_block_reason`` re-derives a turn's deliverable at
    ``finalize_turn`` (``None`` => deliver, reason string => suppress); the fix the
    pre-assistant-hook tickets (#26742/#22956/#16357) + runtime gate (#44637) ask for.
  * **goal (completion)** — ``goal_done`` re-derives a ``/goal``'s completion from
    evidence at ``evaluate_after_turn`` (True only when it re-derives); the #18421 fix.

    from relyable.adapters.hermes import HermesGuardConfig, rederive_skill_guard

    cfg = HermesGuardConfig.from_env()          # grader_src + permit_execution
    err = rederive_skill_guard(skill_dir, cfg)  # None => admit, str => Hermes drops it

See ``DISCOVERY.md`` (skills seam) and ``../../../DELIVER_EDGE_DISCOVERY.md`` (the
deliver + goal seams — file:line, SHA) and why output-edge integration is a source-
patch, not a plugin (Hermes has no pre-assistant hook).
"""

from __future__ import annotations

from .config import HermesDeliverConfig, HermesGoalConfig, HermesGuardConfig
from .deliver_guard import (
    DeliverVerdict,
    deliver_block_reason,
    rederive_deliverable,
)
from .goal_guard import (
    GoalVerdict,
    goal_done,
    rederive_goal_completion,
)
from .guard import (
    admission_reason,
    admit_registry,
    rederive_skill_guard,
    usable,
)
from .learn_guard import (
    package_learned_skill,
    parse_verification,
    rederive_learned_skill_guard,
)

__all__ = [
    "DeliverVerdict",
    "GoalVerdict",
    "HermesDeliverConfig",
    "HermesGoalConfig",
    "HermesGuardConfig",
    "admission_reason",
    "admit_registry",
    "deliver_block_reason",
    "goal_done",
    "package_learned_skill",
    "parse_verification",
    "rederive_deliverable",
    "rederive_goal_completion",
    "rederive_learned_skill_guard",
    "rederive_skill_guard",
    "usable",
]
