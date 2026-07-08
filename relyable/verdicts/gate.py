"""gate.py — evaluate(): the top-level decision.

Composes the pieces into one fail-closed verdict:

    anchor check  -> the gate's own policy was not silently weakened
    run_suite     -> the gate runs the suite ITSELF (claim never trusted)
    conclusive    -> a non-conclusive run is never a pass
    green         -> no test failed or errored, and at least one ran
    ratchets      -> the change did not shrink / skip / uncover / let mutants live

`ok` is the AND of: anchor satisfied, run conclusive, verdict green, every active
ratchet ok. Inactive ratchets (no baseline) surface but do not block, so a first
run can establish a baseline.

The result is a plain dataclass the CLI prints, the MCP tool returns, and the
audit-emit layer turns into a re-derivable bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .baseline import read_baseline
from .config import GateConfig, compute_anchor, verify_anchor
from .ratchets import RatchetContext, RatchetResult, build_enabled
from .runner import RunResult, run_suite
from .sandbox import Sandbox


@dataclass(frozen=True, slots=True)
class GateResult:
    ok: bool
    run: RunResult
    ratchets: tuple[RatchetResult, ...]
    anchor: str
    anchor_pinned: bool
    baseline_present: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        lines: list[str] = []
        head = "PASS" if self.ok else "FAIL"
        lines.append(f"{head}  relyable")
        v = self.run.verdict
        vstate = v.summary() if v is not None else "could not conclude"
        rstate = "OK" if self.run.ok else "FAIL"
        lines.append(f"  {rstate:4}  verdict (gate-run): {vstate} — {self.run.reason}")
        for r in self.ratchets:
            tag = "OK" if r.ok else "FAIL"
            if r.inactive:
                tag = "----"
            lines.append(f"  {tag:4}  ratchet:{r.name}: {r.detail}")
        if not self.anchor_pinned:
            lines.append(
                "  WARN  policy UNPINNED — no expected anchor supplied; "
                f"computed anchor={self.anchor[:16]}…"
            )
        return "\n".join(lines)


def evaluate(
    workspace: Path,
    config: GateConfig,
    *,
    expected_anchor: str | None = None,
    sandbox: Sandbox | None = None,
) -> GateResult:
    workspace = workspace.resolve()
    baseline_file = (workspace / config.baseline_path).resolve()

    # (1) Anchor: refuse a silently-weakened policy. Raises ConfigAnchorMismatch.
    assert config.config_path is not None  # load_config always sets it
    anchor = compute_anchor(config.config_path, baseline_file)
    verify_anchor(anchor, expected_anchor)

    baseline = read_baseline(baseline_file)

    # (2)-(4) Run the suite ourselves; require a conclusive, green verdict.
    run = run_suite(
        workspace,
        config.command,
        config.report_path,
        sandbox=sandbox,
        timeout=config.timeout_seconds,
        max_reruns=config.max_reruns,
    )

    reasons: list[str] = []
    ratchet_results: tuple[RatchetResult, ...] = ()

    if not run.conclusive:
        reasons.append(f"run could not conclude: {run.reason}")
    elif not run.ok:
        reasons.append(f"verdict not green: {run.reason}")

    # (5) Ratchets only run on a conclusive verdict (need real per-test detail).
    if run.conclusive and run.verdict is not None:
        ctx = RatchetContext(
            workspace=workspace,
            verdict=run.verdict,
            baseline=baseline,
            config=config,
        )
        results = []
        for ratchet in build_enabled(config):
            res = ratchet.check(ctx)
            results.append(res)
            if not res.ok:
                reasons.append(f"ratchet {res.name} failed: {res.detail}")
        ratchet_results = tuple(results)

    ok = run.ok and all(r.ok for r in ratchet_results)
    return GateResult(
        ok=ok,
        run=run,
        ratchets=ratchet_results,
        anchor=anchor,
        anchor_pinned=expected_anchor is not None,
        baseline_present=baseline is not None,
        reasons=tuple(reasons),
    )
