"""no_shrink — the suite (and coverage) may not drop below the baseline.

The single most valuable, most general anti-gaming guard, and it needs no
mutation engine. It fails closed when, versus the committed baseline:
  - the total test count dropped, OR
  - a test that was passing is no longer passing (deleted, renamed away, or
    flipped to skipped/failed) — caught by passing-id set subset, which is
    stricter than a count and catches "delete one real test, add one trivial
    test" (count unchanged), OR
  - coverage percent dropped (only when both baseline and current coverage are
    known; otherwise that sub-check is skipped, not failed).

Inactive (not a pass) when there is no baseline — the gate surfaces that so a
reviewer knows the floor is unset.
"""

from __future__ import annotations

from . import RatchetContext, RatchetResult

# Coverage comparison tolerance (percentage points) — floating-point slack only.
_COVERAGE_EPSILON = 1e-6


class NoShrink:
    name = "no_shrink"

    def check(self, ctx: RatchetContext) -> RatchetResult:
        if ctx.baseline is None:
            return RatchetResult(
                self.name,
                ok=True,
                detail="no baseline — shrink protection inactive (establish one)",
                inactive=True,
            )

        base = ctx.baseline
        cur = ctx.verdict
        problems: list[str] = []

        if cur.total < base.total:
            problems.append(f"test count {cur.total} < baseline {base.total}")

        removed = base.passing_ids - cur.passing_ids
        if removed:
            shown = sorted(removed)[:8]
            more = "" if len(removed) <= 8 else f" (+{len(removed) - 8} more)"
            problems.append(
                f"{len(removed)} previously-passing test(s) no longer passing: "
                f"{shown}{more}"
            )

        cur_cov = ctx.config.ratchet_params("no_shrink").get("_current_coverage")
        # The gate injects measured coverage under this key when available; if
        # absent, coverage shrink is simply not evaluated here.
        if (
            base.coverage_percent is not None
            and isinstance(cur_cov, (int, float))
            and float(cur_cov) + _COVERAGE_EPSILON < base.coverage_percent
        ):
            problems.append(
                f"coverage {float(cur_cov):.2f}% < baseline {base.coverage_percent:.2f}%"
            )

        if problems:
            return RatchetResult(self.name, ok=False, detail="; ".join(problems))
        return RatchetResult(
            self.name,
            ok=True,
            detail=f"no shrink vs baseline ({base.total} test(s))",
        )
