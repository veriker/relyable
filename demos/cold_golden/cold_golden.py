#!/usr/bin/env python3
"""cold_golden.py — manufacture a re-derivation check for a skill that ships NO spec.

THE QUESTION THIS ANSWERS (distinct from ``self_spec``)
-------------------------------------------------------
``self_spec`` re-runs the **author's own** committed oracle (shipped tests / documented
examples). It is strong but rare — ~1% of live ClawHub skills ship any checkable spec.
This harness attacks the other ~99%: can relyable manufacture *some* re-derivation
coverage for a skill whose author committed no golden?

The mechanism Max proposed:

    1. A COLD agent (fresh context, direct API) reads ONLY the skill's human-facing
       description (SKILL.md prose + the tool filenames) — never the implementation —
       and constructs NOVEL (input -> expected_output) goldens, OR ABSTAINS.
    2. The skill's actual code is then run on those inputs.
    3. A MECHANICAL compare (no LLM judge) decides PASS / FLAG.

WHAT THIS PROVES, AND WHAT IT DOES NOT (carried honestly into the output)
------------------------------------------------------------------------
* The golden is built from the DESCRIPTION, blind to the implementation. So it cannot
  inherit the implementation's bugs — that is real independence on the impl axis.
* But the anchor is the author's own *description*. So a PASS certifies
  DESCRIPTION-CONFORMANCE (the code does what its description says), NOT correctness:
  if description and code agree but are both wrong about the world, this passes green.
  This is consistency-vs-spec, not correctness — weaker grounding than an author
  golden, named as such, never sold as truth.
* It is NOT the self-verification illusion: the golden is byte-pinned BEFORE the code
  runs and the compare is deterministic. (relyable's re-derivation experiments:
  re-derivation recovers where self-verify recovers 0.00.)

THE TWO DISCIPLINES THAT KEEP IT FROM BEING THEATRE
---------------------------------------------------
* ABSTENTION IS FAIL-CLOSED. The constructor may say "this description does not
  determine behavior". An abstain is reported as a HOLE, never counted as a pass.
* ANTI-VACUITY. A golden that passes the real code AND survives mutation of that code
  proved nothing. Every PASS is mutation-tested; PASSes whose goldens do not kill any
  mutant are reported VACUOUS (see ``mutate.py``), not green.

Verdict taxonomy (per skill):
    OUT_OF_SCOPE  no executable entrypoint (prose-only skill) — nothing to re-derive.
    ABSTAIN       cold constructor could not pin behavior from the description.
    UNJUDGEABLE   constructed goldens but the tool errored / was non-deterministic.
    DIVERGED      tool output differed from a cold golden — UNCONFIRMED, never an
                  accusation: the expected bytes were inferred from prose, not pinned by
                  the author, so a divergence is as likely a format guess as a defect.
                  A real CONTRADICTS needs the author's own documented example (self_spec).
    PASS          tool reproduced every cold-constructed golden ...
    PASS_VACUOUS  ... but the goldens survived mutation, so the pass is not load-bearing.

Stdlib + the official ``anthropic`` SDK only. The API key is read from MASTER.env, the
same source relyable's experiment harnesses use. The constructor is a DIRECT API call with a neutral
system prompt — never the local CLI/Agent tool, so no CLAUDE.md policy contaminates the
cold context (the experiment-harness direct-API rule).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from relyable.adapters._skillpack import (  # noqa: E402
    OutOfScope,
    enumerate_tools,
    parse_frontmatter,
)

# Reuse the demo's own lightweight source mutator.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutate  # noqa: E402

_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"


def _key_file_candidates() -> list[Path]:
    """Optional local env-file fallbacks. The ANTHROPIC_API_KEY env var is the
    primary source; this is only a convenience for local runs. Honors
    $ANTHROPIC_API_KEY_FILE, then a home-relative default."""
    import os

    cands: list[Path] = []
    override = os.environ.get("ANTHROPIC_API_KEY_FILE")
    if override:
        cands.append(Path(override))
    cands.append(Path.home() / ".env" / "MASTER.env")
    return cands


# --- entrypoint runner (mirrors _skillpack._EXT_RUNNER) -----------------------------
_EXT_RUNNER = {
    ".py": [sys.executable],
    ".sh": ["sh"],
    ".js": ["node"],
    ".mjs": ["node"],
}


def _load_key() -> str:
    import os

    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env.strip()
    for p in _key_file_candidates():
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\s*ANTHROPIC_API_KEY\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("ANTHROPIC_API_KEY not found in MASTER.env")


# ------------------------------------------------------------------------------------
# The cold constructor: description-only -> goldens | abstain
# ------------------------------------------------------------------------------------

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


def _http_post(api_key: str, payload: dict) -> dict:
    import urllib.request

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _API_URL,
        data=data,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def construct_goldens(
    skill_md: str, tool_names: list[str], api_key: str, model: str
) -> dict:
    """One direct-API call. Returns the parsed constructor JSON (abstain or goldens)."""
    user = (
        "TOOL FILENAMES (you may invoke any of these):\n"
        + "\n".join(f"  - {t}" for t in tool_names)
        + "\n\n--- SKILL.md (documentation only; you cannot see the code) ---\n"
        + skill_md
    )
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": _CONSTRUCTOR_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
    resp = _http_post(api_key, payload)
    text = "".join(
        b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"
    )
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Parse the first complete JSON object; ignore any trailing prose the model
        # appended after it (raw_decode stops at the end of the first value).
        s = text.find("{")
        if s >= 0:
            return json.JSONDecoder().raw_decode(text, s)[0]
        raise


# ------------------------------------------------------------------------------------
# The runner + mechanical compare
# ------------------------------------------------------------------------------------


def _runner_for(entrypoint: str) -> list[str] | None:
    return _EXT_RUNNER.get(Path(entrypoint).suffix)


def _vacuous_by_construction(g: dict) -> bool:
    """True for goldens that pass ANY output regardless of the code.

    The dominant case: ``match='contains'`` with an empty (or whitespace) expected
    substring — ``'' in anything`` is always True. The constructor reaches for this
    when an output it cannot predict (a timestamp, a path) makes the bytes
    non-deterministic; the honest move there is to abstain, so we treat such a golden
    as no-golden rather than a pass.

    The format-tolerant predicate modes have their own trivial forms — an empty
    expected value, an empty json path, or a regex whose single capture group swallows
    everything (``(.*)``). These constrain nothing, so they are dropped here too, the
    same fail-closed posture as contains-empty. (The mutation gate is the deeper net;
    this is the cheap structural cut.)"""
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
        # A capture group that matches any text pins nothing: ``(.*)``, ``^(.+)$``, etc.
        if arg in {".*", ".+"} or re.fullmatch(r"\^?\(\.[*+]\??\)\$?", arg):
            return True
    return False


def _json_path(doc, path: str):
    """Walk a dotted path over a parsed JSON document. Returns (found, value).

    Dict keys by name; list elements by integer index. Any miss => (False, None)."""
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


def _compare(
    expected: str, actual: str, match: str, match_arg: str | None = None
) -> bool:
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
        # The docs pin a value but not its surrounding wrapper (e.g. a version tool
        # documents "v2.0.0" but prints "tool version: v2.0.0"). Check the final
        # whitespace-delimited token only.
        toks = actual.split()
        return bool(toks) and toks[-1] == expected.strip()
    if match == "json-field-equals":
        # The docs pin one JSON field's value but not the whole document shape.
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
        # Interpret the expected literal as JSON when it parses (so a documented
        # numeric/boolean field compares by value), else compare its string form.
        try:
            want = json.loads(expected)
        except (json.JSONDecodeError, ValueError):
            return str(value) == expected
        return value == want
    if match == "regex-capture-equals":
        # The docs pin a value embedded in unpinned surrounding text; the constructor
        # supplies a regex with exactly ONE capture group isolating that value.
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


_INTERPRETERS = {"python", "python3", "py", "node", "nodejs", "sh", "bash"}


def _sanitize_argv(argv: list[str], ep: Path) -> list[str]:
    """Drop a leading interpreter/script prefix the model sometimes bakes into argv.

    The runner already prepends ``[interpreter, entrypoint]``; a constructor that
    emits ``["python", "pick.py", ".name"]`` would otherwise pass "python"/"pick.py"
    as positional ARGS to the script. Strip any leading tokens that are a known
    interpreter or that name this entrypoint (basename, with or without a dir)."""
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


@dataclass
class GoldenResult:
    note: str
    tool: str
    ok: bool
    reason: str = ""
    expected: str = ""
    actual: str = ""


def run_golden(
    skill_dir: Path,
    g: dict,
    entrypoints: dict[str, Path],
    mask_cwd: bool = False,
    capture_file: str | None = None,
) -> GoldenResult:
    tool = g.get("tool", "")
    note = g.get("note", "")
    ep = entrypoints.get(tool) or entrypoints.get(Path(tool).name)
    if ep is None:
        return GoldenResult(note, tool, False, reason=f"unknown tool {tool!r}")
    runner = _runner_for(ep.name)
    if runner is None:
        return GoldenResult(note, tool, False, reason=f"no runner for {ep.name}")
    with tempfile.TemporaryDirectory(prefix="cold-golden-") as td:
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
            return GoldenResult(
                note, tool, False, reason="timeout (non-deterministic/hung)"
            )
        except FileNotFoundError as e:
            return GoldenResult(note, tool, False, reason=f"runner missing: {e}")
        out = proc.stdout
        if mask_cwd:
            # Tools that echo their absolute working directory embed a per-run tempdir
            # path, which defeats output-to-output comparison. Replace it with a constant
            # so the run-specific noise cancels (used by the metamorphic checker).
            out = out.replace(str(work), "<CWD>")
        if proc.returncode != 0:
            return GoldenResult(
                note,
                tool,
                False,
                reason=f"exit {proc.returncode}: {proc.stderr.strip()[:200]}",
                expected=g.get("expected_stdout", ""),
                actual=out,
            )
        if capture_file is not None:
            # The tool writes its result to a named OUTPUT FILE (argv), not stdout
            # (e.g. flatten.py in.json out.json). Read that file's bytes from the
            # tempdir before it is torn down; this is the value the caller compares.
            fp = work / capture_file
            if not fp.exists():
                return GoldenResult(
                    note,
                    tool,
                    False,
                    reason=f"output file {capture_file!r} not written",
                    actual=out,
                )
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
            note,
            tool,
            ok,
            reason="" if ok else "stdout did not match expected",
            expected=g.get("expected_stdout", ""),
            actual=out,
        )


def run_capture(
    skill_dir: Path,
    spec: dict,
    entrypoints: dict[str, Path],
    output_file: str | None = None,
) -> tuple[bool, str, str]:
    """Run a tool on an input spec and CAPTURE its result (no comparison).

    Returns (ok, result, reason). Used by the metamorphic checker, which compares one
    tool output to ANOTHER (format cancels) rather than to a literal. ``spec`` carries
    the same {tool, files, argv, stdin} shape as a golden. By default ``result`` is
    stdout; pass ``output_file`` (a filename in argv) to capture a file the tool writes
    instead — needed for file-in/file-out tools (the round_trip relation's inverse)."""
    g = {
        "tool": spec.get("tool", ""),
        "files": spec.get("files"),
        "argv": spec.get("argv"),
        "stdin": spec.get("stdin"),
        "expected_stdout": "",
        "match": "contains",
    }  # contains-"" => never fails on mismatch
    r = run_golden(skill_dir, g, entrypoints, mask_cwd=True, capture_file=output_file)
    # run_golden flags non-zero exit / timeout via ok=False with a reason; a clean run
    # is ok=True (the contains-"" comparison is vacuously true) — we want the result.
    return (r.ok, r.actual, r.reason)


# ------------------------------------------------------------------------------------
# Per-skill orchestration
# ------------------------------------------------------------------------------------


@dataclass
class SkillVerdict:
    slug: str
    verdict: str  # OUT_OF_SCOPE | ABSTAIN | UNJUDGEABLE | FLAG | PASS | PASS_VACUOUS
    detail: str = ""
    n_goldens: int = 0
    n_pass: int = 0
    n_fail: int = 0
    n_error: int = 0
    mutation_killrate: float | None = None
    goldens: list = field(default_factory=list)


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


def adjudicate(
    skill_dir: Path, api_key: str, model: str, do_mutate: bool = True
) -> SkillVerdict:
    slug = skill_dir.name
    md_path = skill_dir / "SKILL.md"
    if not md_path.exists():
        return SkillVerdict(slug, "OUT_OF_SCOPE", "no SKILL.md")
    skill_md = md_path.read_text(encoding="utf-8", errors="ignore")
    try:
        entrypoints = _entrypoints(skill_dir)
    except OutOfScope as e:
        return SkillVerdict(slug, "OUT_OF_SCOPE", e.reason_code)

    tool_names = sorted({Path(p).name for p in entrypoints})
    runnable = [t for t in tool_names if _runner_for(t)]
    if not runnable:
        return SkillVerdict(slug, "OUT_OF_SCOPE", "no python/sh/node entrypoint")

    try:
        constructed = construct_goldens(skill_md, runnable, api_key, model)
    except (json.JSONDecodeError, ValueError):
        # The constructor emitted malformed JSON. That is a transient formatting
        # glitch, not a judgement — fail closed to ABSTAIN, never a fabricated pass.
        return SkillVerdict(slug, "ABSTAIN", "constructor emitted unparseable JSON")
    if constructed.get("abstain") or not constructed.get("goldens"):
        return SkillVerdict(slug, "ABSTAIN", constructed.get("reason", "no goldens"))

    # Structural anti-vacuity: drop goldens that are always-true by construction
    # (the constructor's cop-out for non-deterministic output — e.g. a timestamped
    # report it cannot predict, so it sets expected="" with a substring match). These
    # would pass any code and prove nothing; they must not reach a PASS.
    goldens = [g for g in constructed["goldens"] if not _vacuous_by_construction(g)]
    n_dropped = len(constructed["goldens"]) - len(goldens)
    if not goldens:
        return SkillVerdict(
            slug,
            "ABSTAIN",
            f"all {n_dropped} constructed golden(s) were vacuous-by-construction "
            "(empty/substring expectation — output not deterministically pinned)",
        )
    results = [run_golden(skill_dir, g, entrypoints) for g in goldens]
    n_pass = sum(1 for r in results if r.ok)
    n_error = sum(1 for r in results if not r.ok and "did not match" not in r.reason)
    n_fail = sum(1 for r in results if not r.ok and "did not match" in r.reason)

    sv = SkillVerdict(
        slug,
        "PASS",
        n_goldens=len(goldens),
        n_pass=n_pass,
        n_fail=n_fail,
        n_error=n_error,
        goldens=[asdict(r) for r in results],
    )
    if n_fail > 0:
        # A divergence from a COLD-INFERRED golden is NOT a publishable contradiction.
        # The expected bytes were inferred from prose, not pinned by the author, so an
        # apparent mismatch is just as likely a format guess (bare-vs-labeled output,
        # stdout-vs-stderr, table layout) as a real defect — observed empirically: every
        # divergence on the addressable slice was correct logic in a format the docs
        # never pinned. relyable's rail holds: the only thing we ever call a CONTRADICTS
        # is the author's OWN documented example (that is self_spec's job). So this is a
        # non-accusatory review signal, never a fabricated "broken".
        sv.verdict = "DIVERGED"
        sv.detail = (
            f"{n_fail} cold golden(s) diverged — UNCONFIRMED (expected bytes were "
            "inferred from docs, not author-pinned; likely a format guess). Review, "
            "do not accuse."
        )
        return sv
    if n_pass == 0:
        sv.verdict = "UNJUDGEABLE"
        sv.detail = f"all {len(goldens)} goldens errored (non-det / bad invocation)"
        return sv

    # PASS path: anti-vacuity. Only the goldens that actually passed are load-bearing.
    sv.detail = f"{n_pass}/{len(goldens)} cold goldens reproduced"
    if do_mutate:
        passing = [g for g, r in zip(goldens, results) if r.ok]
        kr = mutate.mutation_killrate(skill_dir, passing, entrypoints, run_golden)
        sv.mutation_killrate = kr
        if kr is not None and kr == 0.0:
            sv.verdict = "PASS_VACUOUS"
            sv.detail += (
                " — but goldens survived every mutation (vacuous, not load-bearing)"
            )
    return sv


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "skills_dir",
        type=Path,
        help="directory of installed skills (e.g. ~/.openclaw/skills)",
    )
    ap.add_argument("--only", nargs="*", help="restrict to these slugs")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument(
        "--no-mutate", action="store_true", help="skip the anti-vacuity mutation pass"
    )
    ap.add_argument("--json", dest="as_json", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    api_key = _load_key()
    skill_dirs = sorted(d for d in args.skills_dir.iterdir() if d.is_dir())
    if args.only:
        want = set(args.only)
        skill_dirs = [d for d in skill_dirs if d.name in want]

    verdicts: list[SkillVerdict] = []
    for d in skill_dirs:
        try:
            sv = adjudicate(d, api_key, args.model, do_mutate=not args.no_mutate)
        except Exception as e:  # never let one bad skill abort the sweep
            sv = SkillVerdict(
                d.name, "UNJUDGEABLE", f"harness error: {type(e).__name__}: {e}"
            )
        verdicts.append(sv)
        km = (
            "" if sv.mutation_killrate is None else f"  kill={sv.mutation_killrate:.0%}"
        )
        print(f"  {sv.verdict:13} {sv.slug:28} {sv.detail}{km}", file=sys.stderr)

    counts: dict[str, int] = {}
    for sv in verdicts:
        counts[sv.verdict] = counts.get(sv.verdict, 0) + 1
    summary = {
        "skills_dir": str(args.skills_dir),
        "model": args.model,
        "n_skills": len(verdicts),
        "counts": counts,
        "verdicts": [asdict(sv) for sv in verdicts],
    }
    print("\n== cold-golden coverage ==", file=sys.stderr)
    for k in [
        "PASS",
        "PASS_VACUOUS",
        "DIVERGED",
        "ABSTAIN",
        "UNJUDGEABLE",
        "OUT_OF_SCOPE",
    ]:
        if counts.get(k):
            print(f"  {k:13} {counts[k]}", file=sys.stderr)

    blob = json.dumps(summary, indent=2)
    if args.out:
        args.out.write_text(blob)
        print(f"\n[wrote {args.out}]", file=sys.stderr)
    if args.as_json:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
