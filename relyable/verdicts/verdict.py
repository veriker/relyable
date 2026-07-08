"""verdict.py — the framework-agnostic test verdict + JUnit-XML interchange.

This is the keystone of the honesty gate. A `TestVerdict` is what the gate
*observed* by running the suite itself — never what an agent claimed. Every
language adapter normalizes to this one structure, so the gate logic (verdict
policy + ratchets) is written once and works for pytest, jest/vitest, go test,
cargo-nextest, or anything else that can emit JUnit XML.

JUnit XML is the lingua franca: pytest (`--junitxml`), jest (jest-junit),
go (`go-junit-report` / gotestsum), cargo (`cargo nextest --message-format
... | junit`, or nextest's native junit) all emit it. A framework that emits a
different machine-readable report gets a small adapter that produces a
`TestVerdict`; the rest of the gate does not change.

Fail-closed: a malformed / unparseable / empty report raises `VerdictParseError`.
The gate treats that as NON-green (could-not-conclude is never a pass). Parsing
is hardened against entity-expansion attacks (DOCTYPE is refused) because the
report, while produced inside the gate's own run, is written by third-party
test tooling and is the most attacker-influenced byte stream on the path.

Stdlib only.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# The four normalized outcomes. A testcase with a <failure> child is "failed";
# with an <error> child is "errored" (a test that could not run / crashed);
# with a <skipped> child is "skipped"; with none of those it "passed".
OUTCOME_PASSED = "passed"
OUTCOME_FAILED = "failed"
OUTCOME_ERRORED = "errored"
OUTCOME_SKIPPED = "skipped"

_OUTCOMES = frozenset(
    {OUTCOME_PASSED, OUTCOME_FAILED, OUTCOME_ERRORED, OUTCOME_SKIPPED}
)


class VerdictParseError(Exception):
    """The report could not be parsed into a verdict. Fail-closed: the gate
    treats this as could-not-conclude, never as a pass."""


@dataclass(frozen=True, slots=True)
class TestCase:
    """One normalized test result. `id` is a stable, framework-independent
    identifier (``"<classname>::<name>"`` when a classname is present, else the
    bare name) so per-test outcomes can be diffed across runs and against a
    baseline regardless of suite ordering or parametrization noise."""

    # Not a pytest test class despite the name (domain type "test case").
    __test__ = False

    id: str
    outcome: str
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if self.outcome not in _OUTCOMES:
            raise VerdictParseError(
                f"unknown outcome {self.outcome!r} (known: {sorted(_OUTCOMES)})"
            )


@dataclass(frozen=True, slots=True)
class TestVerdict:
    """What the gate observed by running the suite itself.

    Counts are derived from `cases` at construction so they cannot disagree with
    the per-case detail (a class of laundering where a summary claims 0 failures
    over a body that contains one). `green` is the load-bearing property: the
    suite ran at least one test and nothing failed or errored. Skips do NOT make
    a suite non-green by themselves — the no-new-skip ratchet governs skip abuse,
    not the verdict.
    """

    # Not a pytest test class despite the name (domain type "test verdict").
    __test__ = False

    cases: tuple[TestCase, ...]
    total: int = field(default=0)
    passed: int = field(default=0)
    failed: int = field(default=0)
    errored: int = field(default=0)
    skipped: int = field(default=0)

    @classmethod
    def from_cases(cls, cases: tuple[TestCase, ...]) -> "TestVerdict":
        passed = sum(1 for c in cases if c.outcome == OUTCOME_PASSED)
        failed = sum(1 for c in cases if c.outcome == OUTCOME_FAILED)
        errored = sum(1 for c in cases if c.outcome == OUTCOME_ERRORED)
        skipped = sum(1 for c in cases if c.outcome == OUTCOME_SKIPPED)
        return cls(
            cases=tuple(cases),
            total=len(cases),
            passed=passed,
            failed=failed,
            errored=errored,
            skipped=skipped,
        )

    @property
    def green(self) -> bool:
        """A real, conclusive pass: at least one test ran and none failed or
        errored. An empty suite is NOT green — "0 tests, 0 failures" is the
        oldest way to fake a green and must fail closed."""
        return self.total > 0 and self.failed == 0 and self.errored == 0

    def ids_with_outcome(self, outcome: str) -> frozenset[str]:
        return frozenset(c.id for c in self.cases if c.outcome == outcome)

    @property
    def failing_ids(self) -> frozenset[str]:
        return frozenset(
            c.id for c in self.cases if c.outcome in (OUTCOME_FAILED, OUTCOME_ERRORED)
        )

    @property
    def passing_ids(self) -> frozenset[str]:
        return self.ids_with_outcome(OUTCOME_PASSED)

    def summary(self) -> str:
        return (
            f"{self.total} test(s): {self.passed} passed, {self.failed} failed, "
            f"{self.errored} errored, {self.skipped} skipped"
        )


# ---------------------------------------------------------------------------
# JUnit XML parsing
# ---------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    """Drop an XML namespace prefix ('{ns}testcase' -> 'testcase')."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _case_id(classname: str | None, name: str) -> str:
    classname = (classname or "").strip()
    name = name.strip()
    if not name:
        raise VerdictParseError("testcase missing a 'name' attribute")
    return f"{classname}::{name}" if classname else name


