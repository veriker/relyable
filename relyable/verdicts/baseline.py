"""baseline.py — the committed snapshot the no-shrink / no-new-skip ratchets
compare against.

A baseline records, for a known-good state of the repo: which test ids existed,
which were passing, which were skipped, the totals, and (optionally) coverage.
The ratchets use it to refuse a change that drops below it.

The baseline is updated ONLY by an explicit human action (the CLI `baseline`
command), never automatically by the gate — otherwise an agent could ratchet the
floor down by regenerating it. The baseline file is also part of the config
anchor, so a silent edit to it is detectable.

Stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .verdict import OUTCOME_SKIPPED, TestVerdict

_SCHEMA = "honesty-baseline.v1"


@dataclass(frozen=True, slots=True)
class Baseline:
    total: int
    passing_ids: frozenset[str]
    skipped_ids: frozenset[str]
    coverage_percent: float | None
    created_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": _SCHEMA,
                "total": self.total,
                "passing_ids": sorted(self.passing_ids),
                "skipped_ids": sorted(self.skipped_ids),
                "coverage_percent": self.coverage_percent,
                "created_at": self.created_at,
            },
            indent=2,
            sort_keys=True,
        )


def from_verdict(
    verdict: TestVerdict, *, created_at: str, coverage_percent: float | None = None
) -> Baseline:
    return Baseline(
        total=verdict.total,
        passing_ids=verdict.passing_ids,
        skipped_ids=verdict.ids_with_outcome(OUTCOME_SKIPPED),
        coverage_percent=coverage_percent,
        created_at=created_at,
    )


def write_baseline(path: Path, baseline: Baseline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.to_json(), encoding="utf-8")


def read_baseline(path: Path) -> Baseline | None:
    """Return the baseline, or None if absent. Raises ValueError on a present but
    malformed baseline (fail-closed — a corrupt floor is not 'no floor')."""
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ValueError(f"baseline at {path} is unreadable: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != _SCHEMA:
        raise ValueError(f"baseline at {path} has an unrecognized schema")
    try:
        return Baseline(
            total=int(doc["total"]),
            passing_ids=frozenset(doc["passing_ids"]),
            skipped_ids=frozenset(doc["skipped_ids"]),
            coverage_percent=doc.get("coverage_percent"),
            created_at=str(doc.get("created_at", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"baseline at {path} is missing required fields: {exc}"
        ) from exc
