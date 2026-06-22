"""diff_coverage — added/changed lines must clear a coverage floor.

The cheapest defense against "land new code with no tests for it". Where
no_shrink protects the *whole* suite from dropping below a baseline, this guards
the *delta*: every coverable line you added or changed in this diff must be
exercised by the suite the gate just ran, at or above `min_percent`.

Two inputs, both fail-closed:

  * a Cobertura coverage report (`<class filename><lines><line number= hits=>`),
    the format pytest-cov / coverage.py / jest (cobertura reporter) / gcovr all
    emit. Parsed with stdlib ``xml.etree``; a DOCTYPE is refused (entity-expansion
    hardening, same posture as verdict.py) and any malformed/absent report is a
    BLOCK, never a silent skip.
  * the added line numbers from ``git diff --unified=0 <base_ref>``. Not a git
    repo, an unknown base_ref, or git absent is a BLOCK — an enabled guard that
    cannot establish what changed must fail closed, not wave the change through.

An enabled-but-uncomputable guard returns ``ok=False`` (NOT ``inactive``):
``inactive`` is reserved for "the floor is legitimately unset" (no baseline),
whereas a coverage report that should exist but doesn't is exactly the state an
attacker would engineer. Only a clean, fully-determined "added lines met the
floor" returns ``ok=True``.

Config (honesty.toml):

    [ratchets]
    diff_coverage = { enabled = true, min_percent = 90, \
                      coverage_xml = "coverage.xml", base_ref = "origin/main" }

  min_percent   floor for covered fraction of added coverable lines (default 90)
  coverage_xml  workspace-relative path to the Cobertura report (default
                "coverage.xml"); the [test].command must emit it, e.g.
                pytest --cov --cov-report=xml
  base_ref      git ref the diff is taken against (default "origin/main")
  paths         optional list of workspace-relative pathspecs to limit the diff
  max_listed    cap on uncovered file:line entries named in detail (default 20)

Stdlib only.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import RatchetContext, RatchetResult

# Covered-fraction comparison tolerance — floating-point slack only.
_EPSILON = 1e-9


class _CoverageParseError(Exception):
    """The coverage report could not be parsed. Fail-closed."""


class _GitError(Exception):
    """The diff could not be obtained from git. Fail-closed."""


@dataclass(frozen=True, slots=True)
class _FileCoverage:
    covered: frozenset[int]
    coverable: frozenset[int]


class DiffCoverage:
    name = "diff_coverage"

    def check(self, ctx: RatchetContext) -> RatchetResult:
        params = ctx.config.ratchet_params(self.name)
        min_percent = float(params.get("min_percent", 90))
        coverage_xml = str(params.get("coverage_xml", "coverage.xml"))
        base_ref = str(params.get("base_ref", "origin/main"))
        raw_paths = params.get("paths", [])
        paths = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else []
        max_listed = int(params.get("max_listed", 20))

        # (1) Coverage report — required; absent/malformed BLOCKS.
        cov_file = (ctx.workspace / coverage_xml).resolve()
        if not cov_file.is_file():
            return RatchetResult(
                self.name,
                ok=False,
                detail=(
                    f"coverage report not found at {coverage_xml!r} — the "
                    "[test].command must emit a Cobertura XML (e.g. pytest --cov "
                    "--cov-report=xml). An enabled diff_coverage guard with no "
                    "report fails closed."
                ),
            )
        try:
            file_cov = _parse_cobertura(cov_file)
        except _CoverageParseError as exc:
            return RatchetResult(self.name, ok=False, detail=str(exc))

        # (2) Added lines from git — not-a-repo / bad ref / git-absent BLOCKS.
        try:
            added = _git_added_lines(ctx.workspace, base_ref, paths)
        except _GitError as exc:
            return RatchetResult(self.name, ok=False, detail=str(exc))

        # (3) Intersect added lines with what the coverage report knows is
        # coverable, then measure the covered fraction.
        cov_index = list(file_cov)
        total_coverable = 0
        total_covered = 0
        uncovered: list[str] = []
        for git_path, added_lines in sorted(added.items()):
            match = _match_coverage(git_path, cov_index)
            if match is None:
                # File not in the coverage report at all (non-source, or out of
                # the --cov scope). No coverable lines known for it; skip. A new
                # in-scope module that is wholly untested DOES appear here (all
                # hits=0) and so is caught.
                continue
            fc = file_cov[match]
            added_coverable = added_lines & fc.coverable
            if not added_coverable:
                continue
            covered_here = added_coverable & fc.covered
            total_coverable += len(added_coverable)
            total_covered += len(covered_here)
            for line in sorted(added_coverable - fc.covered):
                uncovered.append(f"{git_path}:{line}")

        if total_coverable == 0:
            return RatchetResult(
                self.name,
                ok=True,
                detail=(
                    f"no coverable lines added vs {base_ref} "
                    "(no source-line delta to cover)"
                ),
            )

        fraction = total_covered / total_coverable
        pct = fraction * 100.0
        if pct + _EPSILON < min_percent:
            shown = uncovered[:max_listed]
            more = (
                ""
                if len(uncovered) <= max_listed
                else f" (+{len(uncovered) - max_listed} more)"
            )
            return RatchetResult(
                self.name,
                ok=False,
                detail=(
                    f"added-line coverage {pct:.1f}% < floor {min_percent:.1f}% "
                    f"({total_covered}/{total_coverable} added coverable lines "
                    f"covered vs {base_ref}); uncovered: {shown}{more}"
                ),
            )
        return RatchetResult(
            self.name,
            ok=True,
            detail=(
                f"added-line coverage {pct:.1f}% >= floor {min_percent:.1f}% "
                f"({total_covered}/{total_coverable} added coverable lines covered)"
            ),
        )


# ---------------------------------------------------------------------------
# Cobertura parsing
# ---------------------------------------------------------------------------


def _parse_cobertura(path: Path) -> dict[str, _FileCoverage]:
    """Parse a Cobertura XML report into ``{filename: _FileCoverage}``.

    Coverable lines are those that appear as ``<line number=...>``; covered lines
    are those whose ``hits`` is a positive integer. Multiple ``<class>`` entries
    for one filename are unioned. Raises ``_CoverageParseError`` (fail-closed) on
    a DOCTYPE, malformed XML, an unexpected root, or a bad line attribute.
    """
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _CoverageParseError(
            f"coverage report at {path} is unreadable: {exc}"
        ) from exc

    if "<!DOCTYPE" in text:
        raise _CoverageParseError(
            "coverage report contains a DOCTYPE; refused (DTD hardening)"
        )

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise _CoverageParseError(
            f"coverage report is not well-formed XML: {exc}"
        ) from exc

    root_tag = _strip_ns(root.tag)
    if root_tag != "coverage":
        raise _CoverageParseError(
            f"unrecognized coverage root <{root_tag}> (expected <coverage>)"
        )

    covered: dict[str, set[int]] = {}
    coverable: dict[str, set[int]] = {}
    for cls in root.iter():
        if _strip_ns(cls.tag) != "class":
            continue
        filename = cls.get("filename")
        if not filename:
            continue
        norm = _norm_path(filename)
        cov_set = coverable.setdefault(norm, set())
        hit_set = covered.setdefault(norm, set())
        for line_el in cls.iter():
            if _strip_ns(line_el.tag) != "line":
                continue
            num_raw = line_el.get("number")
            if num_raw is None:
                continue
            try:
                num = int(num_raw)
            except ValueError as exc:
                raise _CoverageParseError(
                    f"coverage line has a non-integer number {num_raw!r}: {exc}"
                ) from exc
            cov_set.add(num)
            hits_raw = line_el.get("hits", "0")
            try:
                hits = int(hits_raw)
            except ValueError:
                hits = 0
            if hits > 0:
                hit_set.add(num)

    return {
        fname: _FileCoverage(
            covered=frozenset(covered.get(fname, set())),
            coverable=frozenset(lines),
        )
        for fname, lines in coverable.items()
    }


# ---------------------------------------------------------------------------
# git diff parsing
# ---------------------------------------------------------------------------


def _git_added_lines(
    workspace: Path, base_ref: str, paths: list[str]
) -> dict[str, set[int]]:
    """Return ``{filename: {added new-file line numbers}}`` from
    ``git diff --unified=0 <base_ref>``. Raises ``_GitError`` (fail-closed) when
    the workspace is not a git repo, the ref is unknown, or git is unavailable."""
    cmd = [
        "git",
        "-C",
        str(workspace),
        "diff",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        base_ref,
        "--",
    ]
    cmd.extend(paths)
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise _GitError(f"git not found on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise _GitError(f"git diff timed out: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        msg = tail[-1] if tail else f"git exited {proc.returncode}"
        raise _GitError(
            f"git diff against {base_ref!r} failed (is it a git repo / valid "
            f"ref?): {msg}"
        )
    return _parse_unified_diff(proc.stdout)


def _parse_unified_diff(diff: str) -> dict[str, set[int]]:
    """Parse a unified diff into per-file added (new-side) line numbers.

    Robust to any context width: the new-line counter is seeded from each hunk
    header's ``+start`` and advanced on added and context lines, so only genuine
    ``+`` additions are recorded.
    """
    added: dict[str, set[int]] = {}
    current: str | None = None
    new_lineno = 0
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            current = None
            in_hunk = False
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                # strip a leading "b/" (or "a/") prefix git adds
                if target.startswith(("a/", "b/")):
                    target = target[2:]
                current = _norm_path(target)
                added.setdefault(current, set())
            in_hunk = False
            continue
        if line.startswith("@@"):
            new_lineno = _hunk_new_start(line)
            in_hunk = True
            continue
        if not in_hunk or current is None:
            continue
        if line.startswith("+"):
            added[current].add(new_lineno)
            new_lineno += 1
        elif line.startswith("-"):
            # removed line — no new-file line consumed
            continue
        elif line.startswith("\\"):
            # "\ No newline at end of file" — not a line
            continue
        else:
            # context line (present with unified>0) advances the new counter
            new_lineno += 1
    return {f: lines for f, lines in added.items() if lines}


def _hunk_new_start(header: str) -> int:
    """Extract the new-file start line from a hunk header ``@@ -a,b +c,d @@``."""
    try:
        plus = header.split("+", 1)[1]
        token = plus.split(" ", 1)[0].split(",", 1)[0]
        return int(token)
    except (IndexError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _norm_path(p: str) -> str:
    """Normalize a path to forward-slash POSIX form for cross-source matching."""
    return PurePosixPath(p.replace("\\", "/")).as_posix()


def _match_coverage(git_path: str, cov_paths: list[str]) -> str | None:
    """Match a changed git path to a coverage filename.

    Coverage filenames are relative to the --cov source root; git paths are
    relative to the repo root, so one is typically a path-component suffix of the
    other (e.g. coverage 'pkg/foo.py' vs git 'sub/dir/pkg/foo.py'). Returns the
    unambiguous longest-suffix match, or None if there is no confident match.
    """
    if git_path in cov_paths:
        return git_path
    g = PurePosixPath(git_path).parts
    best: str | None = None
    best_len = 0
    tie = False
    for cov in cov_paths:
        c = PurePosixPath(cov).parts
        n = _common_suffix_len(g, c)
        # require the shorter path to be a full suffix of the longer
        if n == 0 or n < min(len(g), len(c)):
            continue
        if n > best_len:
            best, best_len, tie = cov, n, False
        elif n == best_len:
            tie = True
    return None if (best is None or tie) else best


def _common_suffix_len(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    n = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x != y:
            break
        n += 1
    return n
