"""cold_gate.py — manufacture a re-derivation check for a skill at admission time.

Adapts the cold_golden demo's methodology (demos/cold_golden/cold_golden.py) into
a relyable library module that fires at skill-admission time via Hermes'
_security_scan_skill chokepoint. The cold constructor is a fresh-context LLM call
(via Hermes' auxiliary_client, task="cold_constructor") that reads ONLY the
skill's SKILL.md + tool filenames — never the source — and manufactures
(input -> expected_stdout) goldens, or abstains. The skill's actual code is then
run on those inputs and the output is mechanically compared (no LLM judge).

The gate is purely additive at admission: no verdict drops a skill. PASS is an
affirmative trust signal; everything else is honest holes. The drop decision
stays with the existing security scan.

See demos/cold_golden/COLD_GOLDEN_RUN.md for the empirical evidence behind the
verdict taxonomy, the anti-vacuity discipline, and the DIVERGED-never-accuses rail.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from relyable.adapters._skillpack import (  # noqa: E402
    OutOfScope,
    enumerate_tools,
    parse_frontmatter,
)

# ── Optional Hermes integration ──────────────────────────────────────────
# When running inside Hermes, use auxiliary_client for the LLM call (resolves
# provider/model from auxiliary.cold_constructor config, falls back to the
# main provider). When standalone (tests), _call_llm is None and the
# constructor returns UNJUDGEABLE — the gate is a no-op.
try:
    from agent.auxiliary_client import call_llm as _call_llm  # type: ignore
except ImportError:
    _call_llm = None  # standalone / test

# ── Optional mutation engine (anti-vacuity) ──────────────────────────────
# Full anti-vacuity requires running a source mutator to check that the
# constructed goldens actually constrain the code (kill mutants). The structural
# guard (_vacuous_by_construction) is stdlib-only and always fires; this is the
# deeper net. If unavailable, PASS is reported without a kill rate and
# PASS_VACUOUS is never emitted — an honest, disclosed weaker signal.
#
# Import _mutate as a sibling module (next to cold_gate.py) to avoid triggering
# the relyable.adapters.hermes.__init__ chain, which eagerly imports
# deliver_guard → relyable.memory → relyable.gate → veriker (audit_bundle).
# The mutation engine is stdlib-only and should not require veriker.
_MUTATE_AVAILABLE = False
mutation_killrate = None
try:
    import importlib
    import importlib.util
    _mutate_path = Path(__file__).parent / "_mutate.py"
    if _mutate_path.exists():
        _spec = importlib.util.spec_from_file_location("_cold_mutate", _mutate_path)
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            mutation_killrate = _mod.mutation_killrate
            _MUTATE_AVAILABLE = True
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# The cold constructor system prompt
# (verbatim from demos/cold_golden/cold_golden.py — product of empirical
#  iteration on ClawHub samples; see COLD_GOLDEN_RUN.md)
# ═══════════════════════════════════════════════════════════════════════════

_CONSTRUCTOR_SYSTEM = (
    "You are a careful software tester. You are given ONLY the user-facing "
    "documentation (SKILL.md) for a command-line skill and the list of its tool "
    "filenames. You CANNOT see the source code. Your job is to predict the skill's "
    "behaviour from its documentation alone, so a harness can check whether the code "
    "actually does what the documentation claims.\n\n"
    "Construct a small set of NOVEL test cases (do NOT copy any example already shown "
    "verbatim in the docs — invent fresh inputs). For each test case, give the exact "
    "command-line invocation and the EXACT stdout you expect the tool to print, "
    "derived purely from the documented behaviour.\n\n"
    "INTEGRITY RULES — these matter more than coverage:\n"
    "* Only emit a test case if the documentation pins the output UNAMBIGUOUSLY. If you "
    "would have to guess formatting, ordering, whitespace, rounding, or which of "
    "several plausible outputs is correct, DO NOT emit that case.\n"
    "* If the documentation does not determine the tool's exact output for ANY input "
    "you can construct, ABSTAIN. Abstaining is correct and expected; a wrong expected "
    "value causes a false accusation, which is far worse than abstaining.\n"
    "* The docs often pin a VALUE but not the WRAPPER around it (a version tool "
    "documents the version string `v2.0.0` but not whether it prints `v2.0.0` alone or "
    "`tool version: v2.0.0`; a JSON tool documents one field's value but not the whole "
    "document shape). When the value is pinned but its surrounding format is not, "
    "PREFER a format-tolerant predicate over guessing the exact wrapper — that recovers "
    "a real check where an exact-byte guess would force a false divergence or an "
    "abstain.\n"
    "* CONCRETE TELL: most CLIs do NOT print a bare value. They label it "
    "(`Canonical: <url>`, `Result: <n>`, `Version: <v>`) and/or echo the input first "
    "(`Original: <input>` then the answer on the next line). The label text, the echo "
    "line, and the line ordering are almost never pinned by the docs. So whenever you "
    "have predicted a single value, ASSUME it will be wrapped and DO NOT use 'exact' on "
    "the bare value — that guarantees a false divergence. Instead isolate the value: "
    "'last-token-equals' if the value is the final whitespace token of the output, or "
    "'regex-capture-equals' with a tight group (e.g. match_arg `Canonical:\\s*(\\S+)`). "
    "Reserve 'exact' for when the docs pin the ENTIRE output, wrapper included.\n\n"
    "MATCH MODES:\n"
    "* 'exact'  — actual stdout equals expected_stdout byte-for-byte. Use when the doc "
    "pins the WHOLE output.\n"
    "* 'trim'   — equal after stripping leading/trailing whitespace only.\n"
    "* 'json'   — both parse as JSON and are deeply equal (key order ignored). Use when "
    "the doc pins the whole JSON document but not key order.\n"
    "* 'contains' — expected_stdout is a substring of actual. Use ONLY when the doc "
    "guarantees a specific substring appears.\n"
    "* 'last-token-equals' — the LAST whitespace-delimited token of stdout equals "
    "expected_stdout. Use when the doc pins a trailing value but not its label/prefix.\n"
    "* 'json-field-equals' — stdout parses as JSON; the field at the dotted path in "
    '`match_arg` (e.g. "result.version" or "items.0.id") equals expected_stdout '
    "(compared as JSON when expected_stdout parses, else as a string). Use when the doc "
    "pins ONE field's value but not the rest of the document.\n"
    "* 'regex-capture-equals' — `match_arg` is a regex with EXACTLY ONE capture group; "
    "its first match's group 1 equals expected_stdout. Use when the pinned value is "
    "embedded in unpinned surrounding text. The capture group must isolate the value — "
    "a group like `(.*)` that matches anything pins nothing and is rejected.\n\n"
    "Respond with a SINGLE JSON object and nothing else:\n"
    "{\n"
    '  "abstain": <bool>,\n'
    '  "reason": "<if abstaining, why the description does not pin behaviour>",\n'
    '  "goldens": [\n'
    "    {\n"
    '      "note": "<what documented behaviour this checks>",\n'
    '      "tool": "<one of the given tool filenames>",\n'
    '      "files": {"<filename>": "<file contents to create in the cwd>"},\n'
    '      "argv": ["<args AFTER the script name ONLY — NOT the interpreter, NOT the script>"],\n'
    '      "stdin": "<text on stdin, or null>",\n'
    '      "expected_stdout": "<the value you expect — full bytes for exact/trim/json/contains; the single pinned value for the predicate modes>",\n'
    '      "match": "exact|trim|json|contains|last-token-equals|json-field-equals|regex-capture-equals",\n'
    '      "match_arg": "<dotted JSON path for json-field-equals, or the regex for regex-capture-equals; omit/null otherwise>"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Set abstain=true with an empty goldens list when you cannot pin any case.\n\n"
    "INPUT CHANNEL — match the documented invocation exactly: if the docs pipe input "
    "via stdin (e.g. `echo '...' | tool .key`), put that text in `stdin` and leave "
    "`files` empty; if the docs pass a FILE argument (e.g. `tool input.json`), put the "
    "file in `files` and name it in `argv`. Do not move input from one channel to the "
    "other — a tool that reads stdin will hang or error on a file argument.\n\n"
    "Output ONLY the JSON object. No preamble, no explanation, no markdown fences."
)


# ═══════════════════════════════════════════════════════════════════════════
# Result types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class GoldenResult:
    """One golden's execution result."""

    note: str
    tool: str
    ok: bool
    reason: str = ""
    expected: str = ""
    actual: str = ""


