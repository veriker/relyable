"""relyable.adapters.hermes — wire relyable.skills into Hermes skill admission.

A thin shim, no trust logic of its own. ``rederive_skill_guard`` matches the
return contract of Hermes's ``_security_scan_skill`` chokepoint (``None`` => admit,
error string => drop), so one call drops into ``tools/skill_manager_tool.py``; a
skill whose claimed verdict does not re-derive against the consumer's grader is
dropped, not warned. ``usable`` is the batch form exposing only the ADMIT skills.

    from relyable.adapters.hermes import HermesGuardConfig, rederive_skill_guard

    cfg = HermesGuardConfig.from_env()          # grader_src + permit_execution
    err = rederive_skill_guard(skill_dir, cfg)  # None => admit, str => Hermes drops it

See ``DISCOVERY.md`` for the exact seam (file:line, version) and why integration is
a source-patch, not a plugin (Hermes has no skill-lifecycle hook).
"""

from __future__ import annotations

from .config import HermesGuardConfig
from .guard import (
    admission_reason,
    admit_registry,
    rederive_skill_guard,
    usable,
)

__all__ = [
    "HermesGuardConfig",
    "admission_reason",
    "admit_registry",
    "rederive_skill_guard",
    "usable",
]
