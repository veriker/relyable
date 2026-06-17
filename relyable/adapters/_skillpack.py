"""_skillpack.py — package a NATIVE agent skill into a re-derivable veriker bundle.

THE SHARED OPEN SEAM. relyable's skills gate re-derives a veriker bundle
(``skill/`` + ``re_derive/<grader>`` + a digest-bound manifest). A native skill —
a ClawHub ``SKILL.md`` + scripts, or a Hermes skill dir — is NOT that shape. This
module is the producer-side step that turns a native skill directory into a bundle
the existing ``relyable.skills`` gate (``admit_directory`` / ``rederive``) admits
unchanged. It is adapter-agnostic: the OpenClaw ``security.installPolicy`` gate and
the Hermes write-guard both feed it.

CONCEPTUAL BOUNDARY (do not overclaim): a native ``SKILL.md`` carries NO machine-
checkable pass-label — its frontmatter has no test/grader/verdict field. So this is
NOT "re-derive the producer's claim"; it is a CONSUMER-SPEC CONFORMANCE gate: the
consumer supplies the grader (held-out goldens + the I/O check), and the gate admits
iff the skill's own entrypoint reproduces them. ``claimed_verdict`` is a sentinel
for the audit trail only.

SCOPE: IN = a skill with an executable entrypoint and a definable I/O contract
(the scrape / convert / SQL / codegen class). OUT = prose / instruction-only skills
with no deterministic oracle — there is nothing to re-derive, so ``pack_native_skill``
raises ``OutOfScope`` rather than fabricate a verdict (mirrors the Hermes adapter's
"correctness/consistency axis, not arbitrary prose" boundary).

Stdlib only (no PyYAML dependency): the frontmatter parser handles the YAML subset
SKILL.md files use in practice (scalars, one level of mapping nesting, inline lists).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Runners the grader is permitted to invoke. An allowlist, not an open exec: a
# bundle naming an off-list runner is refused at pack time, never shelled out to.
RUNNERS: frozenset[str] = frozenset({"python", "sh", "node"})

# File extension -> runner, for entrypoint auto-detection when frontmatter is silent.
_EXT_RUNNER = {".py": "python", ".sh": "sh", ".js": "node", ".mjs": "node"}

# Reason codes (consumer-facing).
OUT_OF_SCOPE_PROSE_SKILL = "OUT_OF_SCOPE_PROSE_SKILL"
AMBIGUOUS_ENTRYPOINT = "AMBIGUOUS_ENTRYPOINT"
NO_SKILL_MD = "NO_SKILL_MD"
BAD_RUNNER = "BAD_RUNNER"


class OutOfScope(Exception):
    """A native skill that the re-derivation gate cannot judge (prose-only, no
    locatable entrypoint, or an off-allowlist runner). Carries a ``reason_code``."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Invocation:
    """How the grader runs the skill's entrypoint. Recorded in skill/meta.json as a
    HINT — it travels in the bundle, so it is producer-influenced; the consumer's
    grader treats it as untrusted and a lying entrypoint just fails to re-derive."""

    entrypoint: str  # path relative to the skill dir, e.g. "convert.py"
    runner: str  # one of RUNNERS
    input_mode: str = "stdin"  # "stdin" | "argv" | "none"
    output_mode: str = "stdout"  # "stdout" | "file"

    def __post_init__(self) -> None:
        if self.runner not in RUNNERS:
            raise OutOfScope(
                BAD_RUNNER, f"runner {self.runner!r} not in allowlist {sorted(RUNNERS)}"
            )

    def to_meta(self) -> dict:
        return {
            "entrypoint": self.entrypoint,
            "runner": self.runner,
            "input_mode": self.input_mode,
            "output_mode": self.output_mode,
        }


def parse_frontmatter(md_text: str) -> dict:
    """Parse the leading ``---``-fenced YAML frontmatter of a SKILL.md into a dict.

    Stdlib-only subset parser: top-level ``key: value`` scalars, one level of
    mapping nesting by indentation, and inline ``[a, b]`` lists. Returns {} when no
    frontmatter fence is present. Not a full YAML implementation — sufficient for
    the fields SKILL.md files carry (name, version, metadata.openclaw.*)."""
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    body: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        body.append(ln)

    root: dict = {}
    # stack of (indent, container) for one-level (and deeper) mapping nesting.
    stack: list[tuple[int, dict]] = [(-1, root)]

    def _scalar(v: str):
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            return [_scalar(x) for x in inner.split(",")] if inner else []
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            return v[1:-1]
        return v

    for raw in body:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        key, _, rest = raw.strip().partition(":")
        key = key.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        container = stack[-1][1]
        if rest.strip() == "":
            child: dict = {}
            container[key] = child
            stack.append((indent, child))
        else:
            container[key] = _scalar(rest)
    return root


