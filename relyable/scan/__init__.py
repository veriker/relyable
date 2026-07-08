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

  exogenous        recompute from a declared relation / public spec — un-fakeable, narrow
  self_spec        re-run the author's OWN committed oracle — drift-catcher, broad
  cold_golden      third-party golden inferred from docs — weakest, broad
  non_rederivable  nothing checkable — honest floor, never a fabricated pass

WIRING (v2, 2026-07-08; every ungraded path records its degrade reason in the
payload, never silently):
  - ``exogenous``: a declared ``rederive.json`` PROPERTY manifest (idempotence /
    round_trip — ``relyable.skills.exogenous_manifest``) is GRADED: relyable
    computes both sides of the relation from the skill's own code; every PASS is
    mutation-tested (VACUOUS is never a pass). ``spec``-style manifests are
    detected + reported, not graded here.
  - ``self_spec``: fully wired (``relyable.skills.self_spec``: S-A shipped
    suite > S-B documented I/O examples > S-C paired fixtures).
  - ``cold_golden``: wired via ``relyable.skills.cold_golden`` when an LLM key
    is present (``RELYABLE_LLM_API_KEY`` / ``ANTHROPIC_API_KEY`` /
    ``OPENAI_API_KEY``; key PRESENCE only is ever reported). The constructor is
    code-blind by construction (SKILL.md + tool filenames only); a cold
    DIVERGED is UNCONFIRMED evidence, never an accusation. Weakest tier: the
    author can still fake it.

