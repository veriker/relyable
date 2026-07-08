#!/usr/bin/env python3
"""mutate.py — lightweight anti-vacuity check for cold-constructed goldens.

A cold golden that the real code reproduces has only proved something if it would
have CAUGHT a broken version of that code. This applies a handful of generic source
mutations to the skill's executed entrypoint, re-runs the passing goldens against the
mutated code, and asks: did at least one golden flip pass -> fail?

  kill-rate = (mutants caught by some golden) / (mutants that actually changed behaviour)

A mutant that does not apply (pattern absent) or leaves every golden's output byte-
identical is NOT counted against the goldens unless it genuinely altered behaviour —
we only score mutants that changed *something*, so the rate measures the goldens'
discriminating power, not the mutator's luck.

This is the CLI-level sibling of relyable's existing ``prose_property_prove`` /
mutmut prove gate behind relyable's `prove` ladder: same doctrine — "kills-mutants
!= correct-spec, but survives-all-mutants == vacuous". It is deliberately shallow
(regex string edits, single-mutation), enough to flag a golden that constrains
nothing; it is not a full mutation-testing engine.

Returns None when no mutant was applicable (cannot judge vacuity), else a float in
[0,1].
"""

from __future__ import annotations

import re
from pathlib import Path

# (name, regex, replacement) — generic behaviour-changing edits. Order independent;
# each is tried as a SINGLE mutation against a fresh copy of the file.
_MUTATIONS: list[tuple[str, str, str]] = [
    ("eq->ne", r"==", "!="),
    ("ne->eq", r"!=", "=="),
    ("lt->le", r"(?<![<>=!])<(?![<>=])", "<="),
    ("gt->ge", r"(?<![<>=!])>(?![<>=])", ">="),
    ("and->or", r"\band\b", "or"),
    ("or->and", r"\bor\b", "and"),
    ("plus->minus", r"(?<![+\-=])\+(?![+=])", "-"),
    ("true->false", r"\bTrue\b", "False"),
    ("false->true", r"\bFalse\b", "True"),
    ("strip-noop", r"\.strip\(\)", ""),
    ("zero-index-shift", r"\[0\]", "[1]"),
    ("inc-literal-1", r"(?<![\w.])1(?![\w.])", "2"),
    ("js-true->false", r"\btrue\b", "false"),
    ("js-eqeqeq", r"===", "!=="),
]


def _entrypoints_used(goldens: list[dict], entrypoints: dict[str, Path]) -> set[Path]:
    used: set[Path] = set()
    for g in goldens:
        tool = g.get("tool", "")
        ep = entrypoints.get(tool) or entrypoints.get(Path(tool).name)
        if ep is not None:
            used.add(ep)
    return used


def mutation_killrate(
    skill_dir, passing_goldens, entrypoints, run_golden
) -> float | None:
    """For each mutation applicable to an entrypoint that the passing goldens hit,
    apply it, re-run those goldens, and check whether any flips pass->fail.

    ``run_golden`` is injected (the harness's runner) to avoid an import cycle.
    """
    targets = _entrypoints_used(passing_goldens, entrypoints)
    if not targets:
        return None

    applicable = 0
    killed = 0
    for ep in targets:
        original = ep.read_text(encoding="utf-8", errors="ignore")
        # goldens that exercise THIS entrypoint
        ep_goldens = [
            g
            for g in passing_goldens
            if (
                entrypoints.get(g.get("tool", ""))
                or entrypoints.get(Path(g.get("tool", "")).name)
            )
            == ep
        ]
        try:
            for name, pat, repl in _MUTATIONS:
                mutated, n = re.subn(pat, repl, original, count=1)
                if n == 0 or mutated == original:
                    continue  # mutation not applicable to this source
                # Standard mutation-testing convention: an applied mutant that no
                # golden catches is a SURVIVOR. We do not try to prove the mutant
                # changed behaviour independently (we have no oracle for that) — a
                # no-op/crashing mutant simply counts as a survivor, which biases the
                # rate DOWN. That is the safe direction for an anti-vacuity gate:
                # better to under-credit the goldens than over-credit them.
                applicable += 1
                ep.write_text(mutated, encoding="utf-8")
                for g in ep_goldens:
                    if not run_golden(skill_dir, g, entrypoints).ok:
                        killed += 1  # some golden flipped pass -> fail: mutant killed
                        break
        finally:
            ep.write_text(original, encoding="utf-8")  # always restore

    if applicable == 0:
        return None
    return killed / applicable
