"""relyable.scan — the scanner-harness surface: graded functional-axis EVIDENCE.

Built for meta-scanner harnesses (first consumer: openclaw/clawscan) that run many
scanners over a native skill directory and preserve each scanner's raw JSON
verbatim. This surface emits EVIDENCE, not policy: no exit-code gating on
findings, no drop/admit decision — that stays in the gate surfaces
(``relyable-skills admit``, ``relyable-installpolicy``). Evidence-first mirrors
the harness's own invariant ("scanners produce evidence, they are deliberately
not a policy engine").

The payload is the FUNCTIONAL-REDERIVATION axis only — "does the skill do what
it claims, recomputed?" — never the security axis. ``axis`` is stamped into the
schema so no downstream consumer can misread a functional verdict as a malware
verdict. Run alongside security scanners, never instead.

## The grade ladder (ordered by "could the author make this pass while wrong?")

  exogenous        recompute from a public spec / math law — un-fakeable, narrow
  self_spec        re-run the author's OWN committed oracle — drift-catcher, broad
  cold_golden      third-party golden inferred from docs — weakest, broad
  non_rederivable  nothing checkable — honest floor, never a fabricated pass

v1 WIRING HONESTY (recorded in the payload, never silently):
  - ``self_spec`` is the fully wired lane (``relyable.skills.self_spec``:
    S-A shipped suite > S-B documented I/O examples > S-C paired fixtures).
  - ``exogenous`` is DETECTED (a ``rederive.json`` manifest declaring a property
    or spec-ref) but grading is not wired into scan yet — the ``relyable-skills
    prove`` surface certifies properties today; every skill records the degrade
    reason.
  - ``cold_golden`` is not wired into scan; availability of an LLM key is
    reported as a boolean (presence only, never the value).

EXECUTION IS FAIL-CLOSED, inherited from ``grade_self_spec``: without an explicit
``allow_host_exec`` ack (the harness's sandbox is the intended acker), untrusted
skill code is never run and every executable tool reports
``UNJUDGEABLE_NO_SANDBOX`` — honest evidence, not a fabricated verdict.

Stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path

from relyable.skills import self_spec as _ss

SCHEMA_VERSION = "relyable-scan-v1"
AXIS = "functional-rederivation"

GRADE_EXOGENOUS = "exogenous"
GRADE_SELF_SPEC = "self_spec"
GRADE_COLD_GOLDEN = "cold_golden"
GRADE_NON_REDERIVABLE = "non_rederivable"

# Aggregate per-skill verdicts (evidence vocabulary, aligned with the gate
# surfaces' taxonomy; CONTRADICTS at the tool level surfaces as DIVERGED).
VERDICT_PASS = "PASS"
VERDICT_DIVERGED = "DIVERGED"
VERDICT_UNJUDGEABLE = "UNJUDGEABLE"
VERDICT_OUT_OF_SCOPE = "OUT_OF_SCOPE"

# Exogenous declarations we look for (detection only in v1 — see module doc).
_EXOGENOUS_MANIFESTS = ("rederive.json", "rederive.yml", "rederive.yaml")

# Env keys whose PRESENCE (never value) marks the cold_golden lane as available.
_LLM_ENV_KEYS = ("RELYABLE_LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")

_NOT_WIRED_EXOGENOUS = (
    "exogenous lane not wired into scan v1; a declared manifest is reported "
    "but graded only by `relyable-skills prove`"
)
_NOT_WIRED_COLD_GOLDEN = "cold_golden lane not wired into scan v1"

_HONESTY = {
    "unfakeableClaimReservedFor": GRADE_EXOGENOUS,
    "selfSpecMeaning": (
        "consistency with the author's own committed spec, not correctness"
    ),
    "securityAxis": (
        "not covered: this scanner is the functional-rederivation axis only; "
        "run alongside security scanners"
    ),
}


def scanner_version() -> str:
    try:
        from importlib.metadata import version

        return version("relyable")
    except Exception:
        return "unknown"


def _discover_skill_dirs(target: Path) -> tuple[list[Path], str | None]:
    """Resolve a harness target (SKILL.md file, a skill dir, or a dir of skill
    dirs) into concrete skill directories. Returns (dirs, error)."""
    if target.is_file():
        return [target.parent], None
    if target.is_dir():
        if (target / "SKILL.md").is_file():
            return [target], None
        children = sorted(
            child
            for child in target.iterdir()
            if child.is_dir() and (child / "SKILL.md").is_file()
        )
        if children:
            return children, None
        return [], "no SKILL.md found in target or its immediate children"
    return [], "target does not exist"


def _aggregate(tools: dict[str, str]) -> str:
    verdicts = set(tools.values())
    if _ss.ToolVerdict.CONTRADICTS.value in verdicts:
        return VERDICT_DIVERGED
    if verdicts == {_ss.ToolVerdict.REPRODUCES.value}:
        return VERDICT_PASS
    return VERDICT_UNJUDGEABLE


def _scan_skill(skill_dir: Path, *, allow_host_exec: bool, timeout: float) -> dict:
    attempted: list[str] = []
    degrade: dict[str, str] = {}

    # exogenous — detection only in v1 (recorded, never silently skipped)
    attempted.append(GRADE_EXOGENOUS)
    manifest = next(
        (m for m in _EXOGENOUS_MANIFESTS if (skill_dir / m).is_file()), None
    )
    if manifest is None:
        degrade[GRADE_EXOGENOUS] = (
            "no rederive manifest (spec-ref or property) declared"
        )
    else:
        degrade[GRADE_EXOGENOUS] = f"{manifest} declared; {_NOT_WIRED_EXOGENOUS}"

    # self_spec — the wired lane
    attempted.append(GRADE_SELF_SPEC)
    spec = _ss.detect_self_spec(skill_dir)
    if spec.tier != "none":
        result = _ss.grade_self_spec(
            skill_dir,
            spec,
            allow_host_exec=allow_host_exec,
            timeout=timeout,
        )
        tools = {k: v.value for k, v in result.per_tool.items()}
        return {
            "skill": spec.skill,
            "path": str(skill_dir),
            "grade": GRADE_SELF_SPEC,
            "selfSpecTier": spec.tier,
            "verdict": _aggregate(tools),
            "tools": tools,
            "attempted": attempted,
            "degradeReasons": degrade,
            "exogenousManifest": manifest,
            "skipped": list(result.skipped),
            "mutation": None,
        }

    # cold_golden — not wired in v1; recorded honestly
    attempted.append(GRADE_COLD_GOLDEN)
    degrade[GRADE_COLD_GOLDEN] = _NOT_WIRED_COLD_GOLDEN

    return {
        "skill": skill_dir.name,
        "path": str(skill_dir),
        "grade": GRADE_NON_REDERIVABLE,
        "selfSpecTier": "none",
        "verdict": VERDICT_OUT_OF_SCOPE,
        "tools": {},
        "attempted": attempted,
        "degradeReasons": degrade,
        "exogenousManifest": manifest,
        "skipped": list(spec.skipped),
        "mutation": None,
    }


def scan_target(
    target: str | Path,
    *,
    allow_host_exec: bool = False,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> dict:
    """Scan one harness target; return the ``relyable-scan-v1`` payload dict."""
    environ = os.environ if env is None else env
    target_path = Path(target)
    skill_dirs, error = _discover_skill_dirs(target_path)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "axis": AXIS,
        "scanner": {"name": "relyable", "version": scanner_version()},
        "target": str(target),
        "allowHostExec": allow_host_exec,
        "llmLaneAvailable": any(environ.get(k) for k in _LLM_ENV_KEYS),
        "skills": [
            _scan_skill(d, allow_host_exec=allow_host_exec, timeout=timeout)
            for d in skill_dirs
        ],
        "honesty": dict(_HONESTY),
    }
    if error is not None:
        payload["error"] = error
    return payload
