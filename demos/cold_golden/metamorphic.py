#!/usr/bin/env python3
"""metamorphic.py — engineer AROUND the doc-determinism wall with format-proof checks.

The addressable-slice run found that even on local-deterministic CLIs the exact-match
constructor abstains ~18/21: skill docs describe behaviour qualitatively but never pin
the exact OUTPUT BYTES, so a golden cannot be derived and a guessed format false-accuses
(see COLD_GOLDEN_RUN.md §3c). This module sidesteps the wall.

Instead of "predict the exact output", a COLD agent proposes a METAMORPHIC RELATION the
docs IMPLY — a relationship between the tool's own outputs that holds regardless of how
they are formatted:

  invariance   two inputs the docs say are equivalent must produce IDENTICAL output.
               e.g. a URL canonicalizer: f("HTTPS://Example.COM/") == f("https://example.com/").
  idempotence  running the tool on its own output reproduces that output.
               e.g. f(f(x)) == f(x) for any normalizer / canonicalizer / formatter.
  round_trip   a forward tool then its inverse returns the original input.
               e.g. inverse(forward(x)) == x for flatten/unflatten, encode/decode.

invariance and idempotence compare ONE tool output to ANOTHER, so the output FORMAT
cancels; round_trip compares the inverse's result to the original input (semantic JSON-
equality when both parse), so a reversible re-serialization still holds. In all three, no
literal
expected bytes are ever needed, and the doc-determinism wall does not apply. This is the
CLI/process-level analog of relyable's T2 PROVABLE_KINDS (idempotence / round_trip /
schema_conformance in relyable/skills/property_grader.py), lifted from the Python-function
level (import + call f(x)) to the black-box-CLI level (run the process, compare stdout).

WHAT THIS DELIVERS — and the divergence verdict it does NOT
-----------------------------------------------------------
The win is the POSITIVE verdict: `HOLDS`. Exact-match abstains on a skill whose docs
don't pin output bytes; metamorphic mode can still CONFIRM, format-free, that the skill
obeys the structural invariants its docs imply (host-lowercasing, param-sorting,
idempotence …), with anti-vacuity proving the relation actually constrains the code.
That is coverage exact-match cannot produce.

The divergence direction is the opposite story, and the addressable-slice run settled
it empirically: a metamorphic "violation" is NOT a safe accusation. Output-to-output
comparison is defeated by any run-specific noise the output embeds — the input echoed
back (`Original: <input>`), the absolute cwd/tempdir path, timestamps, PIDs. Two guards
were added (mask each run's own input strings; mask the cwd path), but the space of
embeddable noise is open-ended, and every divergence investigated was such an artifact
or a non-reproducible proposer fluke — none a real defect. So a divergence is reported
`DIVERGED` (review signal), NEVER an accusation. A confirmed contradiction needs the
author's own documented example — that is self_spec's job, not cold-golden's. Same rail
as exact-match mode: cold mechanisms map and confirm; they do not accuse.

ANTI-VACUITY
------------
A relation that holds on the real code AND survives every mutation of that code proved
nothing (e.g. a tool that ignores the input bytes A/B differ on is trivially invariant).
Each relation is mutation-tested with the same CLI source mutator as exact-match mode
(mutate._MUTATIONS): a relation is load-bearing iff some mutation makes it diverge/error.

Verdicts (per skill):
    OUT_OF_SCOPE   no executable entrypoint.
    ABSTAIN        proposer found no doc-implied relation it could pin (the common case).
    UNJUDGEABLE    proposed relations all errored (bad invocation / non-deterministic).
    DIVERGED       a doc-implied invariant diverged — UNCONFIRMED review signal, never an
                   accusation (run-specific output noise / proposer fluke, not a defect).
    HOLDS          every proposed relation holds AND >=1 is mutation-load-bearing. THE WIN.
    HOLDS_VACUOUS  relations hold but survive every mutation (not load-bearing).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import cold_golden as cg  # noqa: E402
import mutate  # noqa: E402

from relyable.adapters._skillpack import OutOfScope  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"

_PROPOSER_SYSTEM = (
    "You are a careful software tester. You are given ONLY the user-facing documentation "
    "(SKILL.md) for a command-line skill and its tool filenames. You CANNOT see the "
    "source code. Propose METAMORPHIC RELATIONS the documentation IMPLIES — relationships "
    "between the tool's own outputs that must hold no matter how the output is formatted. "
    "You never predict exact output bytes; you only assert that two runs relate.\n\n"
    "Relation kinds:\n"
    "* invariance — two DIFFERENT inputs that the docs say must yield the SAME output "
    "(e.g. a canonicalizer/normalizer given two equivalent forms; a case-insensitive "
    "tool given two casings). You provide input_a and input_b; the harness asserts "
    "output(a) == output(b).\n"
    "* idempotence — running the tool on its OWN output reproduces that output: "
    "f(f(x))==f(x). You provide one input x and say how the tool's output is fed back in "
    "(feedback: 'stdin' if the tool reads stdin, or 'argv-file:NAME' if it reads a file "
    "named NAME in argv). The harness runs x, then runs the result, asserting equality.\n"
    "* round_trip — a FORWARD tool followed by its INVERSE tool returns the original "
    "input: inverse(forward(x)) == x (encode/decode, flatten/unflatten, serialize/parse). "
    "The forward and inverse may be two different tool files OR the same file with a "
    "different flag (e.g. flatten.py x.json out.json, then flatten.py out.json back.json "
    "--unflatten). You provide the forward input x, where its result lands "
    "(forward_output: 'stdout' or 'argv-file:NAME'), which part of x is the payload that "
    "must come back (payload_channel: 'stdin' or 'argv-file:NAME'), and the inverse "
    "invocation (inverse_tool + its argv/files, how the forward output is fed to it "
    "(feedback: 'stdin' or 'argv-file:NAME'), and where the inverse writes its result "
    "(output: 'stdout' or 'argv-file:NAME')). The harness compares the inverse's result "
    "to the original payload (semantic JSON-equality when both parse as JSON, else "
    "bytes). ONLY propose round_trip when the docs explicitly call the pair reversible / "
    "round-trip-safe / lossless — a lossy transform (uppercasing, hashing) is NOT "
    "invertible and proposing it is a false accusation.\n\n"
    "INTEGRITY RULES — these matter more than coverage:\n"
    "* ONLY propose a relation the documentation genuinely implies, and quote the doc "
    "basis. Proposing idempotence for a tool not meant to be idempotent, or invariance "
    "for inputs the docs do NOT say are equivalent, is a FALSE ACCUSATION — worse than "
    "abstaining. If you are unsure the docs imply the relation, do not propose it.\n"
    "* For invariance, input_a and input_b MUST be inputs the docs explicitly or "
    "obviously make equivalent (same canonical form, same after normalization). They "
    "must differ in the dimension the tool is documented to normalize away.\n"
    "* If the documentation implies NO such relation you can pin, ABSTAIN.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "abstain": <bool>, "reason": "<if abstaining>",\n'
    '  "relations": [\n'
    "    {\n"
    '      "kind": "invariance|idempotence|round_trip",\n'
    '      "doc_basis": "<quote/paraphrase of the documented behaviour that implies this>",\n'
    '      "tool": "<the (forward) tool filename>",\n'
    '      "normalize": "none|trim",\n'
    "      // invariance: two equivalent inputs\n"
    '      "input_a": {"files": {}, "argv": [], "stdin": null},\n'
    '      "input_b": {"files": {}, "argv": [], "stdin": null},\n'
    "      // idempotence: one input + how output is fed back\n"
    '      "input": {"files": {}, "argv": [], "stdin": null},\n'
    '      "feedback": "stdin|argv-file:NAME",\n'
    "      // round_trip: forward input + inverse invocation\n"
    '      "forward_output": "stdout|argv-file:NAME",\n'
    '      "payload_channel": "stdin|argv-file:NAME",\n'
    '      "inverse_tool": "<inverse tool filename (may equal tool)>",\n'
    '      "inverse": {"argv": [], "files": {}, "stdin": null,\n'
    '                  "feedback": "stdin|argv-file:NAME", "output": "stdout|argv-file:NAME"}\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Omit the fields that do not apply to the kind. Output ONLY the JSON object."
)


def propose_relations(
    skill_md: str, tools: list[str], api_key: str, model: str
) -> dict:
    user = (
        "TOOL FILENAMES:\n"
        + "\n".join(f"  - {t}" for t in tools)
        + "\n\n--- SKILL.md (documentation only; you cannot see the code) ---\n"
        + skill_md
    )
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": _PROPOSER_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
    resp = cg._http_post(api_key, payload)
    text = "".join(
        b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"
    )
    return cg._extract_json(text)


def _norm(s: str, mode: str) -> str:
    return s.strip() if mode == "trim" else s


def _rt_equal(a: str, b: str, norm: str) -> bool:
    """Round-trip identity: byte-equal (after normalize) OR semantically JSON-equal.

    A reversible JSON tool may re-serialize with different key order / whitespace, so a
    flatten->unflatten that recovers the data can still differ byte-for-byte. Semantic
    JSON-equality is the honest identity for structured round-trips; the byte check
    covers non-JSON pairs (base64, etc.)."""
    if _norm(a, norm) == _norm(b, norm):
        return True
    try:
        return json.loads(a) == json.loads(b)
    except (json.JSONDecodeError, ValueError):
        return False


def _strip_echo(out: str, spec: dict) -> str:
    """Remove a run's OWN input strings from its output before an invariance compare.

    Many tools echo their input (``Original: <input>\\nCanonical: <result>``). Two
    equivalent-but-different inputs then yield different echoes even when the *result*
    is invariant — a false violation. Masking each run's literal argv/stdin/file bytes
    from its own output isolates the part that must actually be invariant. Biases toward
    HOLD (it can only remove differences, never add them) — the safe direction for an
    accusation; the anti-vacuity gate still requires the relation to kill mutants, so a
    relation made trivially-true by over-masking is caught as vacuous."""
    # FIRST occurrence only: the echo precedes the result, and an already-canonical
    # input equals its own result — stripping ALL occurrences would also delete the
    # result line for that input but not for an equivalent non-canonical one, manufacturing
    # a false difference. Removing just the leading echo keeps the result intact.
    for a in spec.get("argv") or []:
        if a:
            out = out.replace(str(a), "", 1)
    if spec.get("stdin"):
        out = out.replace(spec["stdin"], "", 1)
    for content in (spec.get("files") or {}).values():
        if content:
            out = out.replace(content, "", 1)
    return out


def check_relation(skill_dir: Path, rel: dict, entrypoints: dict) -> tuple[str, str]:
    """Return (status, detail). status in HOLD / VIOLATE / ERROR."""
    kind = rel.get("kind")
    norm = rel.get("normalize", "none")
    tool = rel.get("tool", "")
    if kind == "invariance":
        a = dict(rel.get("input_a") or {}, tool=tool)
        b = dict(rel.get("input_b") or {}, tool=tool)
        oka, sa, ra = cg.run_capture(skill_dir, a, entrypoints)
        okb, sb, rb = cg.run_capture(skill_dir, b, entrypoints)
        if not oka or not okb:
            return "ERROR", f"a:{ra[:60]} b:{rb[:60]}"
        ca, cb = _norm(_strip_echo(sa, a), norm), _norm(_strip_echo(sb, b), norm)
        return (
            ("HOLD", "")
            if ca == cb
            else (
                "VIOLATE",
                f"out(a)!=out(b) [echo-masked]: {ca[:40]!r} vs {cb[:40]!r}",
            )
        )
    if kind == "idempotence":
        x = dict(rel.get("input") or {}, tool=tool)
        ok1, o1, r1 = cg.run_capture(skill_dir, x, entrypoints)
        if not ok1:
            return "ERROR", r1[:80]
        fb = rel.get("feedback", "stdin")
        x2 = {
            "tool": tool,
            "files": dict(x.get("files") or {}),
            "argv": list(x.get("argv") or []),
            "stdin": x.get("stdin"),
        }
        o1n = _norm(o1, norm)
        if fb == "stdin":
            x2["stdin"] = o1
        elif fb.startswith("argv-file:"):
            fname = fb.split(":", 1)[1]
            x2["files"][fname] = o1
        else:
            return "ERROR", f"unknown feedback {fb!r}"
        ok2, o2, r2 = cg.run_capture(skill_dir, x2, entrypoints)
        if not ok2:
            return "ERROR", r2[:80]
        return (
            ("HOLD", "")
            if _norm(o2, norm) == o1n
            else ("VIOLATE", f"f(f(x))!=f(x): {o2[:40]!r} vs {o1n[:40]!r}")
        )
    if kind == "round_trip":
        inv_tool = rel.get("inverse_tool", "")
        if not inv_tool:
            return "ERROR", "round_trip missing inverse_tool"
        # 1. forward run on x; its result lands on stdout or in a named output file.
        fwd = dict(rel.get("input") or {}, tool=tool)
        fout = rel.get("forward_output", "stdout")
        fwd_file = fout.split(":", 1)[1] if fout.startswith("argv-file:") else None
        ok1, o1, r1 = cg.run_capture(skill_dir, fwd, entrypoints, output_file=fwd_file)
        if not ok1:
            return "ERROR", f"forward: {r1[:70]}"
        # 2. the payload that must survive the round-trip (what we compare against).
        pchan = rel.get("payload_channel", "stdin")
        if pchan == "stdin":
            payload = fwd.get("stdin")
        elif pchan.startswith("argv-file:"):
            payload = (fwd.get("files") or {}).get(pchan.split(":", 1)[1])
        else:
            return "ERROR", f"unknown payload_channel {pchan!r}"
        if payload is None:
            return "ERROR", f"no payload in channel {pchan!r}"
        # 3. inverse run, fed the forward output; its result is the round-tripped value.
        ispec = rel.get("inverse") or {}
        inv = {
            "tool": inv_tool,
            "files": dict(ispec.get("files") or {}),
            "argv": list(ispec.get("argv") or []),
            "stdin": ispec.get("stdin"),
        }
        fb = ispec.get("feedback", "stdin")
        if fb == "stdin":
            inv["stdin"] = o1
        elif fb.startswith("argv-file:"):
            inv["files"][fb.split(":", 1)[1]] = o1
        else:
            return "ERROR", f"unknown inverse feedback {fb!r}"
        iout = ispec.get("output", "stdout")
        inv_file = iout.split(":", 1)[1] if iout.startswith("argv-file:") else None
        ok2, o2, r2 = cg.run_capture(skill_dir, inv, entrypoints, output_file=inv_file)
        if not ok2:
            return "ERROR", f"inverse: {r2[:70]}"
        final = _strip_echo(o2, inv)
        return (
            ("HOLD", "")
            if _rt_equal(final, payload, norm)
            else ("VIOLATE", f"inv(fwd(x))!=x: {final[:40]!r} vs {payload[:40]!r}")
        )
    return "ERROR", f"unknown kind {kind!r}"


def _relation_killrate(skill_dir: Path, rel: dict, entrypoints: dict) -> float | None:
    """Mutate the relation's tool source(s); a mutant is KILLED if it makes the relation
    VIOLATE or ERROR. Survivor = relation still HOLDs. Reuses mutate._MUTATIONS.

    round_trip uses two tools (forward + inverse); both are mutated, since a relation
    that survives mutation of EITHER leg is not load-bearing on that leg."""
    eps: list[Path] = []
    for name in (rel.get("tool", ""), rel.get("inverse_tool", "")):
        if not name:
            continue
        ep = entrypoints.get(name) or entrypoints.get(Path(name).name)
        if ep is not None and ep not in eps:
            eps.append(ep)
    if not eps:
        return None
    applicable = killed = 0
    for ep in eps:
        original = ep.read_text(encoding="utf-8", errors="ignore")
        try:
            for _name, pat, repl in mutate._MUTATIONS:
                mutated, n = re.subn(pat, repl, original, count=1)
                if n == 0 or mutated == original:
                    continue
                applicable += 1
                ep.write_text(mutated, encoding="utf-8")
                status, _ = check_relation(skill_dir, rel, entrypoints)
                if status != "HOLD":
                    killed += 1
        finally:
            ep.write_text(original, encoding="utf-8")
    return None if applicable == 0 else killed / applicable


@dataclass
class MetaVerdict:
    slug: str
    verdict: str
    detail: str = ""
    n_relations: int = 0
    relations: list = field(default_factory=list)


def adjudicate_meta(
    skill_dir: Path, api_key: str, model: str, do_mutate: bool = True
) -> MetaVerdict:
    slug = skill_dir.name
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return MetaVerdict(slug, "OUT_OF_SCOPE", "no SKILL.md")
    skill_md = md.read_text(encoding="utf-8", errors="ignore")
    try:
        entrypoints = cg._entrypoints(skill_dir)
    except OutOfScope as e:
        return MetaVerdict(slug, "OUT_OF_SCOPE", e.reason_code)
    tools = sorted({Path(p).name for p in entrypoints if cg._runner_for(Path(p).name)})
    if not tools:
        return MetaVerdict(slug, "OUT_OF_SCOPE", "no py/sh/node entrypoint")

    try:
        proposed = propose_relations(skill_md, tools, api_key, model)
    except (json.JSONDecodeError, ValueError):
        return MetaVerdict(slug, "ABSTAIN", "proposer emitted unparseable JSON")
    rels = proposed.get("relations") or []
    if proposed.get("abstain") or not rels:
        return MetaVerdict(
            slug, "ABSTAIN", proposed.get("reason", "no doc-implied relation")
        )

    records = []
    any_violate = any_hold = False
    n_loadbearing = 0
    for rel in rels:
        status, detail = check_relation(skill_dir, rel, entrypoints)
        kr = None
        if status == "HOLD" and do_mutate:
            kr = _relation_killrate(skill_dir, rel, entrypoints)
            if kr:
                n_loadbearing += 1
        records.append(
            {
                "kind": rel.get("kind"),
                "tool": rel.get("tool"),
                "doc_basis": rel.get("doc_basis", "")[:160],
                "status": status,
                "detail": detail,
                "killrate": kr,
            }
        )
        any_violate = any_violate or status == "VIOLATE"
        any_hold = any_hold or status == "HOLD"

    mv = MetaVerdict(slug, "ABSTAIN", n_relations=len(rels), relations=records)
    if any_violate:
        # A metamorphic divergence is stronger evidence than exact-match's (no guessed
        # bytes), but still NOT a publishable accusation: output-to-output comparison is
        # defeated by any run-specific noise the output embeds (input echo, absolute cwd
        # path, timestamps, PIDs). Every divergence investigated on the addressable slice
        # was such an artifact or a non-reproducible proposer fluke — none a real defect.
        # So this is a review signal, never an accusation (relyable's "never fabricate a
        # broken" rail). A confirmed contradiction needs the author's own example.
        mv.verdict = "DIVERGED"
        mv.detail = (
            "a doc-implied invariant diverged — UNCONFIRMED (likely embedded run-specific "
            "noise or a proposer fluke, not a defect). Review, do not accuse."
        )
    elif not any_hold:
        mv.verdict = "UNJUDGEABLE"
        mv.detail = "all proposed relations errored"
    elif n_loadbearing == 0 and do_mutate:
        mv.verdict = "HOLDS_VACUOUS"
        mv.detail = "relations hold but survived every mutation (not load-bearing)"
    else:
        mv.verdict = "HOLDS"
        mv.detail = f"{n_loadbearing} load-bearing relation(s) hold"
    return mv


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("skills_dir", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-mutate", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    api_key = cg._load_key()
    dirs = sorted(d for d in args.skills_dir.iterdir() if d.is_dir())
    if args.only:
        dirs = [d for d in dirs if d.name in set(args.only)]
    verdicts = []
    for d in dirs:
        try:
            mv = adjudicate_meta(d, api_key, args.model, do_mutate=not args.no_mutate)
        except Exception as e:
            mv = MetaVerdict(
                d.name, "UNJUDGEABLE", f"harness error: {type(e).__name__}: {e}"
            )
        verdicts.append(mv)
        print(f"  {mv.verdict:14} {mv.slug:30} {mv.detail}", file=sys.stderr)

    counts: dict[str, int] = {}
    for mv in verdicts:
        counts[mv.verdict] = counts.get(mv.verdict, 0) + 1
    print("\n== metamorphic coverage ==", file=sys.stderr)
    for k in [
        "HOLDS",
        "HOLDS_VACUOUS",
        "DIVERGED",
        "ABSTAIN",
        "UNJUDGEABLE",
        "OUT_OF_SCOPE",
    ]:
        if counts.get(k):
            print(f"  {k:14} {counts[k]}", file=sys.stderr)
    blob = json.dumps(
        {
            "skills_dir": str(args.skills_dir),
            "model": args.model,
            "counts": counts,
            "verdicts": [asdict(v) for v in verdicts],
        },
        indent=2,
    )
    if args.out:
        args.out.write_text(blob)
        print(f"\n[wrote {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
