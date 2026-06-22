"""safe_versions.py — a worked SEALED first-party reference for relyable.memory.

This stands in for the trusted catalog the consumer controls — the out-of-band
ground truth a recalled note must re-derive against. In a real deployment this is
your own data source (an internal advisory feed, a config registry, a database
view) that lives where the agent's memory cannot rewrite it. The recall grader
imports THIS module via the gate-set PYTHONPATH, never from the bundle.

Here: a tiny known-good package -> safe-version catalog. ``is_safe`` is the single
membership primitive the grader re-derives against (one evaluation, not two).
Stdlib only.
"""

from __future__ import annotations

from types import MappingProxyType

# The sealed truth: for each package, the set of versions known good. A recalled
# note recommending any other version does NOT re-derive and is refused.
_CATALOG = {
    "acme-http": ("1.4.2", "1.4.3", "2.0.0"),
    "widget-core": ("3.1.0", "3.1.1"),
    "data-pipe": ("0.9.7",),
}

CATALOG: MappingProxyType = MappingProxyType(
    {pkg: frozenset(vers) for pkg, vers in _CATALOG.items()}
)


def is_known_package(package: str) -> bool:
    return package in CATALOG


def is_safe(package: str, version: str) -> bool:
    """True iff ``version`` is a sealed-known-good version of ``package``."""
    return package in CATALOG and version in CATALOG[package]