def _slug(name: str) -> str:
    return (
        "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip()).strip("-")
        or "skill"
    )


def detect_invocation(skill_dir: Path, frontmatter: dict) -> Invocation:
    """Resolve how to invoke a native skill, or raise OutOfScope.

    Precedence: an explicit ``metadata.relyable.entrypoint`` (+ optional runner /
    input_mode / output_mode) in frontmatter wins. Otherwise infer from a single
    script file (*.py/*.sh/*.js) in the skill dir. Zero scripts -> prose-only
    (OUT_OF_SCOPE_PROSE_SKILL). More than one with no explicit hint -> ambiguous."""
    rel = (frontmatter.get("metadata", {}) or {}).get("relyable", {}) or {}
    if rel.get("entrypoint"):
        ep = str(rel["entrypoint"])
        runner = str(rel.get("runner") or _EXT_RUNNER.get(Path(ep).suffix, "python"))
        return Invocation(
            entrypoint=ep,
            runner=runner,
            input_mode=str(rel.get("input_mode", "stdin")),
            output_mode=str(rel.get("output_mode", "stdout")),
        )

    scripts = sorted(
        p
        for p in skill_dir.rglob("*")
        if p.is_file() and p.suffix in _EXT_RUNNER and p.name != "SKILL.md"
    )
    if not scripts:
        raise OutOfScope(
            OUT_OF_SCOPE_PROSE_SKILL,
            "no executable entrypoint (*.py/*.sh/*.js) found — prose/instruction "
            "skills have no deterministic oracle to re-derive",
        )
    if len(scripts) > 1:
        raise OutOfScope(
            AMBIGUOUS_ENTRYPOINT,
            f"{len(scripts)} candidate scripts {[s.name for s in scripts]}; declare "
            "metadata.relyable.entrypoint in SKILL.md or pass invocation=",
        )
    ep = scripts[0]
    return Invocation(
        entrypoint=ep.relative_to(skill_dir).as_posix(),
        runner=_EXT_RUNNER[ep.suffix],
    )


def pack_native_skill(
    skill_dir: Path,
    dest: Path,
    *,
    grader_src: Path,
    kind: str | None = None,
    invocation: Invocation | None = None,
    pack_filename: str | None = None,
    author_principal: str | None = None,
) -> Path:
    """Package the native skill at ``skill_dir`` into a re-derivable veriker bundle
    at ``dest``, ready for ``relyable.skills.rederive`` / ``admit_directory``.

    Reads ``SKILL.md`` frontmatter for identity; runs the SCOPE GATE (raising
    ``OutOfScope`` for prose-only / ambiguous / off-allowlist skills); installs the
    consumer's ``grader_src`` as the bundle grader; and records an ``Invocation``
    hint in meta. ``kind`` selects which goldens the grader applies (defaults to the
    skill slug). Returns ``dest``."""
    md = skill_dir / "SKILL.md"
    frontmatter = (
        parse_frontmatter(md.read_text(encoding="utf-8")) if md.is_file() else {}
    )
    name = str(frontmatter.get("name") or skill_dir.name)
    skill_id = _slug(name)
    if invocation is None:
        invocation = detect_invocation(skill_dir, frontmatter)

    # Local import: keep the adapter loadable without importing the gate stack until
    # a pack is actually built (mirrors the adapter packages' import discipline).
    from relyable.skills.bundle import build_native_skill_bundle

    return build_native_skill_bundle(
        dest,
        skill_id=skill_id,
        kind=kind or skill_id,
        artifact_dir=skill_dir,
        grader_src=grader_src,
        invocation=invocation.to_meta(),
        pack_filename=pack_filename,
        author_principal=author_principal
        or (frontmatter.get("metadata", {}) or {}).get("author"),
    )
