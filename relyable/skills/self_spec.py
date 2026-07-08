"""self_spec.py — grade a marketplace skill against ITS OWN committed spec.

The directory funnel measured how much of a skills directory relyable can adjudicate
with CONSUMER-authored goldens and found ``K = 0``: zero tools auto-scaffold a trust
root, so every tool needs goldens the consumer writes. This module attacks a
different question — one that needs no consumer goldens at all:

    Does a skill still reproduce **the author's own committed spec**?

A skill that ships its own test suite, documented input/output examples, or example
fixtures already carries a standard the *author* committed to. relyable does not
invent a spec here — it locates the author's own oracle and re-runs it against the
authentic (ClawHub-``verify``-passing) bytes. The verdict is therefore
"agrees / disagrees with the **author's** standard", never "agrees with a spec we
made up". That is what makes a public statement defensible: the only thing we ever
call a contradiction is *the author's own test/example, run deterministically,
env-clean, from authentic bytes, disagreeing with the author's own code*.

This is the orthogonal axis to ClawHub ``verify``: ``verify`` answers "are these the
real author's bytes?" (provenance — and it answers it correctly); this asks "do
those bytes do what the author themselves documented?" (functional re-derivation).
Run alongside, never instead.

The self-spec ladder (strongest first — strength = how unambiguously it is the
author's committed contract, not our interpretation):

  S-A  shipped TEST SUITE (``tests/`` + a pytest layout). Detected via
       ``scaffold.detect_rung`` -> T1. The suite is the author's own executable
       assertions; relyable just runs it on the authentic bytes. Rare on ClawHub
       (this is the K=0 finding showing up again).
  S-B  documented I/O EXAMPLES — a shown command + its shown output, in a
       prompt-anchored (``$``/``>``) shell block of SKILL.md / README. The common
       case and the real yield of this pass.
  S-C  example FIXTURE files (``examples/`` / ``fixtures/``) pairing input+expected.

HONESTY RAILS (carried verbatim into every capture):
  - Re-derives the author's OWN oracle, NOT "correct" — the author's spec can be
    incomplete or wrong (the ``kills-mutants != correct-spec`` caveat).
  - Functional-conformance only; ClawHub ``verify`` is correct at its job (provenance).
  - Refusal is integrity: a spec we cannot extract unambiguously, a non-deterministic
    tool, or an environment failure is reported UNJUDGEABLE — never a fabricated pass
    AND never a fabricated "broken". The four conditions that gate a publishable
    CONTRADICTS map onto the verdict taxonomy below.
  - No LLM-judge anywhere. The extracted goldens are byte-pinned into the grader
    (the SpecAnchor pattern): authority supplied by the trusted side, never selected
    by the producer.

The S-B extraction is deliberately CONSERVATIVE — it emits a golden only when both
the invocation and its expected output are present and unambiguously paired, and the
inputs are materializable; everything else is dropped to ``skipped`` with a reason.
It under-extracts on purpose: a missed example costs a number, a mis-extracted one
costs a false accusation.

Stdlib only (auditor-independence), like the rest of ``relyable.skills``.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from relyable.adapters._skillpack import Invocation
    from relyable.verdicts.sandbox import Sandbox

# Runner -> argv prefix. Matches _skillpack.RUNNERS / the worked graders.
_RUNNER_CMD = {
    "python": [sys.executable],
    "python3": [sys.executable],
    "py": [sys.executable],
    "node": ["node"],
    "sh": ["sh"],
    "bash": ["bash"],
}

# Shell tokens that introduce a runner (the entrypoint is the *next* script token).
_RUNNER_TOKENS = frozenset({"python", "python3", "py", "node", "sh", "bash", "./"})

# Output markers that mean "the author elided part of the output" — we cannot do an
# exact compare against a truncated golden, so we drop the cell.
_TRUNCATION = ("...", "…", "<snip>", "[truncated]", "[...]", "# ...")

# stderr signatures that mean the failure is the ENVIRONMENT, not the tool's
# behaviour — these make a run UNJUDGEABLE_ENV, never CONTRADICTS.
_ENV_SIGNALS = (
    "ModuleNotFoundError",
    "No module named",
    "ImportError",
    "ConnectionError",
    "ConnectionRefused",
    "Name or service not known",
    "Temporary failure in name resolution",
    "URLError",
    "urlopen error",
    "gaierror",
    "command not found",
    "No such file or directory: 'node'",
    "No such file or directory: 'sh'",
    "Permission denied",
)

_PROMPT_RE = re.compile(r"^\s*[$>]\s+(.*\S)\s*$")
# Data-file extensions that, if a bare argv token carries one and we have no
# content for it, mean the example is unmaterializable (we'd be guessing the input).
_DATA_EXTS = (".json", ".csv", ".txt", ".yaml", ".yml", ".jsonl", ".xml", ".toml")
_SHELL_LANGS = frozenset(
    {"", "sh", "bash", "shell", "console", "text", "sh-session", "shell-session", "zsh"}
)


class ToolVerdict(str, Enum):
    """Per-tool outcome of grading against the author's own spec. CONTRADICTS is the
    only publishable "fail" — and only after the determinism + env gates pass."""

    REPRODUCES = "REPRODUCES"  # clean run reproduced the author's own oracle
    CONTRADICTS = "CONTRADICTS"  # clean, deterministic, env-clean — and disagrees
    UNJUDGEABLE_NO_SPEC = "UNJUDGEABLE_NO_SPEC"
    UNJUDGEABLE_NONDET = "UNJUDGEABLE_NONDET"
    UNJUDGEABLE_ENV = "UNJUDGEABLE_ENV"
    UNJUDGEABLE_UNPARSE = "UNJUDGEABLE_UNPARSE"
    # Execution of the (untrusted) skill was REFUSED because no isolation was
    # authorized — neither an explicit allow_host_exec ack nor a container sandbox.
    # Fail-closed: we never silently run untrusted marketplace code on the bare host.
    UNJUDGEABLE_NO_SANDBOX = "UNJUDGEABLE_NO_SANDBOX"


@dataclass(frozen=True, slots=True)
class Golden:
    """One extracted (input -> expected-output) cell, sourced from the author's own
    docs/fixtures. ``read`` is "stdout" in v1 (file-output examples are skipped — we
    cannot reliably tell an output-path arg from an input-path arg)."""

    kind: str  # "<slug>:<tool-stem>"
    tool: str  # entrypoint path relative to the skill dir
    runner: str
    inputs: dict[str, str]  # rel-name -> content, materialized into a temp cwd
    stdin: str | None
    argv: list[str]
    read: str  # "stdout"
    expected: str
    source: str  # provenance, e.g. "SKILL.md:L40"


@dataclass(frozen=True, slots=True)
class SelfSpec:
    """What ``detect_self_spec`` concluded for one skill. ``goldens`` is empty for
    S-A (the suite is the oracle) and for "none" (no self-spec found). ``skipped`` is
    the fail-closed log of examples we declined to extract, with reasons."""

    skill: str
    tier: str  # "S-A" | "S-B" | "S-C" | "none"
    goldens: list[Golden]
    suite_cmd: list[str] | None
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def _read_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _invocations(skill_dir: Path) -> list["Invocation"]:
    """Enumerate the skill's tools, or [] for a prose skill (no executable oracle)."""
    from relyable.adapters._skillpack import (
        OutOfScope,
        enumerate_tools,
        parse_frontmatter,
    )

    fm = parse_frontmatter(_read_md(skill_dir / "SKILL.md"))
    try:
        return enumerate_tools(skill_dir, fm)
    except OutOfScope:
        return []


