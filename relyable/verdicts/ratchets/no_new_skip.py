"""no_new_skip — no test may newly become skipped versus the baseline.

Skipping a failing test is the laziest way to make a suite "pass". This ratchet
fails closed when a test id is skipped now but was not skipped in the baseline.
(Marking a test skipped, `@pytest.mark.skip`, `it.skip`, `t.Skip`, `xfail` that
the framework reports as skipped — all surface as a skipped outcome in the
JUnit report, so this is framework-agnostic.)

An allowlist of intentionally-skipped ids can be declared in honesty.toml:

    [ratchets]
    no_new_skip = { allow = ["pkg::test_known_slow"] }

Inactive (not a pass) when there is no baseline.
"""

from __future__ import annotations

from . import RatchetContext, RatchetResult
from ..verdict import OUTCOME_SKIPPED


class NoNewSkip:
    name = "no_new_skip"

    def check(self, ctx: RatchetContext) -> RatchetResult:
        if ctx.baseline is None:
            return RatchetResult(
                self.name,
                ok=True,
                detail="no baseline — new-skip protection inactive",
                inactive=True,
            )

        allow = set(ctx.config.ratchet_params("no_new_skip").get("allow", []))
        current_skipped = ctx.verdict.ids_with_outcome(OUTCOME_SKIPPED)
        new_skips = current_skipped - ctx.baseline.skipped_ids - allow

        if new_skips:
            shown = sorted(new_skips)[:8]
            more = "" if len(new_skips) <= 8 else f" (+{len(new_skips) - 8} more)"
            return RatchetResult(
                self.name,
                ok=False,
                detail=(
                    f"{len(new_skips)} test(s) newly skipped vs baseline: "
                    f"{shown}{more} (allowlist them in [ratchets].no_new_skip.allow "
                    "if intentional)"
                ),
            )
        return RatchetResult(self.name, ok=True, detail="no new skips vs baseline")
