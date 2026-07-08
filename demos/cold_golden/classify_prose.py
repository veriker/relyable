#!/usr/bin/env python3
"""classify_prose.py — size the recoverable slice of PROSE (no-bundled-code) skills.

The powered code-presence pull (COLD_GOLDEN_RUN.md §10) found ~half of skills ship no
bundled script — the harness emits OUT_OF_SCOPE_PROSE_SKILL. But "prose" is not one thing.
Reading a handful by hand showed distinct EXECUTION MODELS, each with a different
verifiability story:

  DELEGATES_TO_LOCAL_BIN  the documented way to do the work is to run a specific
                          deterministic, locally-runnable CLI (`uvx markitdown input.pdf`,
                          `pandoc`, `jq`, `ffmpeg` …). The skill is prose but the work is a
                          real, fixed, local tool => RECOVERABLE by cold-golden with an
                          external-command entrypoint: genuine re-derivation, not circular.
  NETWORK_API             the documented execution calls a remote service or fetches/installs
                          (`curl https://…`, `npm i`, `ssh …`). Live / non-deterministic =>
                          out of scope for offline re-derivation.
  OTHER_COMMAND           a shell command whose program is neither a known local-deterministic
                          tool nor a known network/fetch verb — needs a manual look (could be
                          a niche local bin or a niche remote one).
  LLM_EXECUTED            no external command at all — the SKILL.md instructs the agent/model
                          to perform the task itself (case-convert spells out the algorithm in
                          English). "Executing" means running an LLM => only a BEHAVIORAL eval
                          applies (instruction-determinism, partly circular: verifier ≈
                          executor), a weaker claim than artifact re-derivation.

MECHANICAL — no LLM, no API spend. It keys off shell-tagged fenced code blocks, folds `\\`
line-continuations (so a multi-line `curl … \\ -H … \\ -d …` is ONE command, not three), and
judges each command on its PROGRAM (first token, past env-assignments and thin wrappers like
`uvx`/`sudo`) — never "a bin name appears somewhere", which over-counts on incidental greps.
It is a heuristic sizing, not a graded rate; the per-skill evidence is printed so a spot-check
is cheap. Run over the prose skills of a fetched sample:

    python classify_prose.py /tmp/clawhub_powered --out PROSE_EXECUTION_MODEL.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import cold_golden as cg  # noqa: E402

from relyable.adapters._skillpack import OutOfScope  # noqa: E402

_CMD_FENCE_TAGS = {"bash", "sh", "shell", "console", "zsh", "terminal", "shell-session"}

# Deterministic, locally-runnable converter/formatter CLIs — the recoverable subclass.
# Membership is judged on the command's PROGRAM (first token), never "appears anywhere".
_LOCAL_DET_BINS = {
    "markitdown",
    "pandoc",
    "jq",
    "yq",
    "ffmpeg",
    "sox",
    "convert",
    "magick",
    "imagemagick",
    "sed",
    "awk",
    "base64",
    "xxd",
    "iconv",
    "uconv",
    "gnuplot",
    "dot",
    "csvjson",
    "in2csv",
    "csvcut",
    "csvformat",
    "xsv",
    "qsv",
    "sqlite3",
    "tidy",
    "html2text",
    "prettier",
    "black",
    "gofmt",
    "rustfmt",
    "yamllint",
    "xmllint",
}
# Programs that imply a REMOTE call or a fetch/install — never local-deterministic.
_NETWORK_PROGS = {
    "curl",
    "wget",
    "nc",
    "netcat",
    "ssh",
    "scp",
    "sftp",
    "rsync",
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "pip",
    "pip3",
    "go",
    "cargo",
    "gem",
    "brew",
    "apt",
    "apt-get",
    "clawhub",
    "aliyun",
    "gcloud",
    "aws",
    "az",
    "mcporter",
    "tavily",
    "kubectl",
    "docker",
    "git",
    "telnet",
    "http",
    "https",
}
# Thin wrappers to unwrap so the REAL program is judged (uvx markitdown -> markitdown).
_WRAPPERS = {"uvx", "sudo", "env", "time", "nohup", "command", "exec", "xargs"}

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_URL = re.compile(r"https?://", re.IGNORECASE)


def _logical_commands(skill_md: str) -> list[str]:
    """Logical command lines from shell-tagged fenced blocks, folding `\\` continuations."""
    out: list[str] = []
    for info, body in _FENCE.findall(skill_md):
        tag = info.strip().split()[0].lower() if info.strip() else ""
        if tag not in _CMD_FENCE_TAGS:
            continue
        buf = ""
        for raw in body.splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            buf = (buf + " " + stripped) if buf else stripped
            if line.endswith("\\"):
                buf = buf[:-1].rstrip()  # keep accumulating the continuation
            else:
                out.append(buf)
                buf = ""
        if buf:
            out.append(buf)
    return out


def _program(cmd: str) -> str:
    """The invoked program: first token, skipping VAR=val assignments and thin wrappers."""
    toks = cmd.split()
    i = 0
    while i < len(toks) and ("=" in toks[i] and not toks[i].startswith("-")):
        i += 1  # leading env-assignment, e.g. KEY=val cmd
    while i < len(toks) and toks[i].split("/")[-1] in _WRAPPERS:
        i += 1  # unwrap uvx/sudo/env/...
    return toks[i].split("/")[-1] if i < len(toks) else ""


@dataclass
class ProseSkill:
    slug: str
    model: str  # DELEGATES_TO_LOCAL_BIN | NETWORK_API | OTHER_COMMAND | LLM_EXECUTED
    bins: list[str] = field(default_factory=list)
    evidence: str = ""


def classify_one(skill_dir: Path) -> ProseSkill | None:
    """Return a ProseSkill for a prose (no-runnable-entrypoint) skill, else None."""
    md_path = skill_dir / "SKILL.md"
    if not md_path.exists():
        return None
    # Only classify TRUE prose skills — the ones the harness can't run directly.
    try:
        eps = cg._entrypoints(skill_dir)
        if any(cg._runner_for(Path(p).name) for p in eps):
            return None  # ships runnable code: not prose, out of this population
    except OutOfScope:
        pass
    except Exception:
        pass

    md = md_path.read_text(encoding="utf-8", errors="ignore")
    cmds = _logical_commands(md)
    if not cmds:
        return ProseSkill(skill_dir.name, "LLM_EXECUTED", evidence="no command block")

    det_bins: list[str] = []
    det_ev = net_ev = other_ev = ""
    for c in cmds:
        prog = _program(c)
        if prog in _LOCAL_DET_BINS and not _URL.search(c):
            det_bins.append(prog)
            det_ev = det_ev or c[:100]
        elif _URL.search(c) or prog in _NETWORK_PROGS:
            net_ev = net_ev or c[:100]
        else:
            other_ev = other_ev or c[:100]

    # A clean local-deterministic delegation is the recoverable signal; it wins.
    if det_bins:
        return ProseSkill(
            skill_dir.name,
            "DELEGATES_TO_LOCAL_BIN",
            bins=sorted(set(det_bins)),
            evidence=det_ev,
        )
    if net_ev:
        return ProseSkill(skill_dir.name, "NETWORK_API", evidence=net_ev)
    return ProseSkill(skill_dir.name, "OTHER_COMMAND", evidence=other_ev)


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("skills_dir", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    recs: list[ProseSkill] = []
    for d in sorted(p for p in args.skills_dir.iterdir() if p.is_dir()):
        r = classify_one(d)
        if r is not None:
            recs.append(r)

    n = len(recs)
    counts: dict[str, int] = {}
    for r in recs:
        counts[r.model] = counts.get(r.model, 0) + 1

    for r in sorted(recs, key=lambda x: x.model):
        binstr = f" [{','.join(r.bins)}]" if r.bins else ""
        print(f"  {r.model:22} {r.slug:34}{binstr}  «{r.evidence}»", file=sys.stderr)

    print(
        f"\n== prose execution model (mechanical; no LLM) ==  n = {n}", file=sys.stderr
    )
    for k in ("DELEGATES_TO_LOCAL_BIN", "NETWORK_API", "OTHER_COMMAND", "LLM_EXECUTED"):
        c = counts.get(k, 0)
        p, lo, hi = _wilson(c, n)
        print(
            f"  {k:22} {c}/{n} = {p:.1%}  (95% Wilson CI {lo:.1%}-{hi:.1%})",
            file=sys.stderr,
        )

    summary = {
        "skills_dir": str(args.skills_dir),
        "n_prose": n,
        "counts": counts,
        "records": [asdict(r) for r in recs],
    }
    if args.out:
        args.out.write_text(json.dumps(summary, indent=2))
        print(f"\n[wrote {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
