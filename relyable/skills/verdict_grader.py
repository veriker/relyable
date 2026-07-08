"""verdict_grader.py — generate a T1 re-derivation grader from the consumer's OWN
test suite (prototype A).

The blank-page problem: a skill says "this passes", but the agent that wrote the
skill cannot be the one that writes its pass-criteria (that is self-attestation).
Hand-writing held-out goldens per skill (the ``interval_grader`` shape) does not
scale.

For the common case — a *code* skill living in a project that ALREADY has a test
suite — the pass-criteria already exist and the agent did not author them: the
consumer's suite. This module emits a grader that re-derives a candidate skill by
dropping it into place and running that suite. The trust root is the suite the
consumer already had.

WHY THIS IS NOT "the producer grading its own homework" (same contract as
``interval_grader``): the generated grader is the CONSUMER'S trusted copy —
``relyable.gate`` digest-pins it into every bundle, and the test command + target
path are baked into the grader as literals, NOT read from the producer-supplied
``skill/meta.json``. So a poisoned bundle cannot redirect the suite to ``exit 0``;
it can only supply the candidate body, which the suite then judges.

Usage::

    from relyable.skills.verdict_grader import write_verdict_grader
    write_verdict_grader(
        "my_verdict_grader.py",
        project_root="/srv/myproj",
        target_path="src/myproj/skills/generated.py",
        test_cmd=["python", "-m", "pytest", "-q", "tests/test_generated.py"],
    )
    # then pin my_verdict_grader.py as grader_src, exactly like interval_grader.

ISOLATION: by default the grader copies the project to a throwaway tempdir and
runs there, so a candidate never mutates the consumer's working tree. Set
``isolate=False`` to snapshot-and-restore the single target file in place (faster,
but the suite runs against the live tree). The generated grader is stdlib-only and
imports nothing from relyable or veriker (the auditor-independence contract).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# The grader body is a stdlib-only, self-contained module. Consumer-pinned literals
# (PROJECT_ROOT / TARGET_PATH / TEST_CMD / TIMEOUT / ISOLATE) are injected as a
# header ABOVE this body, so the body itself carries no producer- or
# consumer-specific data and needs no brace-escaping.
_GRADER_BODY = '''

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Dirs never worth copying into the isolated work tree (and never the target's
# concern): VCS, virtualenvs, caches, JS deps.
_IGNORE = shutil.ignore_patterns(
    ".git", ".hg", ".svn", ".venv", "venv", "env",
    "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", "node_modules", "build", "dist", "*.egg-info",
)


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def _run_suite(work: Path, candidate_body: str) -> int:
    """Drop the candidate into work/TARGET_PATH and run TEST_CMD with cwd=work.
    Exit 0 iff the suite passes."""
    target = work / TARGET_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(candidate_body, encoding="utf-8")
    except OSError as e:
        return _fail(f"target_write_fail: {e}")
    try:
        proc = subprocess.run(  # noqa: S603 — consumer-pinned TEST_CMD, not bundle-set
            list(TEST_CMD),
            cwd=str(work),
            timeout=TIMEOUT,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return _fail(f"suite_timeout after {TIMEOUT}s")
    except (OSError, ValueError) as e:
        return _fail(f"suite_spawn_fail: {type(e).__name__}: {e}")
    if proc.returncode != 0:
        tail = ((proc.stdout or "")[-600:] + (proc.stderr or "")[-300:]).strip()
        return _fail(f"suite_failed rc={proc.returncode}: ...{tail}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    args = ap.parse_args()
    bundle = Path(args.bundle_dir)

    try:
        body = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    except OSError as e:
        return _fail(f"candidate_unreadable: {e}")
    try:
        ast.parse(body)  # fail-closed on a syntactically broken candidate
    except SyntaxError as e:
        return _fail(f"parse_fail: {e}")

    root = Path(PROJECT_ROOT).resolve()
    if not root.is_dir():
        return _fail(f"project_root_missing: {root}")

    if ISOLATE:
        with tempfile.TemporaryDirectory(prefix="relyable-verdict-") as td:
            work = Path(td) / "proj"
            try:
                shutil.copytree(root, work, ignore=_IGNORE, symlinks=False)
            except OSError as e:
                return _fail(f"project_copy_fail: {e}")
            return _run_suite(work, body)

    # In-place: snapshot the target file, run, then restore unconditionally.
    target = root / TARGET_PATH
    backup = target.read_bytes() if target.exists() else None
    try:
        return _run_suite(root, body)
    finally:
        try:
            if backup is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(backup)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
'''


def make_verdict_grader(
    *,
    project_root: str,
    target_path: str,
    test_cmd: Sequence[str],
    timeout: float = 300.0,
    isolate: bool = True,
) -> str:
    """Return the SOURCE of a stdlib-only re-derivation grader that grades a
    candidate skill by running the consumer's own test suite.

    ``project_root`` — the consumer's project directory (where the suite runs).
    ``target_path``  — path RELATIVE to project_root where the candidate is written
                       before the suite runs (e.g. the module the suite imports).
    ``test_cmd``     — the command that passes iff the candidate is correct, e.g.
                       ``["python", "-m", "pytest", "-q", "tests/test_x.py"]``. Use
                       an absolute interpreter (``sys.executable``) if the suite must
                       run under a specific environment.
    ``timeout``      — seconds before the suite is killed (re-derivation fails).
    ``isolate``      — True (default): run in a throwaway copy of project_root so the
                       candidate never touches the live tree; False: snapshot-restore
                       the single target file in place.

    These become baked-in literals in the grader (consumer authority), so a
    producer-supplied bundle can never redirect them.
    """
    if (
        not target_path
        or Path(target_path).is_absolute()
        or ".." in Path(target_path).parts
    ):
        raise ValueError(
            f"target_path must be a relative path inside the project (got {target_path!r})"
        )
    cmd = list(test_cmd)
    if not cmd:
        raise ValueError("test_cmd must be a non-empty command list")
    header = (
        "PROJECT_ROOT = %r\n"
        "TARGET_PATH = %r\n"
        "TEST_CMD = %r\n"
        "TIMEOUT = %r\n"
        "ISOLATE = %r\n"
    ) % (str(project_root), str(target_path), cmd, float(timeout), bool(isolate))
    preamble = (
        "#!/usr/bin/env python3\n"
        '"""GENERATED by relyable.skills.verdict_grader — do not edit by hand.\n\n'
        "A T1 (pre-existing-ground-truth) re-derivation grader: it grades a candidate\n"
        "skill by running the CONSUMER'S OWN test suite with the candidate dropped\n"
        "into place. The trust root is the suite the consumer already had — the agent\n"
        "that wrote the skill did not author it. Stdlib only; no relyable/veriker import\n"
        "(auditor-independence). The literals below are CONSUMER authority, baked in at\n"
        "generation time, never read from the producer-supplied bundle.\n"
        '"""\n'
    )
    return preamble + header + _GRADER_BODY


def write_verdict_grader(
    dest: str | Path,
    *,
    project_root: str,
    target_path: str,
    test_cmd: Sequence[str],
    timeout: float = 300.0,
    isolate: bool = True,
) -> Path:
    """Write a verdict grader (see ``make_verdict_grader``) to ``dest`` and return
    the path. Pin ``dest`` as ``grader_src`` exactly like ``interval_grader``."""
    src = make_verdict_grader(
        project_root=project_root,
        target_path=target_path,
        test_cmd=test_cmd,
        timeout=timeout,
        isolate=isolate,
    )
    dest = Path(dest)
    dest.write_text(src, encoding="utf-8")
    return dest
