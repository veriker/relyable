"""scaffold.py — ``relyable init``: detect the cheapest applicable grader rung for
a skill and scaffold the grader, so a consumer CONFIRMS a detected grader instead
of writing one from a blank page.

The blank-page problem (same one ``verdict_grader`` attacks for the T1 case): a
skill ships an *asserted* "this passes", but the agent that wrote it cannot author
its own pass-criteria. Hand-writing held-out goldens per skill does not scale. This
module looks at the skill (and the repo it lives in) and picks the cheapest rung of
the trust-root ladder that actually applies, then emits the matching grader:

  T1  pre-existing consumer suite — the repo already has a pytest suite that covers
      the skill. The pass-criteria already exist and the agent did not author them.
      AUTO-FILLABLE: delegates to ``verdict_grader.make_verdict_grader`` with the
      detected project_root / target_path / test_cmd. This is the real win — a
      complete, runnable grader with no human edits.

  T2  structured output + schema — the skill returns data with a schema present.
      Scaffolds a schema-conformance PROPERTY. A property an author can propose is
      only trustworthy once proven NON-VACUOUS (a property no broken candidate can
      fail asserts nothing); that anti-vacuity proof is a separate gate (mutate the
      candidate, the property must KILL the mutants). Until that runs, this is a
      PROPOSAL to confirm by hand — NOT auto-pinned.

  T0  pure deterministic entrypoint — a function with no nondeterminism source.
      Scaffolds a determinism property (run twice, require identical output). Proves
      REPRODUCIBILITY, never correctness — the weakest root. PROPOSAL: fill the
      sample inputs and confirm.

  T5  nothing detectable — emits the general held-out-goldens shape (the
      ``interval_grader`` template, emptied) for a human to fill.

HONEST SCOPE: detection is static and heuristic. Only T1 yields a usable grader
with no human edits, and even then relyable cannot prove the detected suite truly
exercises the skill (a suite that passes regardless is a vacuous T1 root) — the
``caveat`` on every detection says what the human must still confirm. T0/T2/T5 emit
templates with clearly-marked FILL-ME sections; they are scaffolds, not finished
trust roots. The generated graders are stdlib-only (auditor-independence), exactly
like ``interval_grader`` / ``verdict_grader``.
"""

from __future__ import annotations

import ast
import configparser
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .property_grader import make_property_grader
from .verdict_grader import make_verdict_grader

# Import sources that make a function's output depend on wall-clock / entropy /
# external state — their presence rules out the T0 "pure deterministic" rung.
_NONDET_ROOTS = frozenset(
    {
        "random",
        "secrets",
        "time",
        "datetime",
        "uuid",
        "os",  # os.urandom / os.environ / os.getpid …
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "threading",
        "multiprocessing",
        "tempfile",
        "subprocess",
    }
)

# Files / config sections that indicate a pytest setup at a repo root.
_PYTEST_INI_FILES = ("pytest.ini", "tox.ini", "setup.cfg")
_PROJECT_MARKERS = ("pyproject.toml", "setup.cfg", "setup.py", "pytest.ini", "tox.ini")


@dataclass(frozen=True, slots=True)
class Detection:
    """What ``detect_rung`` concluded. ``auto_fillable`` is True ONLY for T1 (a
    complete grader with no human edits). ``caveat`` is the honest limitation the
    consumer must still check before trusting the emitted grader."""

    rung: str  # "T1" | "T2" | "T0" | "T5"
    reason: str
    caveat: str
    auto_fillable: bool
    params: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """The outcome of writing a scaffold. ``needs_confirmation`` is True for every
    rung except a clean T1 — a reminder that the consumer, not the scaffolder, is
    the trust root."""

    rung: str
    dest: Path
    auto_fillable: bool
    needs_confirmation: bool
    reason: str
    caveat: str
    next_step: str


# ---------------------------------------------------------------------------
# detection helpers (pure, static; stdlib only)
# ---------------------------------------------------------------------------