EXECUTION IS FAIL-CLOSED across ALL lanes: without an explicit
``allow_host_exec`` ack (the harness's sandbox is the intended acker), untrusted
skill code is never run — self_spec tools report ``UNJUDGEABLE_NO_SANDBOX``, and
the exogenous/cold lanes degrade with an explicit no-ack reason. Skill code that
does run gets a SCRUBBED environment (``relyable.skills._exec_env``): an
env-dumping skill cannot exfiltrate API keys into the evidence artifact.

Schema note: additive v2 — same ``relyable-scan-v1`` shape; the declared grade
ladder is unchanged, the ``exogenous``/``coldGolden`` sub-blocks are new
optional fields.

Stdlib only.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from relyable.skills import cold_golden as _cg
from relyable.skills import exogenous_manifest as _exo
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

# Env keys whose PRESENCE (never value) marks the cold_golden lane as available.
_LLM_ENV_KEYS = _cg.LLM_ENV_KEYS

_HONESTY = {
    "unfakeableClaimReservedFor": GRADE_EXOGENOUS,
    "selfSpecMeaning": (
        "consistency with the author's own committed spec, not correctness"
    ),
    "coldGoldenMeaning": (
        "a code-blind model's inference from the author's prose; weakest tier — "
        "the author can still fake it, and a cold DIVERGED is unconfirmed "
        "evidence, never an accusation"
    ),
    "exogenousScope": (
        "property manifests (idempotence / round_trip) graded with mutation "
        "anti-vacuity; spec-ref manifests detected only"
    ),
    "securityAxis": (
        "not covered: this scanner is the functional-rederivation axis only; "
        "run alongside security scanners"
    ),
}

_NO_ACK = (
    "execution ack required (fail-closed): pass --allow-host-exec / run inside "
    "the harness sandbox"
)


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


def _skill_row(skill_dir: Path, **overrides) -> dict:
    row = {
        "skill": skill_dir.name,
        "path": str(skill_dir),
        "grade": GRADE_NON_REDERIVABLE,
        "selfSpecTier": "none",
        "verdict": VERDICT_OUT_OF_SCOPE,
        "tools": {},
        "attempted": [],
        "degradeReasons": {},
        "exogenousManifest": None,
        "exogenous": None,
        "coldGolden": None,
        "skipped": [],
        "mutation": None,
    }
    row.update(overrides)
    return row


_NO_LLM_KEY = (
    "no LLM key available (set RELYABLE_LLM_API_KEY / ANTHROPIC_API_KEY "
    "/ OPENAI_API_KEY to enable the cold lane)"
)


def _scan_skill(
    skill_dir: Path,
    *,
    allow_host_exec: bool,
    timeout: float,
    llm_call,
    llm_model: str,
    llm_unavailable_reason: str = _NO_LLM_KEY,
) -> dict:
    attempted: list[str] = []
    degrade: dict[str, str] = {}
    exogenous_block = None

    # ── exogenous — a declared property manifest is graded (strongest rung) ──
    attempted.append(GRADE_EXOGENOUS)
    manifest_name = next(
        (m for m in _exo.MANIFEST_NAMES if (skill_dir / m).is_file()), None
    )
    manifest, manifest_err = _exo.load_manifest(skill_dir)
    if manifest_name is None:
        degrade[GRADE_EXOGENOUS] = (
            "no rederive manifest (spec-ref or property) declared"
        )
    elif manifest is None:
        degrade[GRADE_EXOGENOUS] = manifest_err or "unreadable manifest"
    elif not allow_host_exec:
        degrade[GRADE_EXOGENOUS] = f"{manifest_name} declared; {_NO_ACK}"
    else:
        result = _exo.grade_manifest(skill_dir, manifest, timeout=timeout)
        block = asdict(result)
        if result.verdict in (_exo.VERDICT_PASS, _exo.VERDICT_DIVERGED):
            return _skill_row(
                skill_dir,
                grade=GRADE_EXOGENOUS,
                verdict=result.verdict,
                attempted=attempted,
                degradeReasons=degrade,
                exogenousManifest=manifest_name,
                exogenous=block,
            )
        degrade[GRADE_EXOGENOUS] = f"{manifest_name}: {result.detail}"
        # fall through with the graded block preserved as evidence
        exogenous_block = block

    # ── self_spec — the author's own committed oracle ──
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
        return _skill_row(
            skill_dir,
            skill=spec.skill,
            grade=GRADE_SELF_SPEC,
            selfSpecTier=spec.tier,
            verdict=_aggregate(tools),
            tools=tools,
            attempted=attempted,
            degradeReasons=degrade,
            exogenousManifest=manifest_name,
            exogenous=exogenous_block,
            skipped=list(result.skipped),
        )

    # ── cold_golden — description-conformance, code-blind (weakest rung) ──
    attempted.append(GRADE_COLD_GOLDEN)
    cold_block = None
    if llm_call is None:
        degrade[GRADE_COLD_GOLDEN] = llm_unavailable_reason
    elif not allow_host_exec:
        degrade[GRADE_COLD_GOLDEN] = _NO_ACK
    else:
        result = _cg.adjudicate_cold(
            skill_dir, llm_call=llm_call, model_label=llm_model
        )
        cold_block = asdict(result)
        if result.verdict in ("PASS", "DIVERGED"):
            return _skill_row(
                skill_dir,
                grade=GRADE_COLD_GOLDEN,
                verdict=result.verdict,
                attempted=attempted,
                degradeReasons=degrade,
                exogenousManifest=manifest_name,
                exogenous=exogenous_block,
                coldGolden=cold_block,
                skipped=list(spec.skipped),
            )
        degrade[GRADE_COLD_GOLDEN] = f"{result.verdict}: {result.detail}"

    # ── the honest floor ──
    return _skill_row(
        skill_dir,
        attempted=attempted,
        degradeReasons=degrade,
        exogenousManifest=manifest_name,
        exogenous=exogenous_block,
        coldGolden=cold_block,
        skipped=list(spec.skipped),
    )


def scan_target(
    target: str | Path,
    *,
    allow_host_exec: bool = False,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
    llm_call=None,
    no_llm: bool = False,
) -> dict:
    """Scan one harness target; return the ``relyable-scan-v1`` payload dict.

    ``llm_call`` overrides the env-resolved constructor client (tests inject a
    spy here); ``no_llm`` forces the cold lane off regardless of keys."""
    environ = os.environ if env is None else env
    model = ""
    unavailable = _NO_LLM_KEY
    if no_llm:
        llm_call = None
        unavailable = "cold lane disabled (--no-llm)"
    elif llm_call is None:
        llm_call, model = _cg.env_llm_call(environ)
    else:
        model = "injected"
    target_path = Path(target)
    skill_dirs, error = _discover_skill_dirs(target_path)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "axis": AXIS,
        "scanner": {"name": "relyable", "version": scanner_version()},
        "target": str(target),
        "allowHostExec": allow_host_exec,
        "llmLaneAvailable": (not no_llm)
        and (llm_call is not None or any(environ.get(k) for k in _LLM_ENV_KEYS)),
        "skills": [
            _scan_skill(
                d,
                allow_host_exec=allow_host_exec,
                timeout=timeout,
                llm_call=llm_call,
                llm_model=model,
                llm_unavailable_reason=unavailable,
            )
            for d in skill_dirs
        ],
        "honesty": dict(_HONESTY),
    }
    if error is not None:
        payload["error"] = error
    return payload