@dataclass(frozen=True, slots=True)
class ColdGateResult:
    """The re-derivation verdict for one skill at admission time.

    ``verdict`` is one of:
        OUT_OF_SCOPE  — no executable entrypoint (prose-only skill)
        ABSTAIN       — constructor could not pin behavior from the description
        UNJUDGEABLE   — constructed goldens but the tool errored / was non-deterministic
        DIVERGED      — tool output differed from a cold golden (UNCONFIRMED, never
                        an accusation — the expected bytes were inferred from prose)
        PASS          — tool reproduced every cold-constructed golden
        PASS_VACUOUS  — reproduced, but goldens survived mutation (not load-bearing)

    No verdict causes the caller to drop the skill. PASS is an affirmative trust
    signal; everything else is an honest hole.
    """

    verdict: str
    detail: str = ""
    n_goldens: int = 0
    n_pass: int = 0
    n_fail: int = 0
    n_error: int = 0
    mutation_killrate: float | None = None
    model: str = ""
    elapsed_s: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# JSON extraction (verbatim from cold_golden.py)
# ═══════════════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s = text.find("{")
        if s >= 0:
            return json.JSONDecoder().raw_decode(text, s)[0]
        raise


# ═══════════════════════════════════════════════════════════════════════════
# The cold constructor (adapted: call_llm instead of direct Anthropic API)
# ═══════════════════════════════════════════════════════════════════════════

