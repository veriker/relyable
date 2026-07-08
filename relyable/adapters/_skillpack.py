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

from collections.abc import Callable
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


def _metadata(frontmatter: dict) -> dict:
    """The ``metadata`` mapping from frontmatter, or {} if absent or non-mapping.

    Real SKILL.md files in the wild carry ``metadata`` as an inline flow value
    (e.g. ``metadata: {"clawdbot": {...}}``), which the stdlib subset parser returns
    as a *string* rather than a dict. Reading hint fields off that string would raise
    AttributeError; treat any non-mapping metadata as 'no relyable hint present'."""
    meta = frontmatter.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _tool_scripts(skill_dir: Path) -> list[Path]:
    """The candidate ENTRYPOINT scripts under ``skill_dir`` (*.py/*.sh/*.js),
    sorted. Excludes two non-entrypoint classes so a real multi-file skill is not
    mis-read:

      * leading-underscore module helpers (``_common.py``) — imported BY a tool, not
        invoked as one (Python's private-module convention);
      * anything under a ``__pycache__/`` dir (compiled artefacts).

    SKILL.md is never a script. This is the shared candidate set behind both the
    single-entrypoint ``detect_invocation`` and the N-tool ``enumerate_tools``."""
    return sorted(
        p
        for p in skill_dir.rglob("*")
        if p.is_file()
        and p.suffix in _EXT_RUNNER
        and p.name != "SKILL.md"
        and not p.name.startswith("_")
        and "__pycache__" not in p.parts
    )


def _explicit_invocation(frontmatter: dict) -> Invocation | None:
    """The ``metadata.relyable.entrypoint`` hint as an Invocation, or None when the
    frontmatter declares no single explicit entrypoint."""
    rel = _metadata(frontmatter).get("relyable") or {}
    if isinstance(rel, dict) and rel.get("entrypoint"):
        ep = str(rel["entrypoint"])
        runner = str(rel.get("runner") or _EXT_RUNNER.get(Path(ep).suffix, "python"))
        return Invocation(
            entrypoint=ep,
            runner=runner,
            input_mode=str(rel.get("input_mode", "stdin")),
            output_mode=str(rel.get("output_mode", "stdout")),
        )
    return None


def detect_invocation(skill_dir: Path, frontmatter: dict) -> Invocation:
    """Resolve how to invoke a SINGLE-ENTRYPOINT native skill, or raise OutOfScope.

    Precedence: an explicit ``metadata.relyable.entrypoint`` (+ optional runner /
    input_mode / output_mode) in frontmatter wins. Otherwise infer from a single
    script file (*.py/*.sh/*.js) in the skill dir. Zero scripts -> prose-only
    (OUT_OF_SCOPE_PROSE_SKILL). More than one with no explicit hint -> AMBIGUOUS
    (the skill is a tool BUNDLE — route it through ``enumerate_tools`` /
    ``pack_native_tool_bundles`` instead, which re-derives one bundle per tool).

    Module helpers (``_common.py``) do NOT count as entrypoints, so a one-tool
    skill that ships a shared helper is single-entrypoint, not ambiguous."""
    explicit = _explicit_invocation(frontmatter)
    if explicit is not None:
        return explicit

    scripts = _tool_scripts(skill_dir)
    if not scripts:
        raise OutOfScope(
            OUT_OF_SCOPE_PROSE_SKILL,
            "no executable entrypoint (*.py/*.sh/*.js) found — prose/instruction "
            "skills have no deterministic oracle to re-derive",
        )
    if len(scripts) > 1:
        raise OutOfScope(
            AMBIGUOUS_ENTRYPOINT,
            f"{len(scripts)} candidate scripts {[s.name for s in scripts]}; this is a "
            "tool BUNDLE — use enumerate_tools / pack_native_tool_bundles (one bundle "
            "per tool), declare metadata.relyable.entrypoint, or pass invocation=",
        )
    ep = scripts[0]
    return Invocation(
        entrypoint=ep.relative_to(skill_dir).as_posix(),
        runner=_EXT_RUNNER[ep.suffix],
    )