def _slug_of(skill_dir: Path) -> str:
    from relyable.adapters._skillpack import _slug, parse_frontmatter

    fm = parse_frontmatter(_read_md(skill_dir / "SKILL.md"))
    return _slug(str(fm.get("name") or skill_dir.name))


def _detect_suite(skill_dir: Path, invs: list["Invocation"]) -> list[str] | None:
    """S-A: the author shipped a pytest suite covering the skill. Reuses
    ``scaffold.detect_rung`` (T1) on the first python tool; returns the suite command
    or None."""
    from .scaffold import detect_rung

    py = next((i for i in invs if i.runner in ("python", "python3", "py")), None)
    if py is None:
        return None
    det = detect_rung(skill_dir / py.entrypoint, project_root=skill_dir)
    if det.rung == "T1":
        return list(det.params["test_cmd"])
    return None


def detect_self_spec(
    skill_dir: Path, *, invocations: list["Invocation"] | None = None
) -> SelfSpec:
    """Find the author's own committed spec for ``skill_dir`` and extract it into
    byte-pinnable goldens. Priority S-A (suite) > S-B (doc examples) > S-C (fixtures);
    returns tier="none" with the accumulated skip log when nothing extractable is
    found."""
    skill = skill_dir.name
    invs = invocations if invocations is not None else _invocations(skill_dir)
    slug = _slug_of(skill_dir)
    skipped: list[str] = []

    if invs:
        suite = _detect_suite(skill_dir, invs)
        if suite is not None:
            return SelfSpec(skill, "S-A", [], suite, skipped)

    md = _read_md(skill_dir / "SKILL.md")
    for extra in ("README.md", "readme.md", "README"):
        p = skill_dir / extra
        if p.is_file():
            md += "\n\n" + _read_md(p)

    g_b, sk_b = _extract_doc_examples(md, invs, slug)
    if g_b:
        return SelfSpec(skill, "S-B", g_b, None, skipped + sk_b)

    g_c, sk_c = _pair_fixture_files(skill_dir, invs, slug)
    if g_c:
        return SelfSpec(skill, "S-C", g_c, None, skipped + sk_b + sk_c)

    return SelfSpec(skill, "none", [], None, skipped + sk_b + sk_c)