def _parse(skill_path: Path) -> ast.AST | None:
    try:
        return ast.parse(skill_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None


def _contract_fns(tree: ast.AST) -> list[str]:
    """Public top-level function names — the candidate's contract entrypoints."""
    return [
        n.name
        for n in getattr(tree, "body", [])
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not n.name.startswith("_")
    ]


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _find_project_root(skill_path: Path, given: Path | None) -> Path | None:
    if given is not None:
        return given.resolve()
    cur = skill_path.resolve().parent
    for parent in (cur, *cur.parents):
        if (
            any((parent / m).exists() for m in _PROJECT_MARKERS)
            or (parent / "tests").is_dir()
        ):
            return parent
    return None


def _pytest_testpaths_from_cfg(root: Path) -> list[str]:
    """Best-effort: read testpaths from setup.cfg/tox.ini/pytest.ini. pyproject's
    TOML testpaths are left to pytest's own discovery (no tomllib parse needed —
    an empty testpaths just means default discovery)."""
    for name in _PYTEST_INI_FILES:
        path = root / name
        if not path.is_file():
            continue
        section = "tool:pytest" if name == "setup.cfg" else "pytest"
        parser = configparser.ConfigParser()
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            continue
        if parser.has_option(section, "testpaths"):
            return parser.get(section, "testpaths").split()
    return []


def _has_pytest_layout(root: Path) -> bool:
    if (root / "pytest.ini").is_file():
        return True
    for name in ("setup.cfg", "tox.ini"):
        path = root / name
        section = "tool:pytest" if name == "setup.cfg" else "pytest"
        if path.is_file():
            parser = configparser.ConfigParser()
            try:
                parser.read(path, encoding="utf-8")
            except (OSError, configparser.Error):
                continue
            if parser.has_section(section):
                return True
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            if "[tool.pytest" in pyproject.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
    tests = root / "tests"
    if tests.is_dir() and any(
        p.name.startswith("test_") or p.name.endswith("_test.py")
        for p in tests.rglob("*.py")
    ):
        return True
    return False


def _detect_schema(skill_path: Path, tree: ast.AST) -> dict | None:
    """A schema is 'present' if the skill assigns a module-level SCHEMA/OUTPUT_SCHEMA
    dict, imports a schema library, or a ``*.schema.json`` sibling exists."""
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id in ("SCHEMA", "OUTPUT_SCHEMA")
                    and isinstance(node.value, ast.Dict)
                ):
                    return {"source": f"module-level {tgt.id}"}
    libs = _imported_roots(tree) & {"jsonschema", "pydantic"}
    if libs:
        return {"source": f"imports {sorted(libs)[0]}"}
    sibling = next(skill_path.parent.glob("*.schema.json"), None)
    if sibling is not None:
        return {"source": f"sibling {sibling.name}"}
    return None


# ---------------------------------------------------------------------------
# detection (priority: T1 > T2 > T0 > T5)
# ---------------------------------------------------------------------------