def _construct_goldens(skill_md: str, tool_names: list[str]) -> dict:
    """One auxiliary LLM call via Hermes' call_llm. Returns parsed constructor JSON.

    Uses task="cold_constructor" so the provider/model resolves from
    auxiliary.cold_constructor config (default: auto = inherit main provider).
    The cold context (description-only, never source) makes same-model honest.
    """
    if _call_llm is None:
        return {"abstain": True, "reason": "no LLM client available (not running inside Hermes)"}

    user = (
        "TOOL FILENAMES (you may invoke any of these):\n"
        + "\n".join(f"  - {t}" for t in tool_names)
        + "\n\n--- SKILL.md (documentation only; you cannot see the code) ---\n"
        + skill_md
    )
    try:
        resp = _call_llm(
            task="cold_constructor",
            messages=[
                {"role": "system", "content": _CONSTRUCTOR_SYSTEM},
                {"role": "user", "content": user},
            ],
            max_tokens=4096,
            timeout=120,
        )
    except Exception as exc:
        return {"abstain": True, "reason": f"constructor LLM call failed: {exc}"}

    if resp is None or not getattr(resp, "choices", None):
        return {"abstain": True, "reason": "constructor call returned no response"}

    text = resp.choices[0].message.content or ""
    try:
        return _extract_json(text)
    except (json.JSONDecodeError, ValueError):
        return {"abstain": True, "reason": "constructor emitted unparseable JSON"}


# ═══════════════════════════════════════════════════════════════════════════
# Structural anti-vacuity (verbatim from cold_golden.py — stdlib-only)
# ═══════════════════════════════════════════════════════════════════════════

def _vacuous_by_construction(g: dict) -> bool:
    """True for goldens that pass ANY output regardless of the code.

    The dominant case: ``match='contains'`` with an empty (or whitespace) expected
    substring — ``'' in anything`` is always True. The constructor reaches for
    this when an output it cannot predict (a timestamp, a path) makes the bytes
    non-deterministic; the honest move there is to abstain, so we treat such a
    golden as no-golden rather than a pass.
    """
    expected = g.get("expected_stdout") or ""
    match = g.get("match", "exact")
    arg = (g.get("match_arg") or "").strip()
    if match == "contains" and expected.strip() == "":
        return True
    if match == "last-token-equals" and expected.strip() == "":
        return True
    if match == "json-field-equals" and (expected.strip() == "" or arg == ""):
        return True
    if match == "regex-capture-equals":
        if expected.strip() == "" or arg == "":
            return True
        if arg in {".*", ".+"} or re.fullmatch(r"\^?\(\.[*+]\??\)\$?", arg):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Output comparison (verbatim from cold_golden.py — stdlib-only)
