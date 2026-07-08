"""relyable.verdicts — the engine behind the agent test-honesty gate.

A trusted harness that owns test execution and re-derives the verdict, so a
coding agent cannot self-report "all tests pass" and cannot quietly shrink the
suite below a committed baseline. Framework-agnostic via the JUnit-XML verdict
interchange (verdict.py); CLI / MCP / audit-bundle wrappers sit on top.

Working name — subject to a product-naming decision.
"""

from __future__ import annotations

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

__all__ = [
    "TestVerdict",
    "TestCase",
    "VerdictParseError",
    "parse_junit_xml",
    "OUTCOME_PASSED",
    "OUTCOME_FAILED",
    "OUTCOME_ERRORED",
    "OUTCOME_SKIPPED",
]
