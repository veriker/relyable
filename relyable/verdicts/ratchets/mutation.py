"""mutation — survivors of a real mutation engine may not exceed a floor.

The strongest anti-gaming lever, and the most expensive: it drives a REAL
mutation-testing engine (mutmut for Python, Stryker for JS/TS), which perturbs
the source and re-runs the suite per mutant. A mutant the suite still passes is a
*survivor* — direct evidence of a test that asserts nothing useful (the
tautological / assertion-free test no_shrink and diff_coverage cannot see, since
those tests run and "pass"). The ratchet fails when survivors exceed
`max_survivors`.

Opt-in and slow by design (default-disabled; minutes, not seconds) — wire it as
a CI-nightly or pre-merge gate, not an inner-loop check.

The ratchet shells the engine and parses ITS native report; it does not
re-implement mutation. Two adapters ship:

  * mutmut (Python): `mutmut run` then `mutmut results --all true`, whose
    `<mutant-id>: <status>` lines are classified (survived / no_tests are
    survivors; killed is detected). [verified against mutmut 3.6]
  * Stryker (JS/TS): reads the mutation-testing-elements JSON report
    (`reports/mutation/mutation.json` by default), classifying each mutant's
    `status` (Survived / NoCoverage are survivors; Killed / Timeout are
    detected).

Fail-closed: an absent engine binary, an engine crash, a missing/malformed
report, or a degenerate "no mutants produced" run all return `ok=False` — an
enabled mutation guard that cannot actually measure survivors must BLOCK, never
wave the change through. (`inactive` is reserved for an unset baseline; a guard
the policy asked for that cannot run is a failure, not an absence.)

Config (honesty.toml):

    [ratchets]
    mutation = { enabled = true, engine = "mutmut", max_survivors = 0, \
                 paths = ["relyable/verdicts"], timeout_seconds = 1800 }

Stdlib only (each adapter shells its engine; no pip dependency on either).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import RatchetContext, RatchetResult

# --- mutmut status vocabulary (verified against mutmut 3.6 `results` output) ---
# A survivor is a mutant the suite failed to detect; "no tests" means no test
# even exercised the mutated line — survivor-equivalent for our purposes.
_MUTMUT_SURVIVOR = frozenset({"survived", "no_tests"})
_MUTMUT_KILLED = frozenset({"killed"})
_MUTMUT_KNOWN = frozenset(
    {
        "killed",
        "survived",
        "no_tests",
        "timeout",
        "suspicious",
        "skipped",
        "caught_by_type_check",
        "segfault",
        "check_was_interrupted_by_user",
    }
)

# --- Stryker (mutation-testing-elements) status vocabulary ---
_STRYKER_SURVIVOR = frozenset({"Survived", "NoCoverage"})
_STRYKER_KILLED = frozenset({"Killed", "Timeout"})


class MutationEngineError(Exception):
    """The mutation engine could not be run or its report could not be read.
    Fail-closed: the ratchet turns this into a BLOCK."""


@dataclass(frozen=True, slots=True)
class MutationReport:
    killed: int
    survived: int
    total: int
    surviving: tuple[str, ...] = field(default_factory=tuple)


class MutationEngine(Protocol):
    def run(
        self,
        workspace: Path,
        *,
        paths: list[str],
        timeout: float,
        params: dict[str, Any],
    ) -> MutationReport: ...


# ---------------------------------------------------------------------------
# report parsers (pure; the tests drive these against recorded fixtures)
# ---------------------------------------------------------------------------


def parse_mutmut_results(text: str) -> MutationReport:
    """Parse `mutmut results --all true` output into a MutationReport.

    Each result line is ``    <mutant-id>: <status>``. Lines whose trailing token
    is not a known mutmut status (warnings, banners) are ignored, so the parser
    is robust to deprecation noise on stdout.
    """
    statuses: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        mid, status = line.rsplit(":", 1)
        mid = mid.strip()
        norm = status.strip().lower().replace(" ", "_")
        if not mid or norm not in _MUTMUT_KNOWN:
            continue
        statuses[mid] = norm

    survivors = sorted(m for m, s in statuses.items() if s in _MUTMUT_SURVIVOR)
    killed = sum(1 for s in statuses.values() if s in _MUTMUT_KILLED)
    return MutationReport(
        killed=killed,
        survived=len(survivors),
        total=len(statuses),
        surviving=tuple(survivors),
    )


def parse_stryker_json(data: str | bytes | dict) -> MutationReport:
    """Parse a Stryker mutation-testing-elements JSON report into a
    MutationReport. Raises MutationEngineError (fail-closed) on a malformed
    report."""
    if isinstance(data, (str, bytes)):
        try:
            doc = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MutationEngineError(
                f"Stryker report is not valid JSON: {exc}"
            ) from exc
    else:
        doc = data
    if not isinstance(doc, dict):
        raise MutationEngineError("Stryker report root is not an object")
    files = doc.get("files")
    if not isinstance(files, dict):
        raise MutationEngineError("Stryker report has no 'files' object")

    killed = 0
    survivors: list[str] = []
    for path, fdata in files.items():
        if not isinstance(fdata, dict):
            continue
        for m in fdata.get("mutants", []) or []:
            if not isinstance(m, dict):
                continue
            status = m.get("status")
            if status in _STRYKER_KILLED:
                killed += 1
            elif status in _STRYKER_SURVIVOR:
                line = (
                    (m.get("location") or {}).get("start", {}).get("line", "?")
                    if isinstance(m.get("location"), dict)
                    else "?"
                )
                survivors.append(
                    f"{path}:{line}:{m.get('mutatorName', '?')}#{m.get('id', '?')}"
                )
            # CompileError / RuntimeError / Ignored / Pending are not a
            # test-quality signal; excluded from killed, survivors, and total.
    survivors.sort()
    return MutationReport(
        killed=killed,
        survived=len(survivors),
        total=killed + len(survivors),
        surviving=tuple(survivors),
    )


# ---------------------------------------------------------------------------
# engine adapters (shell the engine, then parse)
# ---------------------------------------------------------------------------


def _shell(
    cmd: list[str], workspace: Path, timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — fixed argv, no shell
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise MutationEngineError(f"{cmd[0]!r} not found on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MutationEngineError(
            f"{cmd[0]!r} timed out after {timeout}s: {exc}"
        ) from exc


class MutmutAdapter:
    """Drive mutmut (Python). Source paths come from mutmut's own config
    (setup.cfg / pyproject `[mutmut] source_paths`); the ratchet's `paths` is not
    forwarded here, since mutmut selects mutants from its config, not argv."""

    def run(
        self,
        workspace: Path,
        *,
        paths: list[str],
        timeout: float,
        params: dict[str, Any],
    ) -> MutationReport:
        binary = str(params.get("mutmut_binary", "mutmut"))
        # `mutmut run` returns 0 even with survivors, so the report — not the exit
        # code — is authoritative. A FileNotFoundError (binary absent) raises.
        _shell([binary, "run"], workspace, timeout)
        results = _shell([binary, "results", "--all", "true"], workspace, timeout)
        report = parse_mutmut_results(results.stdout)
        if report.total == 0:
            raise MutationEngineError(
                "mutmut produced no mutants — check that it ran and that "
                "[mutmut] source_paths points at code to mutate"
            )
        return report


class StrykerAdapter:
    """Drive Stryker (JS/TS) and read its JSON report."""

    def run(
        self,
        workspace: Path,
        *,
        paths: list[str],
        timeout: float,
        params: dict[str, Any],
    ) -> MutationReport:
        report_rel = str(params.get("stryker_report", "reports/mutation/mutation.json"))
        binary = str(params.get("stryker_binary", "npx"))
        # `npx stryker run`, or `<binary> run` for a direct stryker executable.
        cmd = [binary, "stryker", "run"] if binary == "npx" else [binary, "run"]
        if paths:
            cmd += ["--mutate", ",".join(paths)]
        _shell(cmd, workspace, timeout)
        report_file = (workspace / report_rel).resolve()
        if not report_file.is_file():
            raise MutationEngineError(
                f"Stryker report not found at {report_rel!r} after the run — "
                "ensure the 'json' reporter is enabled"
            )
        try:
            data = report_file.read_bytes()
        except OSError as exc:
            raise MutationEngineError(f"Stryker report unreadable: {exc}") from exc
        return parse_stryker_json(data)


_ENGINES: dict[str, Any] = {
    "mutmut": MutmutAdapter,
    "stryker": StrykerAdapter,
}


# ---------------------------------------------------------------------------
# the ratchet
# ---------------------------------------------------------------------------


class Mutation:
    name = "mutation"

    def check(self, ctx: RatchetContext) -> RatchetResult:
        params = ctx.config.ratchet_params(self.name)
        engine_name = str(params.get("engine", "mutmut"))
        max_survivors = int(params.get("max_survivors", 0))
        raw_paths = params.get("paths", [])
        paths = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else []
        timeout = float(params.get("timeout_seconds", 1800))
        max_listed = int(params.get("max_listed", 20))

        factory = _ENGINES.get(engine_name)
        if factory is None:
            return RatchetResult(
                self.name,
                ok=False,
                detail=(
                    f"unknown mutation engine {engine_name!r}; "
                    f"known: {sorted(_ENGINES)}"
                ),
            )

        try:
            report = factory().run(
                ctx.workspace, paths=paths, timeout=timeout, params=params
            )
        except MutationEngineError as exc:
            return RatchetResult(
                self.name,
                ok=False,
                detail=f"mutation engine {engine_name!r} failed: {exc}",
            )

        if report.survived > max_survivors:
            shown = list(report.surviving[:max_listed])
            more = (
                ""
                if len(report.surviving) <= max_listed
                else f" (+{len(report.surviving) - max_listed} more)"
            )
            return RatchetResult(
                self.name,
                ok=False,
                detail=(
                    f"{report.survived} mutant(s) survived > max {max_survivors} "
                    f"({report.killed}/{report.total} killed, engine={engine_name}); "
                    f"survivors: {shown}{more}"
                ),
            )
        return RatchetResult(
            self.name,
            ok=True,
            detail=(
                f"{report.killed}/{report.total} mutants killed; "
                f"{report.survived} survived (<= max {max_survivors}, "
                f"engine={engine_name})"
            ),
        )