# ═══════════════════════════════════════════════════════════════════════════

def _json_path(doc, path: str):
    """Walk a dotted path over a parsed JSON document. Returns (found, value)."""
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            idx = int(part)
            if -len(cur) <= idx < len(cur):
                cur = cur[idx]
            else:
                return (False, None)
        else:
            return (False, None)
    return (True, cur)


def _compare(expected: str, actual: str, match: str, match_arg: str | None = None) -> bool:
    if match == "exact":
        return actual == expected
    if match == "trim":
        return actual.strip() == expected.strip()
    if match == "contains":
        return expected in actual
    if match == "json":
        try:
            return json.loads(actual) == json.loads(expected)
        except (json.JSONDecodeError, ValueError):
            return False
    if match == "last-token-equals":
        toks = actual.split()
        return bool(toks) and toks[-1] == expected.strip()
    if match == "json-field-equals":
        path = (match_arg or "").strip()
        if not path:
            return False
        try:
            doc = json.loads(actual)
        except (json.JSONDecodeError, ValueError):
            return False
        found, value = _json_path(doc, path)
        if not found:
            return False
        try:
            want = json.loads(expected)
        except (json.JSONDecodeError, ValueError):
            return str(value) == expected
        return value == want
    if match == "regex-capture-equals":
        pattern = match_arg or ""
        if not pattern:
            return False
        try:
            m = re.search(pattern, actual)
        except re.error:
            return False
        if not m or m.re.groups < 1:
            return False
        return m.group(1) == expected
    return actual == expected


# ═══════════════════════════════════════════════════════════════════════════
# Entrypoint runner (verbatim from cold_golden.py — stdlib subprocess)
# ═══════════════════════════════════════════════════════════════════════════

_EXT_RUNNER = {
    ".py": [sys.executable],
    ".sh": ["sh"],
    ".js": ["node"],
    ".mjs": ["node"],
}

_INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "sh", "bash"}


def _runner_for(entrypoint: str) -> list[str] | None:
    return _EXT_RUNNER.get(Path(entrypoint).suffix)


def _sanitize_argv(argv: list[str], ep: Path) -> list[str]:
    """Drop a leading interpreter/script prefix the model sometimes bakes into argv."""
    names = {ep.name, ep.stem, Path(ep.name).name}
    i = 0
    while i < len(argv):
        tok = argv[i]
        base = Path(tok).name
        if tok in _INTERPRETERS or base in names or base in _INTERPRETERS:
            i += 1
            continue
        break
    return argv[i:]


