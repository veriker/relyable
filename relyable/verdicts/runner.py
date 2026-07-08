"""runner.py — the chokepoint. The gate runs the suite ITSELF and derives the
verdict; the agent's "all tests pass" is never an input here.

This is the enforcement core. Given an anchored test command and the report path
that command writes, `run_suite`:

  1. DELETES the report path first, so a stale green report left in the tree
     cannot be mistaken for this run's result (a real gaming vector — "don't
     actually run, leave yesterday's passing report").
  2. Executes the command behind a `Sandbox`.
  3. Parses the JUnit report it produced into a `TestVerdict`.
  4. Optionally re-runs to absorb FLAKINESS — but the retry budget is gate-owned
     (read from anchored config, never from the agent), and the default is 0
     (strict). With reruns > 0 a test is "passed" if it passed in ANY run and
     "failed/errored" only if it appeared and NEVER passed — the standard
     best-of-N flaky policy, applied by the gate, not the suite.

Fail-closed everywhere: a missing report, a non-XML report, a command crash with
no report, or a timeout all yield `verdict=None` and `conclusive=False`. The
gate treats a non-conclusive run as NON-green. A run is only "ok" when it
conclusively produced a green verdict.

The command itself is trusted because it comes from the anchored config
(config.py) — the agent cannot swap `pytest` for `echo pass` without tripping
the config anchor. This module assumes that and just executes.

Stdlib only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import ExecResult, Sandbox, SubprocessSandbox
from .verdict import (
    OUTCOME_ERRORED,
    OUTCOME_FAILED,
    OUTCOME_PASSED,
    OUTCOME_SKIPPED,
    TestCase,
    TestVerdict,
    VerdictParseError,
    parse_junit_xml,
)

# Precedence when merging a test id's outcome across reruns: a PASS anywhere
# wins (flaky tolerance); else the worst seen. Lower number = better.
_OUTCOME_RANK = {
    OUTCOME_PASSED: 0,
    OUTCOME_SKIPPED: 1,
    OUTCOME_FAILED: 2,
    OUTCOME_ERRORED: 3,
}


@dataclass(frozen=True, slots=True)
class RunResult:
    verdict: TestVerdict | None
    conclusive: bool
    reason: str
    runs: int = 0
    exit_codes: tuple[int, ...] = field(default_factory=tuple)
    flaky_ids: tuple[str, ...] = field(default_factory=tuple)
    report_path: str = ""
    stderr_tail: str = ""

    @property
    def ok(self) -> bool:
        """Conclusively green: a real run produced a verdict and it is green."""
        return self.conclusive and self.verdict is not None and self.verdict.green


def _tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if text and len(text) > limit else (text or "")


def _read_report(report_file: Path) -> TestVerdict:
    if not report_file.is_file():
        raise VerdictParseError(
            f"no report produced at {report_file} — the command did not run or "
            "did not write the configured report path"
        )
    return parse_junit_xml(report_file.read_bytes())


def _merge_runs(verdicts: Sequence[TestVerdict]) -> tuple[TestVerdict, list[str]]:
    """Best-of-N merge across rerun verdicts. A test id resolves to its BEST
    outcome across runs (a pass anywhere wins). An id that failed/errored in some
    run but passed in another is reported `flaky`. Returns (merged, flaky_ids)."""
    best: dict[str, str] = {}
    worst: dict[str, str] = {}
    duration: dict[str, float] = {}
    for v in verdicts:
        for c in v.cases:
            if c.id not in best or _OUTCOME_RANK[c.outcome] < _OUTCOME_RANK[best[c.id]]:
                best[c.id] = c.outcome
            if (
                c.id not in worst
                or _OUTCOME_RANK[c.outcome] > _OUTCOME_RANK[worst[c.id]]
            ):
                worst[c.id] = c.outcome
            duration[c.id] = max(duration.get(c.id, 0.0), c.duration_s)
    flaky = sorted(
        cid
        for cid in best
        if best[cid] == OUTCOME_PASSED
        and worst[cid] in (OUTCOME_FAILED, OUTCOME_ERRORED)
    )
    merged = TestVerdict.from_cases(
        tuple(
            TestCase(id=cid, outcome=best[cid], duration_s=duration[cid])
            for cid in sorted(best)
        )
    )
    return merged, flaky


def run_suite(
    workspace: Path,
    command: Sequence[str],
    report_path: str,
    *,
    sandbox: Sandbox | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    max_reruns: int = 0,
) -> RunResult:
    """Run the configured suite and return the gate's authoritative result.

    `report_path` is relative to `workspace`. `max_reruns` is the gate-owned
    flaky budget (0 = strict; default). Reruns stop early once a fully green
    merge is reached.
    """
    workspace = workspace.resolve()
    sandbox = sandbox or SubprocessSandbox()
    report_file = (workspace / report_path).resolve()

    # Containment: the configured report path must stay inside the workspace.
    try:
        report_file.relative_to(workspace)
    except ValueError:
        return RunResult(
            verdict=None,
            conclusive=False,
            reason=f"report_path {report_path!r} resolves outside the workspace",
            report_path=report_path,
        )

    verdicts: list[TestVerdict] = []
    exit_codes: list[int] = []
    last_stderr = ""
    attempts = max(1, max_reruns + 1)

    for _attempt in range(attempts):
        # (1) Stale-report defense: this run must produce its own report.
        try:
            if report_file.exists():
                report_file.unlink()
        except OSError as exc:
            return RunResult(
                verdict=None,
                conclusive=False,
                reason=f"could not clear stale report {report_file}: {exc}",
                runs=len(verdicts),
                exit_codes=tuple(exit_codes),
                report_path=report_path,
            )

        # (2) Execute behind the sandbox.
        res: ExecResult = sandbox.run(command, cwd=workspace, env=env, timeout=timeout)
        exit_codes.append(res.returncode)
        last_stderr = res.stderr

        if res.timed_out:
            return RunResult(
                verdict=None,
                conclusive=False,
                reason=f"test command timed out after {timeout}s",
                runs=len(verdicts) + 1,
                exit_codes=tuple(exit_codes),
                report_path=report_path,
                stderr_tail=_tail(res.stderr),
            )

        # (3) Parse the report THIS run produced.
        try:
            verdicts.append(_read_report(report_file))
        except VerdictParseError as exc:
            return RunResult(
                verdict=None,
                conclusive=False,
                reason=str(exc),
                runs=len(verdicts) + 1,
                exit_codes=tuple(exit_codes),
                report_path=report_path,
                stderr_tail=_tail(res.stderr),
            )

        # Early exit once a green result is in hand (no need to spend reruns).
        if verdicts[-1].green:
            break

    merged, flaky = _merge_runs(verdicts)
    reason = "green" if merged.green else f"non-green: {merged.summary()}"
    if flaky:
        reason += f"; flaky (passed on rerun): {len(flaky)}"
    return RunResult(
        verdict=merged,
        conclusive=True,
        reason=reason,
        runs=len(verdicts),
        exit_codes=tuple(exit_codes),
        flaky_ids=tuple(flaky),
        report_path=report_path,
        stderr_tail=_tail(last_stderr),
    )