def detect_rung(
    skill_path: str | Path, *, project_root: str | Path | None = None
) -> Detection:
    """Pick the cheapest applicable grader rung for ``skill_path`` (the candidate
    skill module). ``project_root`` defaults to the nearest ancestor with a project
    marker / ``tests`` dir. Static and heuristic — the returned ``caveat`` names what
    the consumer must still confirm."""
    skill_path = Path(skill_path)
    root = _find_project_root(skill_path, Path(project_root) if project_root else None)
    tree = _parse(skill_path)
    fns = _contract_fns(tree) if tree is not None else []
    contract_fn = fns[0] if fns else ""

    # T1 — a pre-existing suite the agent did not author. Requires the skill to live
    # INSIDE the project root, so the candidate can be dropped at its relative path.
    if root is not None and _has_pytest_layout(root):
        try:
            target_path = skill_path.resolve().relative_to(root).as_posix()
            inside = True
        except ValueError:
            target_path, inside = "", False
        if inside:
            test_cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *_pytest_testpaths_from_cfg(root),
            ]
            return Detection(
                rung="T1",
                reason=f"pytest suite at {root}; skill is the in-repo module {target_path}",
                caveat=(
                    "detection found a suite but did NOT verify it exercises this "
                    "skill — confirm the suite covers the target (a suite that passes "
                    "regardless is a vacuous T1 root). Run with --smoke to check the "
                    "current skill passes it."
                ),
                auto_fillable=True,
                params={
                    "project_root": str(root),
                    "target_path": target_path,
                    "test_cmd": test_cmd,
                },
            )

    # T2 — structured output + schema. A proposable property; only a trust root once
    # proven non-vacuous (anti-vacuity gate, separate). Scaffold = proposal.
    if tree is not None:
        schema = _detect_schema(skill_path, tree)
        if schema is not None:
            return Detection(
                rung="T2",
                reason=f"structured output with a schema present ({schema['source']})",
                caveat=(
                    "schema-conformance is an AUTHOR-PROPOSED property — weak until "
                    "proven non-vacuous (mutate the candidate; the property must kill "
                    "the mutants). This is a PROPOSAL to confirm by hand; fill "
                    "SAMPLE_INPUTS and the conformance check, do not auto-pin."
                ),
                auto_fillable=False,
                params={"contract_fn": contract_fn, "schema_source": schema["source"]},
            )

        # T0 — a pure deterministic entrypoint (a contract fn, no nondeterminism src).
        if contract_fn and not (_imported_roots(tree) & _NONDET_ROOTS):
            return Detection(
                rung="T0",
                reason=f"pure deterministic entrypoint {contract_fn!r} (no nondeterminism import)",
                caveat=(
                    "determinism proves only REPRODUCIBILITY, never correctness — a "
                    "wrong-but-deterministic candidate passes. The weakest root; fill "
                    "SAMPLE_INPUTS and confirm this is the criterion you want."
                ),
                auto_fillable=False,
                params={"contract_fn": contract_fn},
            )

    # T5 — nothing cheaper detectable; the general held-out-goldens shape.
    return Detection(
        rung="T5",
        reason="no pre-existing suite, schema, or pure deterministic entrypoint detected",
        caveat=(
            "no cheap root applies — a human must pin held-out instances and a "
            "reference implementation. See examples/interval_grader.py for a worked "
            "grader."
        ),
        auto_fillable=False,
        params={"contract_fn": contract_fn},
    )


# ---------------------------------------------------------------------------
# scaffold templates. T1 delegates to verdict_grader; the T0 (determinism) and T2
# (schema-conformance) PROPERTY templates moved to property_grader.py (the single
# source B's anti-vacuity gate proves against — placeholders=True is byte-identical
# to what we shipped). Only the T5 held-out-goldens shape stays here (not a
# property — nothing for B to mutate).
# ---------------------------------------------------------------------------

_T5_PREAMBLE = '''#!/usr/bin/env python3
"""SCAFFOLDED by relyable init — T5 held-out-goldens grader (HUMAN fills this).

Nothing cheaper was auto-detectable (no pre-existing suite, no schema, no pure
deterministic entrypoint). This is the general re-derivation shape: pin held-out
instances the producer never sees, compute goldens from YOUR reference
implementation, run the candidate, compare. See
relyable/skills/examples/interval_grader.py for a worked example. Fill reference(),
HOLDOUTS, and the comparison. Stdlib only; no relyable/veriker import.
"""
'''