# ---------------------------------------------------------------------------
# S-B: documented I/O examples (the conservative parser)
# ---------------------------------------------------------------------------


def _fenced_blocks(md: str) -> list[tuple[str, list[str], int]]:
    """Return (lang, body_lines, first_body_line_no) for each ``` fenced block."""
    out: list[tuple[str, list[str], int]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*```+\s*([\w-]*)\s*$", lines[i])
        if not m:
            i += 1
            continue
        lang = m.group(1).lower()
        body: list[str] = []
        start = i + 2  # 1-based line number of the first body line
        i += 1
        while i < len(lines) and not re.match(r"^\s*```+\s*$", lines[i]):
            body.append(lines[i])
            i += 1
        out.append((lang, body, start))
        i += 1
    return out


def _labeled_files(md: str) -> dict[str, str]:
    """Map filename -> content for fenced blocks whose immediately-preceding non-blank
    line labels them with a filename (``**in.json**``, `` `in.json` ``, ``in.json:``,
    ``File: in.json``). Used to materialize an example's input when the author shows
    the file alongside the command."""
    files: dict[str, str] = {}
    lines = md.splitlines()
    blocks = _fenced_blocks(md)
    name_re = re.compile(r"([\w./-]+\.(?:json|csv|txt|yaml|yml|jsonl|xml|toml))")
    for _lang, body, start in blocks:
        # the label is the nearest non-blank line above the opening fence (start-2)
        j = start - 3  # 0-based index of line just above the fence line
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            continue
        label = lines[j].strip().strip("*`#").strip()
        m = name_re.search(label)
        # only treat as a file label when the line is essentially just the name
        if m and len(label) <= len(m.group(1)) + 2:
            files[m.group(1).split("/")[-1]] = "\n".join(body)
    return files


def _command_output_pairs(body: list[str]) -> list[tuple[str, str]]:
    """Within one shell block, pair each prompt-anchored command (``$``/``>``) with
    the output lines that follow it (until the next prompt or block end). Blocks with
    no prompt line yield nothing (a bare command with no shown output is not gradable)."""
    pairs: list[tuple[str, str]] = []
    cur_cmd: str | None = None
    cur_out: list[str] = []
    for ln in body:
        m = _PROMPT_RE.match(ln)
        if m:
            if cur_cmd is not None:
                pairs.append((cur_cmd, "\n".join(cur_out)))
            cur_cmd = m.group(1)
            cur_out = []
        elif cur_cmd is not None:
            cur_out.append(ln)
    if cur_cmd is not None:
        pairs.append((cur_cmd, "\n".join(cur_out)))
    return pairs


def _split_top_pipe(cmd: str) -> list[str]:
    """Split a command on top-level ``|`` (ignoring pipes inside quotes)."""
    parts, cur, quote = [], [], None
    for ch in cmd:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch == "|":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _stdin_from_pipe(stage: str, files: dict[str, str]) -> str | None | object:
    """Resolve the stdin a leading pipe stage produces. Supports ``echo``/``printf``
    of a literal and ``cat <known-file>``. Returns the text, or _UNSUPPORTED if the
    source is something we cannot reproduce (so the caller drops the cell)."""
    try:
        toks = shlex.split(stage)
    except ValueError:
        return _UNSUPPORTED
    if not toks:
        return _UNSUPPORTED
    if toks[0] in ("echo", "printf"):
        # join the literal operands (drop flags like -n/-e); echo adds no trailing \n
        operands = [t for t in toks[1:] if not t.startswith("-")]
        return " ".join(operands)
    if toks[0] == "cat" and len(toks) == 2 and toks[1].split("/")[-1] in files:
        return files[toks[1].split("/")[-1]]
    return _UNSUPPORTED


_UNSUPPORTED = object()


def _find_entrypoint(
    toks: list[str], tool_by_token: dict[str, "Invocation"]
) -> tuple[int, "Invocation"] | None:
    """Locate the tool entrypoint in a token list: skip leading ``VAR=val`` env
    assignments and runner tokens, then match a token whose basename/stem is a known
    tool. Returns (index, Invocation) or None."""
    i = 0
    while i < len(toks) and (
        "=" in toks[i]
        and not toks[i].startswith("-")
        and "/" not in toks[i].split("=")[0]
    ):
        i += 1  # env assignment prefix
    # optional runner word
    if i < len(toks) and toks[i] in _RUNNER_TOKENS:
        i += 1
    for j in range(i, len(toks)):
        base = toks[j].split("/")[-1]
        stem = base[:-3] if base.endswith((".py", ".sh", ".js")) else base
        inv = tool_by_token.get(base) or tool_by_token.get(stem)
        if inv is not None:
            return j, inv
    return None


def _extract_doc_examples(
    md: str, invs: list["Invocation"], slug: str
) -> tuple[list[Golden], list[str]]:
    """Extract S-B goldens from documented examples. Fail-closed: a cell is emitted
    only when the tool is known, the inputs are materializable, the output is shown,
    non-empty, and not truncated. Everything else is appended to ``skipped``."""
    goldens: list[Golden] = []
    skipped: list[str] = []
    if not invs:
        return goldens, skipped
    tool_by_token: dict[str, "Invocation"] = {}
    for inv in invs:
        base = Path(inv.entrypoint).name
        tool_by_token[base] = inv
        tool_by_token[Path(inv.entrypoint).stem] = inv
    files = _labeled_files(md)

    for lang, body, start in _fenced_blocks(md):
        if lang not in _SHELL_LANGS:
            continue
        for cmd, out in _command_output_pairs(body):
            res = _parse_command(cmd, tool_by_token, files)
            if isinstance(res, str):
                skipped.append(f"{slug} L{start}: {res}")
                continue
            inv, inputs, stdin, argv = res
            if not out.strip():
                skipped.append(f"{slug} L{start}: empty_output")
                continue
            if any(t in out for t in _TRUNCATION):
                skipped.append(f"{slug} L{start}: truncated_output")
                continue
            stem = Path(inv.entrypoint).stem
            goldens.append(
                Golden(
                    kind=f"{slug}:{stem}",
                    tool=inv.entrypoint,
                    runner=inv.runner,
                    inputs=inputs,
                    stdin=stdin,
                    argv=argv,
                    read="stdout",
                    expected=out,
                    source=f"L{start}",
                )
            )
    return goldens, skipped


def _parse_command(
    cmd: str, tool_by_token: dict[str, "Invocation"], files: dict[str, str]
) -> tuple["Invocation", dict[str, str], str | None, list[str]] | str:
    """Parse one shell command into (Invocation, inputs, stdin, argv), or return a
    string skip-reason. v1 supports: an optional leading ``echo/printf/cat`` pipe
    (-> stdin), a known tool entrypoint, literal/flag argv, and argv file tokens that
    name a labeled file (-> inputs). Redirections, file-output args, and
    unmaterializable file tokens are refused."""
    stages = _split_top_pipe(cmd)
    stdin: str | None = None
    if len(stages) > 1:
        src = _stdin_from_pipe(stages[0], files)
        if src is _UNSUPPORTED:
            return "unsupported_pipe_source"
        stdin = src  # type: ignore[assignment]
    tool_stage = stages[-1]
    try:
        toks = shlex.split(tool_stage)
    except ValueError:
        return "unparseable_command"
    if not toks:
        return "empty_command"
    if any(t in (">", ">>", "<", "2>", "&>") for t in toks):
        return "redirection"
    found = _find_entrypoint(toks, tool_by_token)
    if found is None:
        return "no_known_tool"
    idx, inv = found
    raw_argv = toks[idx + 1 :]
    inputs: dict[str, str] = {}
    argv: list[str] = []
    for t in raw_argv:
        if t.startswith("-"):
            argv.append(t)
            continue
        base = t.split("/")[-1]
        if base in files:
            inputs[base] = files[base]
            argv.append(base)
            continue
        if "/" in t or t.lower().endswith(_DATA_EXTS):
            # looks like a path but we have no content -> can't materialize (and we
            # cannot tell an output-path from an input-path) -> refuse the cell.
            return f"unmaterializable_input:{base}"
        argv.append(t)
    return inv, inputs, stdin, argv


# ---------------------------------------------------------------------------
# S-C: example fixture files (conservative)
# ---------------------------------------------------------------------------


def _pair_fixture_files(
    skill_dir: Path, invs: list["Invocation"], slug: str
) -> tuple[list[Golden], list[str]]:
    """Pair ``X.in``/``X.out`` (and ``*.input``/``*.expected``) fixtures into stdin->
    stdout goldens. Conservative: only for a single-tool skill whose one tool is
    stdin-shaped (``input_mode == 'stdin'``) — otherwise the I/O wiring is a guess
    and a wrong guess would manufacture a false CONTRADICTS, so we refuse."""
    skipped: list[str] = []
    py_tools = [i for i in invs if i.runner in _RUNNER_CMD]
    if len(py_tools) != 1:
        if invs:
            skipped.append(f"{slug}: fixture_tool_ambiguous ({len(invs)} tools)")
        return [], skipped
    inv = py_tools[0]
    if getattr(inv, "input_mode", "stdin") != "stdin":
        skipped.append(f"{slug}: fixture_wiring_unknown (input_mode != stdin)")
        return [], skipped
    stem = Path(inv.entrypoint).stem
    goldens: list[Golden] = []
    for sub in ("examples", "fixtures", "samples", "tests/fixtures"):
        d = skill_dir / sub
        if not d.is_dir():
            continue
        for in_path in sorted(d.rglob("*")):
            if not in_path.is_file():
                continue
            out_path = _fixture_partner(in_path)
            if out_path is None or not out_path.is_file():
                continue
            goldens.append(
                Golden(
                    kind=f"{slug}:{stem}",
                    tool=inv.entrypoint,
                    runner=inv.runner,
                    inputs={},
                    stdin=_read_md(in_path),
                    argv=[],
                    read="stdout",
                    expected=_read_md(out_path),
                    source=f"{sub}/{in_path.name}",
                )
            )
    return goldens, skipped


def _fixture_partner(in_path: Path) -> Path | None:
    """The expected-output partner of an input fixture, by naming convention."""
    name = in_path.name
    for a, b in ((".in", ".out"), (".input", ".expected"), (".in.txt", ".out.txt")):
        if name.endswith(a):
            return in_path.with_name(name[: -len(a)] + b)
    if name.startswith("input"):
        return in_path.with_name("expected" + name[len("input") :])
    return None


# ---------------------------------------------------------------------------
# grader generation: byte-pin the extracted goldens (SpecAnchor pattern)
# ---------------------------------------------------------------------------

_GRADER_TEMPLATE = '''#!/usr/bin/env python3
"""SELF-SPEC grader (GENERATED by relyable.skills.self_spec).

The GOLDENS below were EXTRACTED from the skill author's OWN committed spec
(documented examples / fixtures) and are pinned HERE on the trusted side — never
bundle-supplied. A lying entrypoint cannot pass: it must actually reproduce the
author's own shown output. A kind with no goldens fails closed (no_goldens_for_kind),
never a fabricated pass. Per the auditor-independence contract: stdlib only, no
relyable/veriker import.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GOLDENS = {goldens!r}

_RUNNER_CMD = {{
    "python": [sys.executable],
    "python3": [sys.executable],
    "py": [sys.executable],
    "node": ["node"],
    "sh": ["sh"],
    "bash": ["bash"],
}}


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {{msg}}", file=sys.stderr)
    return 1


def _norm(s: str) -> str:
    return s.replace("\\r\\n", "\\n").rstrip("\\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    bundle = Path(ap.parse_args().bundle_dir)
    try:
        meta = json.loads((bundle / "skill" / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"meta_unreadable: {{e}}")

    kind = meta.get("kind")
    cells = GOLDENS.get(kind)
    if not cells:
        return _fail(f"no_goldens_for_kind: {{kind!r}}")

    inv = meta.get("invocation") or {{}}
    entrypoint = inv.get("entrypoint")
    runner = inv.get("runner")
    if not entrypoint or runner not in _RUNNER_CMD:
        return _fail(f"bad_invocation: entrypoint={{entrypoint!r}} runner={{runner!r}}")
    ep_path = (bundle / "skill" / entrypoint).resolve()
    if (bundle / "skill").resolve() not in ep_path.parents or not ep_path.is_file():
        return _fail(f"entrypoint_not_in_bundle: {{entrypoint!r}}")
    cmd = _RUNNER_CMD[runner] + [str(ep_path)]

    for i, cell in enumerate(cells):
        with tempfile.TemporaryDirectory(prefix="self-spec-grader-") as td:
            cwd = Path(td)
            for rel, text in cell.get("inputs", {{}}).items():
                (cwd / rel).write_text(text, encoding="utf-8")
            try:
                res = subprocess.run(
                    cmd + list(cell.get("argv", [])),
                    input=cell.get("stdin"),
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return _fail(f"cell{{i}}: timeout")
            except OSError as e:
                return _fail(f"cell{{i}}: runner_unavailable: {{e}}")
            if res.returncode != 0:
                return _fail(f"cell{{i}}: entrypoint_exit_{{res.returncode}}: {{res.stderr[:200]}}")
            read = cell.get("read", "stdout")
            if read == "stdout":
                got = res.stdout
            else:
                f = cwd / read
                if not f.is_file():
                    return _fail(f"cell{{i}}: tool wrote no output file {{read!r}}")
                got = f.read_text(encoding="utf-8")
            if _norm(got) != _norm(cell["expected"]):
                return _fail(f"cell{{i}}: mismatch (got {{got[:120]!r}})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def make_self_spec_grader(goldens_by_kind: dict[str, list[dict]]) -> str:
    """Emit a stdlib-only grader source with ``goldens_by_kind`` byte-pinned in it.
    Each cell is a dict {inputs, stdin, argv, read, expected}. ``repr`` keeps the
    embedded literal valid Python (handles None / newlines / quotes)."""
    return _GRADER_TEMPLATE.format(goldens=goldens_by_kind)


def cells_for_kind(goldens: list[Golden]) -> dict[str, list[dict]]:
    """Group ``Golden`` objects by kind into the grader's cell dict shape."""
    out: dict[str, list[dict]] = {}
    for g in goldens:
        out.setdefault(g.kind, []).append(
            {
                "inputs": g.inputs,
                "stdin": g.stdin,
                "argv": g.argv,
                "read": g.read,
                "expected": g.expected,
            }
        )
    return out


# ---------------------------------------------------------------------------
# grading: determinism + env preflight, then the gate-routed re-derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillResult:
    """The graded outcome for one skill. ``per_tool`` maps each tool's kind to its
    ``ToolVerdict``; ``tier`` and ``skipped`` carry the detection context."""

    skill: str
    tier: str
    per_tool: dict[str, ToolVerdict]
    skipped: list[str]


def _is_env_failure(stderr: str) -> bool:
    return any(sig in stderr for sig in _ENV_SIGNALS)


def _run_tool_once(
    skill_dir: Path, golden: Golden, timeout: float
) -> tuple[int, str, str] | None:
    """Run the tool on one golden's inputs from the AUTHENTIC bytes, in a throwaway
    cwd. Returns (exit, stdout, stderr) or None on timeout. The entrypoint is invoked
    by ABSOLUTE path so a tool that imports a sibling module keeps resolving it."""
    runner = _RUNNER_CMD.get(golden.runner)
    if runner is None:
        return (127, "", f"runner_unavailable: {golden.runner}")
    ep = (skill_dir / golden.tool).resolve()
    if not ep.is_file():
        return (127, "", f"entrypoint_missing: {golden.tool}")
    with tempfile.TemporaryDirectory(prefix="self-spec-pre-") as td:
        cwd = Path(td)
        for rel, text in golden.inputs.items():
            (cwd / rel).write_text(text, encoding="utf-8")
        try:
            res = subprocess.run(
                runner + [str(ep)] + list(golden.argv),
                input=golden.stdin,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None
        except OSError as e:
            return (127, "", f"runner_unavailable: {e}")
        return (res.returncode, res.stdout, res.stderr)


def _preflight(
    skill_dir: Path, goldens: list[Golden], runs: int, timeout: float
) -> ToolVerdict | None:
    """The two gates the binary admit/reject verdict cannot express. Returns
    UNJUDGEABLE_ENV / UNJUDGEABLE_NONDET if a gate trips, else None (proceed to the
    gate run). A non-env, non-zero exit is NOT a gate trip — it is left for the gate
    to adjudicate as a genuine contradiction of the author's shown behaviour."""
    for golden in goldens:
        outs: list[str] = []
        for _ in range(max(1, runs)):
            r = _run_tool_once(skill_dir, golden, timeout)
            if r is None:
                return ToolVerdict.UNJUDGEABLE_ENV  # timeout = environment
            code, out, err = r
            if code != 0 and _is_env_failure(err):
                return ToolVerdict.UNJUDGEABLE_ENV
            if code == 0:
                outs.append(out)
        if len(outs) > 1 and len(set(outs)) > 1:
            return ToolVerdict.UNJUDGEABLE_NONDET
    return None


def _gate_verdict(
    skill_dir: Path,
    kind: str,
    goldens: list[Golden],
    permit_execution: bool,
    timeout: float,
    sandbox: Sandbox | None = None,
) -> ToolVerdict:
    """Route the per-tool re-derivation through ``relyable.skills.gate.rederive`` with
    the extracted goldens byte-pinned into the grader, then map the AdmissionVerdict
    to a self-spec ToolVerdict. ``sandbox`` (opt-in) runs the gate's re-derivation
    worker behind that isolation boundary (e.g. ``ContainerSandbox`` with network
    off); None keeps the in-process default."""
    from relyable.adapters._skillpack import pack_native_tool_bundles
    from relyable.skills.gate import ADMIT, rederive

    inv = next((g for g in goldens), None)
    if inv is None:
        return ToolVerdict.UNJUDGEABLE_NO_SPEC
    grader_text = make_self_spec_grader(cells_for_kind(goldens))
    with tempfile.TemporaryDirectory(prefix="self-spec-gate-") as td:
        root = Path(td)
        grader_path = root / "self_spec_grader.py"
        grader_path.write_text(grader_text, encoding="utf-8")
        # Pack ONLY this tool's bundle, keyed to the kind the grader expects.
        from relyable.adapters._skillpack import (
            Invocation,
            enumerate_tools,
            parse_frontmatter,
        )

        fm = parse_frontmatter(_read_md(skill_dir / "SKILL.md"))
        target = next(
            (i for i in enumerate_tools(skill_dir, fm) if i.entrypoint == inv.tool),
            Invocation(entrypoint=inv.tool, runner=inv.runner),
        )
        bundles = pack_native_tool_bundles(
            skill_dir,
            root / "bundles",
            grader_src=grader_path,
            kind_for=lambda _i: kind,
            invocations=[target],
        )
        bundle_dir = next(iter(bundles.values()))
        v = rederive(
            bundle_dir,
            grader_src=grader_path,
            permit_execution=permit_execution,
            sandbox=sandbox,
        )

    if v.verdict == ADMIT:
        return ToolVerdict.REPRODUCES
    if v.rederived_label == "REJECTED":
        # veriker actively re-derived and the bytes disagreed. Defensively re-check
        # for an env signature the preflight might not have surfaced.
        if _is_env_failure(v.detail):
            return ToolVerdict.UNJUDGEABLE_ENV
        return ToolVerdict.CONTRADICTS
    # UNVERIFIED: grader missing / permit_execution=False / verifier incomplete.
    return ToolVerdict.UNJUDGEABLE_ENV


def _run_suite(skill_dir: Path, suite_cmd: list[str], timeout: float) -> ToolVerdict:
    """S-A: run the author's OWN shipped suite against the authentic bytes. pytest
    exit codes: 0 ok -> REPRODUCES; 1 tests failed -> CONTRADICTS; 5 no tests ->
    NO_SPEC; anything else (collection/usage/internal error) -> ENV."""
    try:
        res = subprocess.run(
            suite_cmd,
            cwd=str(skill_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ToolVerdict.UNJUDGEABLE_ENV
    if res.returncode == 0:
        return ToolVerdict.REPRODUCES
    if res.returncode == 1 and not _is_env_failure(res.stdout + res.stderr):
        return ToolVerdict.CONTRADICTS
    if res.returncode == 5:
        return ToolVerdict.UNJUDGEABLE_NO_SPEC
    return ToolVerdict.UNJUDGEABLE_ENV


def grade_self_spec(
    skill_dir: Path,
    spec: SelfSpec | None = None,
    *,
    runs: int = 3,
    permit_execution: bool = True,
    timeout: float = 30.0,
    allow_host_exec: bool = False,
    sandbox: Sandbox | None = None,
) -> SkillResult:
    """Grade one skill against its own committed spec. Detects the spec if not given,
    then per tool: preflight (determinism + env gates) -> gate-routed re-derivation.
    S-A runs the author's suite directly (the suite IS the oracle — nothing to pin).

    EXECUTION IS FAIL-CLOSED. Grading runs the skill's (untrusted) code: the
    entrypoint lives outside any per-call mount, so it cannot be containerized
    per-call — the honest control is an explicit operator vow that the host is
    disposable. So unless ``allow_host_exec=True``, every executable tool is reported
    ``UNJUDGEABLE_NO_SANDBOX`` and NOTHING is run. ``sandbox`` (opt-in) additionally
    isolates the gate's re-derivation worker (e.g. ``ContainerSandbox`` w/ network
    off) — defense-in-depth on top of the ack, not a substitute for it."""
    if spec is None:
        spec = detect_self_spec(skill_dir)
    if spec.tier == "none":
        return SkillResult(
            spec.skill,
            "none",
            {"_skill": ToolVerdict.UNJUDGEABLE_NO_SPEC},
            spec.skipped,
        )

    # Fail-closed: refuse to execute untrusted skill code on the bare host unless the
    # operator has explicitly vouched the host is disposable/sandboxed. No silent ACE.
    if not allow_host_exec:
        key = "_suite" if spec.tier == "S-A" else None
        if key is not None:
            tools = {key: ToolVerdict.UNJUDGEABLE_NO_SANDBOX}
        else:
            kinds = {g.kind for g in spec.goldens} or {"_skill"}
            tools = {k: ToolVerdict.UNJUDGEABLE_NO_SANDBOX for k in kinds}
        return SkillResult(spec.skill, spec.tier, tools, spec.skipped)

    if spec.tier == "S-A":
        v = (
            _run_suite(skill_dir, spec.suite_cmd, timeout)
            if spec.suite_cmd
            else ToolVerdict.UNJUDGEABLE_NO_SPEC
        )
        return SkillResult(spec.skill, "S-A", {"_suite": v}, spec.skipped)

    per_tool: dict[str, ToolVerdict] = {}
    by_kind: dict[str, list[Golden]] = {}
    for g in spec.goldens:
        by_kind.setdefault(g.kind, []).append(g)
    for kind, goldens in by_kind.items():
        gate = _preflight(skill_dir, goldens, runs, timeout)
        if gate is not None:
            per_tool[kind] = gate
            continue
        per_tool[kind] = _gate_verdict(
            skill_dir, kind, goldens, permit_execution, timeout, sandbox
        )
    return SkillResult(spec.skill, spec.tier, per_tool, spec.skipped)
