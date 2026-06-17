"""anti_vacuity.py — prove an author-proposed property is NON-VACUOUS (B).

An agent may PROPOSE a property as its acceptance criterion (round-trip,
idempotence, schema-conformance) without a human hand-authoring goldens. But a
property no broken candidate can fail asserts nothing — it would admit anything.
This gate certifies a property is non-vacuous the only honest way: drive a REAL
mutation engine (mutmut) over the reference candidate, and require the property
(run as a test) to KILL the mutants. A mutant the property still passes is a
survivor — direct evidence the property/inputs assert too little.

HONEST CATCH: kills-mutants proves NON-VACUOUS, not correct-spec. It's an
anti-vacuity gate, not a correctness oracle (the property is anchored to the
candidate-at-proposal-time as pseudo-ground-truth). T2 stays genuinely weaker than
T1.

PLACEMENT: this runs ONCE, at the moment a consumer ACCEPTS a proposed property —
it emits a scope-bound ``VacuityCertificate`` (reference-candidate digest + engine
+ floor + mutmut version + mutant count). It is NOT a per-admission leg; reuse of
the certified grader outside its recorded scope is visible on the cert, not
silently assumed.

FAIL-CLOSED: mutmut absent, an engine crash, or a ZERO-mutant run all yield
``ok=False`` — an anti-vacuity proof that cannot actually measure survivors must
BLOCK, never wave the property through. ``determinism`` is rejected up front: it
near-universally survives mutation (a wrong-but-deterministic mutant still passes
``f(x) == f(x)``), so it is not provable and stays a confirm-by-hand T0 template.

The engine-run step is dependency-injectable (``run_engine``) so the cert-assembly
and fail-closed logic are unit-tested against a RECORDED mutmut report with no
binary installed; one live end-to-end test drives real mutmut.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from relyable.verdicts.ratchets.mutation import (
    MutationEngineError,
    MutationReport,
    MutmutAdapter,
)

from .property_grader import PROVABLE_KINDS, property_predicate_source

#: The honest catch, carried verbatim on every B surface (here, the cert field).
HONEST_CATCH = (
    "kills-mutants proves NON-VACUOUS, not correct-spec. It's an anti-vacuity "
    "gate, not a correctness oracle (the property is anchored to the "
    "candidate-at-proposal-time as pseudo-ground-truth). T2 stays genuinely "
    "weaker than T1."
)

# mutmut config the harness writes: mutate only the reference candidate.
_SETUP_CFG = "[mutmut]\npaths_to_mutate=candidate.py\n"

# The literals a CONCRETE grader bakes in (placeholders=False) — the single source
# the synthesized test reuses, so the test proves exactly what the grader checks.
_BAKED = ("KIND", "CONTRACT_FN", "INVERSE_FN", "SCHEMA", "SAMPLE_INPUTS")


@dataclass(frozen=True, slots=True)
class EngineResult:
    """One mutation-engine run: the parsed report + the engine version (stamped on
    the cert)."""

    report: MutationReport
    version: str


@dataclass(frozen=True, slots=True)
class VacuityCertificate:
    """Scope-bound attestation that a property is non-vacuous for ONE reference
    candidate. ``ok`` is True iff survivors are within the floor AND at least one
    mutant was produced (a zero-mutant run is a BLOCK, never a pass)."""

    ok: bool
    kind: str
    killed: int
    total: int
    max_survivors: int
    survivors: tuple[str, ...]
    reference_digest: str  # sha256 of the reference candidate body (scope binding)
    mutmut_version: str  # version stamp
    engine: str = "mutmut"
    reason: str = ""
    honest_catch: str = HONEST_CATCH


# ---------------------------------------------------------------------------
# default engine runner (real mutmut) — injectable for unit tests
# ---------------------------------------------------------------------------


def _default_run_engine(
    workspace: Path, *, mutmut_binary: str, timeout: float
) -> EngineResult:
    """Shell real mutmut over the workspace and stamp its version. Reuses the
    verdicts MutmutAdapter (``mutmut run`` then ``mutmut results --all true``,
    parsed by parse_mutmut_results), which already fails closed on an absent binary
    or a zero-mutant run."""
    report = MutmutAdapter().run(
        workspace, paths=[], timeout=timeout, params={"mutmut_binary": mutmut_binary}
    )
    try:
        version = importlib.metadata.version("mutmut")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return EngineResult(report=report, version=version)


RunEngine = Callable[..., EngineResult]


# ---------------------------------------------------------------------------
# harness: extract the grader's baked literals; synthesize the property test
# ---------------------------------------------------------------------------


def _extract_grader_literals(grader_src: str) -> dict:
    """Pull the baked literals out of a CONCRETE grader via AST (no exec). A
    placeholders=True grader lacks them (its SAMPLE_INPUTS is an annotated empty
    assign) — that raises, refusing to prove a FILL-ME template."""
    try:
        tree = ast.parse(grader_src)
    except SyntaxError as exc:
        raise ValueError(f"grader_src is not parseable: {exc}") from exc
    out: dict = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in _BAKED
        ):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
    missing = [name for name in _BAKED if name not in out]
    if missing:
        raise ValueError(
            f"grader_src missing baked literals {missing} — pass a CONCRETE grader "
            "(make_property_grader(..., placeholders=False)), not a FILL-ME template"
        )
    return out


def _build_test_source(kind: str, literals: dict) -> str:
    """Synthesize test_property.py: import the contract fn(s) from candidate.py,
    embed property_predicate_source(kind) (THE single source), and assert the
    predicate over the grader's baked inputs. mutmut runs this against each
    mutant; a mutant the predicate still passes survives."""
    contract_fn = str(literals["CONTRACT_FN"])
    inverse_fn = str(literals["INVERSE_FN"]) if kind == "round_trip" else ""
    imports = f"from candidate import {contract_fn}"
    if inverse_fn:
        imports += f", {inverse_fn}"
    inverse_ref = inverse_fn if inverse_fn else "None"
    return "".join(
        [
            "import json\n",
            f"{imports}\n",
            property_predicate_source(kind),
            f"\nSCHEMA = {literals['SCHEMA']!r}\n",
            f"INPUTS = {list(literals['SAMPLE_INPUTS'])!r}\n\n",
            "def test_property():\n",
            "    assert INPUTS, 'no inputs baked'\n",
            "    for call_args in INPUTS:\n",
            "        args = [json.loads(json.dumps(x)) for x in call_args]\n",
            f"        assert property_holds({contract_fn}, {inverse_ref}, SCHEMA, args)\n",
        ]
    )


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def prove_non_vacuous(
    grader_src: str,
    reference_candidate: str,
    *,
    kind: str,
    max_survivors: int = 0,
    mutmut_binary: str = "mutmut",
    timeout: float = 1800.0,
    run_engine: RunEngine | None = None,
) -> VacuityCertificate:
    """Prove the property in ``grader_src`` is non-vacuous against
    ``reference_candidate`` and return a scope-bound ``VacuityCertificate``.

    ``grader_src`` MUST be a concrete grader (make_property_grader with
    placeholders=False) — its baked CONTRACT_FN / INVERSE_FN / SCHEMA /
    SAMPLE_INPUTS drive the synthesized property test, so the cert proves exactly
    what the grader checks. ``determinism`` is rejected up front (not provable).
    Mutmut absent / crash / zero-mutant all return ``ok=False`` (fail-closed)."""
    if kind == "determinism":
        raise ValueError(
            "determinism is not a provable property — it near-universally survives "
            "mutation (a wrong-but-deterministic mutant still passes f(x)==f(x)); it "
            "stays a confirm-by-hand T0 template, never an anti-vacuity cert"
        )
    if kind not in PROVABLE_KINDS:
        raise ValueError(
            f"unknown/unprovable property kind {kind!r}; provable: {list(PROVABLE_KINDS)}"
        )
    runner = run_engine or _default_run_engine

    digest = hashlib.sha256(reference_candidate.encode("utf-8")).hexdigest()
    literals = _extract_grader_literals(grader_src)
    if literals["KIND"] != kind:
        raise ValueError(
            f"grader_src KIND={literals['KIND']!r} does not match kind={kind!r}"
        )
    test_src = _build_test_source(kind, literals)

    def _blocked(reason: str, version: str = "") -> VacuityCertificate:
        return VacuityCertificate(
            ok=False,
            kind=kind,
            killed=0,
            total=0,
            max_survivors=max_survivors,
            survivors=(),
            reference_digest=digest,
            mutmut_version=version,
            reason=reason,
        )

    try:
        with tempfile.TemporaryDirectory(prefix="relyable-vacuity-") as td:
            ws = Path(td)
            (ws / "candidate.py").write_text(reference_candidate, encoding="utf-8")
            (ws / "test_property.py").write_text(test_src, encoding="utf-8")
            (ws / "setup.cfg").write_text(_SETUP_CFG, encoding="utf-8")
            result = runner(ws, mutmut_binary=mutmut_binary, timeout=timeout)
    except MutationEngineError as exc:
        return _blocked(f"mutation engine BLOCK: {exc}")

    report = result.report
    if report.total == 0:
        return _blocked("zero mutants produced — BLOCK", result.version)
    ok = report.survived <= max_survivors
    reason = (
        ""
        if ok
        else f"{report.survived} survivor(s) > max {max_survivors} — property is vacuous"
    )
    return VacuityCertificate(
        ok=ok,
        kind=kind,
        killed=report.killed,
        total=report.total,
        max_survivors=max_survivors,
        survivors=report.surviving,
        reference_digest=digest,
        mutmut_version=result.version,
        reason=reason,
    )