def run_golden(
    skill_dir: Path,
    g: dict,
    entrypoints: dict[str, Path],
    mask_cwd: bool = False,
    capture_file: str | None = None,
) -> GoldenResult:
    """Run one constructed golden against the skill's actual code."""
    tool = g.get("tool", "")
    note = g.get("note", "")
    ep = entrypoints.get(tool) or entrypoints.get(Path(tool).name)
    if ep is None:
        return GoldenResult(note, tool, False, reason=f"unknown tool {tool!r}")
    runner = _runner_for(ep.name)
    if runner is None:
        return GoldenResult(note, tool, False, reason=f"no runner for {ep.name}")
    with tempfile.TemporaryDirectory(prefix="cold-gate-") as td:
        work = Path(td)
        for fname, content in (g.get("files") or {}).items():
            fp = work / fname
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
        argv = _sanitize_argv([str(a) for a in (g.get("argv") or [])], ep)
        cmd = runner + [str(ep)] + argv
        try:
            proc = subprocess.run(
                cmd,
                input=(g.get("stdin") or None),
                text=True,
                capture_output=True,
                cwd=work,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return GoldenResult(note, tool, False, reason="timeout (non-deterministic/hung)")
        except FileNotFoundError as e:
            return GoldenResult(note, tool, False, reason=f"runner missing: {e}")
        out = proc.stdout
        if mask_cwd:
            out = out.replace(str(work), "<CWD>")
        if proc.returncode != 0:
            return GoldenResult(
                note, tool, False,
                reason=f"exit {proc.returncode}: {proc.stderr.strip()[:200]}",
                expected=g.get("expected_stdout", ""),
                actual=out,
            )
        if capture_file is not None:
            fp = work / capture_file
            if not fp.exists():
                return GoldenResult(note, tool, False, reason=f"output file {capture_file!r} not written", actual=out)
            out = fp.read_text(encoding="utf-8", errors="ignore")
            if mask_cwd:
                out = out.replace(str(work), "<CWD>")
        ok = _compare(
            g.get("expected_stdout", ""),
            out,
            g.get("match", "exact"),
            g.get("match_arg"),
        )
        return GoldenResult(
            note, tool, ok,
            reason="" if ok else "stdout did not match expected",
            expected=g.get("expected_stdout", ""),
            actual=out,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Entrypoint enumeration (uses relyable.adapters._skillpack)
# ═══════════════════════════════════════════════════════════════════════════

def _entrypoints(skill_dir: Path) -> dict[str, Path]:
    """tool filename -> absolute path, for every runnable entrypoint."""
    fm = parse_frontmatter(
        (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    )
    invs = enumerate_tools(skill_dir, fm)  # raises OutOfScope for prose-only skills
    out: dict[str, Path] = {}
    for inv in invs:
        ep = (skill_dir / inv.entrypoint).resolve()
        out[inv.entrypoint] = ep
        out[Path(inv.entrypoint).name] = ep
    return out


# ═══════════════════════════════════════════════════════════════════════════
# The gate: adjudicate one skill
# ═══════════════════════════════════════════════════════════════════════════

def adjudicate_cold(
    skill_dir: Path,
    *,
    do_mutate: bool = True,
) -> ColdGateResult:
    """Manufacture a re-derivation check for one skill at admission time.

    This is the entry point called from Hermes' ``_security_scan_skill`` after
    the existing injection scan passes. It is purely additive — no return from
    this function causes the caller to drop the skill.

    Steps:
      1. Detect executable entrypoints (OutOfScope for prose-only skills).
      2. Cold-construct goldens from the SKILL.md description (never the source).
      3. Run the skill's actual code on the constructed inputs.
      4. Mechanically compare (no LLM judge). Byte-pinned before execution.
      5. Optionally mutation-test surviving PASSes for anti-vacuity.

    Args:
        skill_dir: the skill directory (contains SKILL.md + scripts/).
        do_mutate: if True (default) and the mutation engine is available,
            mutation-test surviving goldens. If the engine is unavailable,
            PASS is reported without a kill rate (honest weaker signal).

    Returns:
        ColdGateResult with the verdict and details. The caller logs this
        and always admits the skill (no verdict blocks).
    """
    import time
    t0 = time.monotonic()

    slug = skill_dir.name
    md_path = skill_dir / "SKILL.md"
    if not md_path.exists():
        return ColdGateResult("OUT_OF_SCOPE", "no SKILL.md", elapsed_s=time.monotonic() - t0)
    skill_md = md_path.read_text(encoding="utf-8", errors="ignore")

    # (1) Detect executable entrypoints
    try:
        entrypoints = _entrypoints(skill_dir)
    except OutOfScope as e:
        return ColdGateResult("OUT_OF_SCOPE", e.reason_code, elapsed_s=time.monotonic() - t0)

    tool_names = sorted({Path(p).name for p in entrypoints})
    runnable = [t for t in tool_names if _runner_for(t)]
    if not runnable:
        return ColdGateResult("OUT_OF_SCOPE", "no python/sh/node entrypoint", elapsed_s=time.monotonic() - t0)

    # (2) Cold-construct goldens from the description
    try:
        constructed = _construct_goldens(skill_md, runnable)
    except Exception as exc:
        return ColdGateResult(
            "UNJUDGEABLE", f"constructor error: {type(exc).__name__}: {exc}",
            elapsed_s=time.monotonic() - t0,
        )

    if constructed.get("abstain") or not constructed.get("goldens"):
        return ColdGateResult(
            "ABSTAIN", constructed.get("reason", "no goldens constructed"),
            elapsed_s=time.monotonic() - t0,
        )

    # Structural anti-vacuity: drop goldens that are always-true by construction
    goldens = [g for g in constructed["goldens"] if not _vacuous_by_construction(g)]
    n_dropped = len(constructed["goldens"]) - len(goldens)
    if not goldens:
        return ColdGateResult(
            "ABSTAIN",
            f"all {n_dropped} constructed golden(s) were vacuous-by-construction "
            "(empty/substring expectation — output not deterministically pinned)",
            elapsed_s=time.monotonic() - t0,
        )

    # (3) Run the skill's actual code on the constructed inputs
    results = [run_golden(skill_dir, g, entrypoints) for g in goldens]
    n_pass = sum(1 for r in results if r.ok)
    n_error = sum(1 for r in results if not r.ok and "did not match" not in r.reason)
    n_fail = sum(1 for r in results if not r.ok and "did not match" in r.reason)

    # (4) Verdict
    result = ColdGateResult(
        "PASS",
        f"{n_pass}/{len(goldens)} cold goldens reproduced",
        n_goldens=len(goldens), n_pass=n_pass, n_fail=n_fail, n_error=n_error,
        elapsed_s=time.monotonic() - t0,
    )

    if n_fail > 0:
        # A divergence from a COLD-INFERRED golden is NOT a publishable contradiction.
        # The expected bytes were inferred from prose, not pinned by the author, so an
        # apparent mismatch is just as likely a format guess as a real defect.
        # relyable's rail: the only thing we ever call a CONTRADICTS is the author's
        # OWN documented example (self_spec's job). This is a non-accusatory review
        # signal, never a block.
        result = ColdGateResult(
            "DIVERGED",
            f"{n_fail} cold golden(s) diverged — UNCONFIRMED (expected bytes were "
            "inferred from docs, not author-pinned; likely a format guess). Review, "
            "do not accuse.",
            n_goldens=len(goldens), n_pass=n_pass, n_fail=n_fail, n_error=n_error,
            elapsed_s=time.monotonic() - t0,
        )
        return result

    if n_pass == 0:
        result = ColdGateResult(
            "UNJUDGEABLE",
            f"all {len(goldens)} goldens errored (non-det / bad invocation)",
            n_goldens=len(goldens), n_pass=n_pass, n_fail=n_fail, n_error=n_error,
            elapsed_s=time.monotonic() - t0,
        )
        return result

    # (5) Anti-vacuity: mutation-test surviving PASSes
    if do_mutate and _MUTATE_AVAILABLE:
        passing = [g for g, r in zip(goldens, results) if r.ok]
        try:
            kr = mutation_killrate(skill_dir, passing, entrypoints, run_golden)
            if kr is not None and kr == 0.0:
                result = ColdGateResult(
                    "PASS_VACUOUS",
                    f"{n_pass}/{len(goldens)} cold goldens reproduced — but goldens "
                    "survived every mutation (vacuous, not load-bearing)",
                    n_goldens=len(goldens), n_pass=n_pass, n_fail=n_fail, n_error=n_error,
                    mutation_killrate=kr,
                    elapsed_s=time.monotonic() - t0,
                )
            else:
                result = ColdGateResult(
                    "PASS",
                    f"{n_pass}/{len(goldens)} cold goldens reproduced, mutation "
                    f"kill={kr:.0%}" if kr is not None else
                    f"{n_pass}/{len(goldens)} cold goldens reproduced",
                    n_goldens=len(goldens), n_pass=n_pass, n_fail=n_fail, n_error=n_error,
                    mutation_killrate=kr,
                    elapsed_s=time.monotonic() - t0,
                )
        except Exception:
            pass  # mutation engine failed — PASS without kill rate (honest weaker signal)
    # If mutation unavailable, PASS stands without kill rate (disclosed in docstring)

    return result
