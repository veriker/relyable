"""ratchets — the anti-gaming layer.

A ratchet is a fail-closed check that the change did not WEAKEN the suite, even
when the verdict itself is green. The verdict catches the lie ("tests pass" when
they don't); ratchets catch the gaming ("write tests that pass instead of code
that passes tests"): deleting assertions, dropping tests, skipping, uncovering
new lines, or letting mutants survive.

Each ratchet is small, language-agnostic where possible, reads a committed
baseline the gate owns, and fails closed. The registry lets the gate enable
ratchets by name from honesty.toml.

Shipped here: no_shrink, no_new_skip (cheap, general, no engine needed),
diff_coverage (needs a coverage report + git), and mutation (opt-in, slow; drives
a real mutmut / Stryker engine behind the gate).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..baseline import Baseline
from ..config import GateConfig
from ..verdict import TestVerdict


@dataclass(frozen=True, slots=True)
class RatchetContext:
    workspace: Path
    verdict: TestVerdict
    baseline: Baseline | None
    config: GateConfig


@dataclass(frozen=True, slots=True)
class RatchetResult:
    name: str
    ok: bool
    detail: str
    # inactive: the ratchet could not run (e.g. no baseline) — surfaced, not a
    # silent pass. The gate decides whether inactive blocks (default: warn, allow
    # on first run so a baseline can be established).
    inactive: bool = False


class Ratchet(Protocol):
    name: str

    def check(self, ctx: RatchetContext) -> RatchetResult: ...


_REGISTRY: dict[str, Callable[[], Ratchet]] = {}


def register(name: str, factory: Callable[[], Ratchet]) -> None:
    _REGISTRY[name] = factory


def available() -> frozenset[str]:
    return frozenset(_REGISTRY)


def build_enabled(config: GateConfig) -> list[Ratchet]:
    """Instantiate the ratchets enabled in config, in registry order. An enabled
    ratchet name with no registered factory is an error (fail-closed: the policy
    asked for a guard the gate cannot provide)."""
    built: list[Ratchet] = []
    for name in _REGISTRY:
        if config.ratchet_enabled(name):
            built.append(_REGISTRY[name]())
    unknown = [
        n for n in config.ratchets if config.ratchet_enabled(n) and n not in _REGISTRY
    ]
    if unknown:
        raise ValueError(
            f"honesty.toml enables unknown ratchet(s) {unknown!r}; "
            f"available: {sorted(_REGISTRY)}"
        )
    return built


# Register the shipped ratchets at import.
from .diff_coverage import DiffCoverage  # noqa: E402
from .mutation import Mutation  # noqa: E402
from .no_new_skip import NoNewSkip  # noqa: E402
from .no_shrink import NoShrink  # noqa: E402

register("no_shrink", NoShrink)
register("no_new_skip", NoNewSkip)
register("diff_coverage", DiffCoverage)
register("mutation", Mutation)