def enumerate_tools(skill_dir: Path, frontmatter: dict) -> list[Invocation]:
    """The N-tool generalization of ``detect_invocation``: every bundled tool a
    native skill routes to, as a list of ``Invocation`` (one per entrypoint script).

    A real ClawHub "tool bundle" is a SKILL.md whose prose routes to several bundled
    ``scripts/*`` — each a small CLI. ``detect_invocation`` raises AMBIGUOUS on these
    because it models exactly one entrypoint; this returns them all so the caller can
    re-derive ONE bundle per tool (``pack_native_tool_bundles``).

    The set of tools is producer-supplied (the scripts the skill ships + any
    ``metadata.relyable.entrypoint`` hint) and therefore UNTRUSTED — the consumer's
    grader keys its held-out goldens by tool; a tool with no goldens fails closed
    (unjudgeable) and a lying invocation simply fails to reproduce. Raises
    OUT_OF_SCOPE_PROSE_SKILL when the skill ships no executable entrypoint at all.

    Each tool's input/output mode defaults to the conservative stdin/stdout; an
    explicit ``metadata.relyable.entrypoint`` hint (if present) keeps its declared
    modes and leads the list."""
    invs: list[Invocation] = []
    seen: set[str] = set()
    explicit = _explicit_invocation(frontmatter)
    if explicit is not None:
        invs.append(explicit)
        seen.add(explicit.entrypoint)
    for ep in _tool_scripts(skill_dir):
        rel = ep.relative_to(skill_dir).as_posix()
        if rel in seen:
            continue
        invs.append(Invocation(entrypoint=rel, runner=_EXT_RUNNER[ep.suffix]))
        seen.add(rel)
    if not invs:
        raise OutOfScope(
            OUT_OF_SCOPE_PROSE_SKILL,
            "no executable entrypoint (*.py/*.sh/*.js) found — prose/instruction "
            "skills have no deterministic oracle to re-derive",
        )
    return invs


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
        author_principal=author_principal or _metadata(frontmatter).get("author"),
    )


def pack_native_tool_bundles(
    skill_dir: Path,
    dest_root: Path,
    *,
    grader_src: Path,
    kind_prefix: str | None = None,
    kind_for: Callable[[Invocation], str] | None = None,
    invocations: list[Invocation] | None = None,
    pack_filename: str | None = None,
    author_principal: str | None = None,
) -> dict[str, Path]:
    """Pack a multi-tool native skill (a "tool bundle": one SKILL.md routing to N
    bundled ``scripts/*``) into ONE re-derivable veriker bundle PER tool, each under
    ``dest_root/<tool>/`` and ready for ``relyable.skills.admit_directory`` /
    ``rederive``. Returns ``{tool_stem: bundle_dir}``.

    This is the tool-BUNDLE generalization of ``pack_native_skill`` (which packs a
    single entrypoint and raises AMBIGUOUS on a bundle). Each per-tool bundle carries
    the WHOLE skill tree (``artifact_dir=skill_dir``) — so a shared helper like
    ``_common.py`` that the tools import at module level travels with every tool — and
    records that tool's ``Invocation`` as the meta hint.

    KIND (which goldens the consumer's grader applies) is, in precedence order:
    ``kind_for(inv)`` if given; else ``f"{kind_prefix or skill_id}:{tool_stem}"``
    (the convention the worked ``json_toolkit_grader`` keys on, e.g.
    ``clean-json-toolkit:query``). A tool whose kind has no goldens fails closed
    (the grader returns no_goldens_for_kind -> not admitted), never fabricates a
    pass; so admitting K of N tools is honest — only the consumer-graded tools count.

    ``invocations`` overrides the auto-enumeration (defaults to
    ``enumerate_tools(skill_dir, frontmatter)``)."""
    md = skill_dir / "SKILL.md"
    frontmatter = (
        parse_frontmatter(md.read_text(encoding="utf-8")) if md.is_file() else {}
    )
    name = str(frontmatter.get("name") or skill_dir.name)
    skill_id = _slug(name)
    prefix = kind_prefix or skill_id
    if invocations is None:
        invocations = enumerate_tools(skill_dir, frontmatter)

    from relyable.skills.bundle import build_native_skill_bundle

    out: dict[str, Path] = {}
    for inv in invocations:
        stem = Path(inv.entrypoint).stem
        kind = kind_for(inv) if kind_for is not None else f"{prefix}:{stem}"
        dest = dest_root / stem
        build_native_skill_bundle(
            dest,
            skill_id=f"{skill_id}-{stem}",
            kind=kind,
            artifact_dir=skill_dir,
            grader_src=grader_src,
            invocation=inv.to_meta(),
            pack_filename=pack_filename,
            author_principal=author_principal or _metadata(frontmatter).get("author"),
        )
        out[stem] = dest
    return out
