"""exogenous_manifest.py — grade a skill's DECLARED re-derivation manifest.

The exogenous rung of the ladder: the expected value is recomputed by relyable's
own code from a relation the author declared — the author NEVER gets a vote on
the expected value itself. This module grades the PROPERTY family of that rung
(metamorphic relations over a skill's CLI tool):

  idempotence   f(f(x)) == f(x)      run the tool, feed its output back in,
                                      require a fixed point
  round_trip    g(f(x)) == x          encode with ``tool``, decode with
                                      ``inverse_tool``, require the original

For both, relyable computes BOTH sides of the comparison by executing the
skill's real code on relyable-chosen composition — a wrong-but-plausible output
has no author-supplied "expected" to hide behind. What the author DOES supply
(the property kind, the tool, the sample inputs) cannot make a wrong skill pass
the relation; it can only make the check vacuous — which is why every PASS is
mutation-tested (``_cold_mutate``): a property no broken variant of the code can
fail asserts nothing, and reports VACUOUS instead of PASS.

THE MANIFEST (``rederive.json`` in the skill root):

    {
      "kind": "idempotence" | "round_trip",
      "tool": "scripts/normalize.py",        // entrypoint, relative to the skill
      "inverse_tool": "scripts/decode.py",   // round_trip only
      "inputs": [ {"stdin": "..."}, ... ]     // >= 1 sample inputs
    }

v2 SCOPE (recorded honestly in every degrade): tools must read stdin and write
stdout (the composable CLI shape); ``spec``/``spec-ref`` manifests — recompute
from a public spec document — are DETECTED but not graded here. Outputs are
normalized by trailing-newline strip only (disclosed; CRLF -> LF).

Execution is the caller's fail-closed decision: this module never runs code
unless the caller passed the disposable-host ack down to it. Subprocess env is
SCRUBBED (``_exec_env``) — property runs execute untrusted code.

Stdlib only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from relyable.skills._exec_env import scrubbed_env

try:
    from relyable.skills._cold_mutate import _MUTATIONS

    _MUTATE_AVAILABLE = True
except Exception:  # pragma: no cover - defensive
    _MUTATIONS = []
    _MUTATE_AVAILABLE = False

MANIFEST_NAMES = ("rederive.json", "rederive.yml", "rederive.yaml")
SUPPORTED_KINDS = ("idempotence", "round_trip")

VERDICT_PASS = "PASS"
VERDICT_DIVERGED = "DIVERGED"
VERDICT_UNJUDGEABLE = "UNJUDGEABLE"
VERDICT_VACUOUS = "VACUOUS"
VERDICT_UNSUPPORTED = "UNSUPPORTED"

_EXT_RUNNER = {
    ".py": [sys.executable],
    ".sh": ["sh"],
    ".js": ["node"],
    ".mjs": ["node"],
}


@dataclass(frozen=True, slots=True)
class ExogenousResult:
    """The graded outcome of one declared manifest.

    ``verdict``:
        PASS         — the declared relation held on every input, and at least
                       one source mutation broke it (non-vacuous)
        DIVERGED     — the relation FAILED on some input: the skill's own code,
                       composed by relyable, contradicts the author's declared
                       property
        VACUOUS      — the relation held, but survived every mutation — it
                       constrains nothing; never reported as a pass
        UNJUDGEABLE  — the tool errored/hung/was unrunnable on the declared inputs
        UNSUPPORTED  — a manifest kind this grader does not cover (spec-ref, ...)
    """

    verdict: str
    kind: str = ""
    detail: str = ""
    n_inputs: int = 0
    n_pass: int = 0
    n_fail: int = 0
    mutation_killrate: float | None = None


def load_manifest(skill_dir: Path) -> tuple[dict | None, str | None]:
    """Find and parse the manifest. Returns (manifest, error). YAML manifests
    are detected but reported unparsed (stdlib-only surface)."""
    for name in MANIFEST_NAMES:
        p = skill_dir / name
        if not p.is_file():
            continue
        if p.suffix != ".json":
            return (
                None,
                f"{name}: YAML manifests not parsed by this surface (use rederive.json)",
            )
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return None, f"{name}: unreadable manifest: {e}"
        if not isinstance(doc, dict):
            return None, f"{name}: manifest must be a JSON object"
        return doc, None
    return None, None


def _norm(s: str) -> str:
    return s.replace("\r\n", "\n").rstrip("\n")


def _run_tool(
    skill_dir: Path, tool_rel: str, stdin: str, timeout: float
) -> tuple[bool, str, str]:
    """Run one stdin->stdout tool invocation under the scrubbed env.
    Returns (ok, stdout, reason)."""
    ep = (skill_dir / tool_rel).resolve()
    if skill_dir.resolve() not in ep.parents or not ep.is_file():
        return False, "", f"tool not inside the skill: {tool_rel!r}"
    runner = _EXT_RUNNER.get(ep.suffix)
    if runner is None:
        return False, "", f"no runner for {ep.name}"
    try:
        proc = subprocess.run(
            runner + [str(ep)],
            input=stdin,
            text=True,
            capture_output=True,
            cwd=str(skill_dir),
            timeout=timeout,
            env=scrubbed_env(),
        )
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except (OSError, FileNotFoundError) as e:
        return False, "", f"runner unavailable: {e}"
    if proc.returncode != 0:
        return False, "", f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    return True, proc.stdout, ""


def _property_holds(
    skill_dir: Path, manifest: dict, timeout: float
) -> tuple[str, int, int, str]:
    """Check the declared relation on every input.
    Returns (verdict, n_pass, n_fail, detail) with verdict in
    PASS/DIVERGED/UNJUDGEABLE (mutation not yet applied)."""
    kind = manifest.get("kind")
    tool = manifest.get("tool") or ""
    inputs = manifest.get("inputs") or []
    if (
        not tool
        or not inputs
        or not all(
            isinstance(i, dict) and isinstance(i.get("stdin"), str) for i in inputs
        )
    ):
        return (
            VERDICT_UNJUDGEABLE,
            0,
            0,
            'manifest needs "tool" and >=1 inputs of the form {"stdin": "..."}',
        )
    n_pass = n_fail = 0
    for i, item in enumerate(inputs):
        x = item["stdin"]
        ok, y, reason = _run_tool(skill_dir, tool, x, timeout)
        if not ok:
            return VERDICT_UNJUDGEABLE, n_pass, n_fail, f"input {i}: {reason}"
        if kind == "idempotence":
            ok, z, reason = _run_tool(skill_dir, tool, y, timeout)
            if not ok:
                return (
                    VERDICT_UNJUDGEABLE,
                    n_pass,
                    n_fail,
                    f"input {i} (second application): {reason}",
                )
            held = _norm(z) == _norm(y)
        else:  # round_trip
            inverse = manifest.get("inverse_tool") or ""
            if not inverse:
                return (
                    VERDICT_UNJUDGEABLE,
                    n_pass,
                    n_fail,
                    'round_trip manifest needs "inverse_tool"',
                )
            ok, z, reason = _run_tool(skill_dir, inverse, y, timeout)
            if not ok:
                return (
                    VERDICT_UNJUDGEABLE,
                    n_pass,
                    n_fail,
                    f"input {i} (inverse): {reason}",
                )
            held = _norm(z) == _norm(x)
        if held:
            n_pass += 1
        else:
            n_fail += 1
    if n_fail:
        return (
            VERDICT_DIVERGED,
            n_pass,
            n_fail,
            f"declared {kind} relation FAILED on {n_fail}/{len(inputs)} input(s) — "
            "both sides computed by relyable from the skill's own code",
        )
    return VERDICT_PASS, n_pass, n_fail, ""


def _mutation_killrate(skill_dir: Path, manifest: dict, timeout: float) -> float | None:
    """Anti-vacuity: apply single source mutations to the declared tool(s); a
    mutant is killed when the property STOPS holding (fail or error). Returns
    killed/applicable, or None when no mutation applied."""
    if not _MUTATE_AVAILABLE:
        return None
    import re

    tools = [manifest.get("tool") or ""]
    if manifest.get("kind") == "round_trip":
        tools.append(manifest.get("inverse_tool") or "")
    applicable = killed = 0
    for rel in tools:
        ep = (skill_dir / rel).resolve()
        if skill_dir.resolve() not in ep.parents or not ep.is_file():
            continue
        original = ep.read_text(encoding="utf-8", errors="ignore")
        try:
            for _name, pat, repl in _MUTATIONS:
                mutated, n = re.subn(pat, repl, original, count=1)
                if n == 0 or mutated == original:
                    continue
                applicable += 1
                ep.write_text(mutated, encoding="utf-8")
                verdict, _p, _f, _d = _property_holds(skill_dir, manifest, timeout)
                if verdict != VERDICT_PASS:
                    killed += 1
        finally:
            ep.write_text(original, encoding="utf-8")  # always restore
    if applicable == 0:
        return None
    return killed / applicable


def grade_manifest(
    skill_dir: Path,
    manifest: dict,
    *,
    timeout: float = 30.0,
    do_mutate: bool = True,
) -> ExogenousResult:
    """Grade one declared manifest. The caller has already made the fail-closed
    execution decision — calling this function IS the ack."""
    kind = manifest.get("kind")
    if kind not in SUPPORTED_KINDS:
        return ExogenousResult(
            VERDICT_UNSUPPORTED,
            kind=str(kind),
            detail=(
                f"manifest kind {kind!r} not graded by this surface "
                f"(supported: {', '.join(SUPPORTED_KINDS)}); detected only"
            ),
        )
    inputs = manifest.get("inputs") or []
    verdict, n_pass, n_fail, detail = _property_holds(skill_dir, manifest, timeout)
    if verdict != VERDICT_PASS:
        return ExogenousResult(
            verdict,
            kind=kind,
            detail=detail,
            n_inputs=len(inputs),
            n_pass=n_pass,
            n_fail=n_fail,
        )
    kr = _mutation_killrate(skill_dir, manifest, timeout) if do_mutate else None
    if kr is not None and kr == 0.0:
        return ExogenousResult(
            VERDICT_VACUOUS,
            kind=kind,
            detail=(
                f"declared {kind} relation held on {n_pass}/{len(inputs)} input(s) "
                "but survived every source mutation — the property constrains "
                "nothing; not a pass"
            ),
            n_inputs=len(inputs),
            n_pass=n_pass,
            n_fail=n_fail,
            mutation_killrate=kr,
        )
    return ExogenousResult(
        VERDICT_PASS,
        kind=kind,
        detail=(
            f"declared {kind} relation held on {n_pass}/{len(inputs)} input(s)"
            + (
                f", mutation kill={kr:.0%}"
                if kr is not None
                else ", mutation not applicable (no killrate; weaker signal, disclosed)"
            )
        ),
        n_inputs=len(inputs),
        n_pass=n_pass,
        n_fail=n_fail,
        mutation_killrate=kr,
    )
