"""fake_hermes.py — a FAITHFUL reconstruction of the Hermes skill-write contract.

This is NOT a mock that hides schema drift: it reproduces, byte-for-byte, the
documented control flow of Hermes's ``tools/skill_manager_tool.py::_create_skill``
rollback path (see ``relyable/adapters/hermes/DISCOVERY.md`` for the pinned source).
The point is to drive the real adapter guard through the real harness contract
without needing a live Hermes install or API key — the only substitution is the
harness shell, and it is kept identical to the upstream code:

    scan_error = _security_scan_skill(skill_dir)   # our guard plugs in here
    if scan_error:
        shutil.rmtree(skill_dir, ignore_errors=True)   # DROP, not warn
        return {"success": False, "error": scan_error}
    return {"success": True}

If Hermes changes that contract, this fixture must change with it — that is the
intended coupling (the fixture is the contract, pinned in DISCOVERY.md).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

# The guard signature Hermes's _security_scan_skill expects: skill_dir -> error|None
SkillScan = Callable[[Path], "str | None"]


def create_skill(skill_dir: Path, scan: SkillScan) -> dict:
    """Reconstruct Hermes ``_create_skill``'s post-write admission step.

    ``skill_dir`` is assumed already written (Hermes atomically writes the skill
    before scanning). ``scan`` is the guard occupying ``_security_scan_skill``'s
    slot. On a non-empty return the skill directory is rolled back (rmtree) and a
    failure dict is returned, exactly as upstream does.
    """
    scan_error = scan(skill_dir)
    if scan_error:
        shutil.rmtree(skill_dir, ignore_errors=True)
        return {"success": False, "error": scan_error}
    return {"success": True}