_T5_BODY = '''
import argparse
import ast
import json
import sys
from pathlib import Path


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def reference(*call_args):
    """FILL ME: the consumer's trusted reference implementation of CONTRACT_FN.
    Its output is the golden the candidate must reproduce."""
    raise NotImplementedError("fill reference() before using this grader")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    bundle = Path(ap.parse_args().bundle_dir)

    try:
        body = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    except OSError as e:
        return _fail(f"candidate_unreadable: {e}")
    try:
        ast.parse(body)
    except SyntaxError as e:
        return _fail(f"parse_fail: {e}")
    if not HOLDOUTS:
        return _fail("no HOLDOUTS — fill the scaffold before using this grader")

    ns: dict = {}
    try:
        exec(body, ns)  # noqa: S102 — bundle-code-exec; veriker's gated lane
    except Exception as e:  # noqa: BLE001
        return _fail(f"import_fail: {type(e).__name__}: {e}")
    fn = ns.get(CONTRACT_FN)
    if not callable(fn):
        return _fail(f"no_contract_fn: {CONTRACT_FN!r}")

    for i, call_args in enumerate(HOLDOUTS):
        try:
            golden = reference(*[json.loads(json.dumps(x)) for x in call_args])
            got = fn(*[json.loads(json.dumps(x)) for x in call_args])
        except NotImplementedError:
            return _fail("reference() not filled in")
        except Exception as e:  # noqa: BLE001
            return _fail(f"holdout[{i}] runtime_fail: {type(e).__name__}: {e}")
        if got != golden:
            return _fail(f"holdout[{i}] mismatch: {got!r} != {golden!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _t5_header(contract_fn: str) -> str:
    fn = contract_fn or "REPLACE_WITH_CONTRACT_FN"
    return (
        f"CONTRACT_FN = {fn!r}\n"
        "# FILL ME: held-out instances the producer never sees; each is an args\n"
        "# tuple passed to both reference() and the candidate.\n"
        "HOLDOUTS: list = []\n"
    )


# T0/T2 rungs map onto property_grader kinds (the single source B proves against).
_RUNG_KIND = {"T0": "determinism", "T2": "schema_conformance"}


def make_scaffold_source(detection: Detection) -> str:
    """Return the SOURCE of the grader scaffold for ``detection``. For T1 this is a
    complete, runnable grader (via ``verdict_grader``); T0/T2 delegate to
    ``property_grader`` (placeholders=True confirm-by-hand templates); T5 is the
    stdlib-only held-out-goldens template with clearly-marked FILL-ME sections."""
    if detection.rung == "T1":
        return make_verdict_grader(
            project_root=detection.params["project_root"],
            target_path=detection.params["target_path"],
            test_cmd=detection.params["test_cmd"],
        )
    if detection.rung in _RUNG_KIND:
        return make_property_grader(
            _RUNG_KIND[detection.rung],
            contract_fn=detection.params.get("contract_fn", ""),
            params=detection.params,
            placeholders=True,
        )
    # T5 — held-out goldens; not a property, stays here.
    header = _t5_header(detection.params.get("contract_fn", ""))
    return _T5_PREAMBLE + header + _T5_BODY


def scaffold_grader(
    skill_path: str | Path,
    dest: str | Path,
    *,
    project_root: str | Path | None = None,
) -> ScaffoldResult:
    """Detect the cheapest rung for ``skill_path`` and write its grader scaffold to
    ``dest``. Returns a ``ScaffoldResult`` describing the rung, whether the grader is
    ready to pin (T1) or needs human completion, and the honest caveat."""
    detection = detect_rung(skill_path, project_root=project_root)
    dest = Path(dest)
    dest.write_text(make_scaffold_source(detection), encoding="utf-8")
    if detection.rung == "T1":
        next_step = (
            f"pin {dest.name} as grader_src; run with --smoke (or `relyable-skills "
            "admit`) to confirm the current skill passes the detected suite."
        )
    else:
        next_step = (
            f"fill the FILL-ME sections in {dest.name}, then pin it as grader_src. "
            "This is a PROPOSAL, not a finished trust root."
        )
    return ScaffoldResult(
        rung=detection.rung,
        dest=dest,
        auto_fillable=detection.auto_fillable,
        needs_confirmation=not detection.auto_fillable,
        reason=detection.reason,
        caveat=detection.caveat,
        next_step=next_step,
    )