def _case_outcome(case_el: ET.Element) -> str:
    """Outcome from a <testcase>'s children. failure > error > skipped > passed
    (a case carrying both a failure and an error is counted as failed — it did
    assert-fail, which is the stronger signal)."""
    has_failure = has_error = has_skipped = False
    for child in case_el:
        tag = _strip_ns(child.tag)
        if tag == "failure":
            has_failure = True
        elif tag == "error":
            has_error = True
        elif tag == "skipped":
            has_skipped = True
        # rerunFailure / flakyFailure (surefire) and system-out/err are ignored:
        # a rerun that ultimately passed leaves no <failure>, so it reads passed.
    if has_failure:
        return OUTCOME_FAILED
    if has_error:
        return OUTCOME_ERRORED
    if has_skipped:
        return OUTCOME_SKIPPED
    return OUTCOME_PASSED


def _parse_duration(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_junit_xml(data: str | bytes) -> TestVerdict:
    """Parse a JUnit XML report into a normalized `TestVerdict`.

    Accepts a root of either <testsuites> (multiple suites) or a single
    <testsuite>. Counts are derived from the actual <testcase> elements, NOT
    from the suite-level tests=/failures= attributes — those are advisory and a
    forged summary attribute must not be able to override the body.

    Raises `VerdictParseError` on malformed XML, a DOCTYPE (entity-expansion
    hardening), an unrecognized root, or a testcase missing a name.
    """
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise VerdictParseError(f"report is not valid UTF-8: {exc}") from exc
    else:
        text = data

    # Entity-expansion hardening: refuse any DOCTYPE outright. stdlib ET does not
    # resolve external entities, but an internal-subset billion-laughs is still a
    # DoS; the simplest sound defense is to reject DTDs, which no legitimate
    # JUnit report carries.
    if "<!DOCTYPE" in text:
        raise VerdictParseError("report contains a DOCTYPE; refused (DTD hardening)")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise VerdictParseError(f"report is not well-formed XML: {exc}") from exc

    root_tag = _strip_ns(root.tag)
    if root_tag == "testsuites":
        suites = [el for el in root if _strip_ns(el.tag) == "testsuite"]
    elif root_tag == "testsuite":
        suites = [root]
    else:
        raise VerdictParseError(
            f"unrecognized JUnit root <{root_tag}> (expected testsuites/testsuite)"
        )

    cases: list[TestCase] = []
    for suite in suites:
        for el in suite.iter():
            if _strip_ns(el.tag) != "testcase":
                continue
            name = el.get("name", "")
            classname = el.get("classname") or el.get("class")
            cases.append(
                TestCase(
                    id=_case_id(classname, name),
                    outcome=_case_outcome(el),
                    duration_s=_parse_duration(el.get("time")),
                )
            )

    return TestVerdict.from_cases(tuple(cases))
