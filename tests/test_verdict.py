"""test_verdict.py — the JUnit-XML interchange must normalize every real-world
shape and fail closed on the adversarial / malformed ones."""

from __future__ import annotations

import pytest

from relyable.verdicts.verdict import (
    VerdictParseError,
    parse_junit_xml,
)

# --- Real-world report shapes (representative, trimmed) ---------------------

PYTEST = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" errors="0" skipped="1">
    <testcase classname="tests.test_a" name="test_pass" time="0.01"/>
    <testcase classname="tests.test_a" name="test_fail" time="0.02">
      <failure message="assert 1 == 2">AssertionError</failure>
    </testcase>
    <testcase classname="tests.test_b" name="test_skip" time="0.0">
      <skipped message="needs network"/>
    </testcase>
    <testcase classname="tests.test_b" name="test_ok" time="0.03"/>
  </testsuite>
</testsuites>
"""

# jest-junit uses a <testsuites> root with classname="" sometimes.
JEST = """<testsuites name="jest tests" tests="2" failures="0">
  <testsuite name="auth.test.ts" tests="2" failures="0">
    <testcase classname="auth login" name="returns a token" time="0.5"/>
    <testcase classname="auth login" name="rejects bad creds" time="0.4"/>
  </testsuite>
</testsuites>
"""

# go-junit-report: single <testsuite> root, error child for a panic.
GO = """<testsuite tests="3" failures="1" errors="1" name="pkg/auth">
  <testcase classname="pkg/auth" name="TestLogin" time="0.001"/>
  <testcase classname="pkg/auth" name="TestLogout" time="0.001">
    <failure message="Failed">login still active</failure>
  </testcase>
  <testcase classname="pkg/auth" name="TestPanic" time="0.000">
    <error message="panic">runtime error: nil deref</error>
  </testcase>
</testsuite>
"""


def test_pytest_shape():
    v = parse_junit_xml(PYTEST)
    assert (v.total, v.passed, v.failed, v.errored, v.skipped) == (4, 2, 1, 0, 1)
    assert not v.green  # a failure present
    assert v.failing_ids == {"tests.test_a::test_fail"}
    assert "tests.test_a::test_pass" in v.passing_ids


def test_jest_shape_all_green():
    v = parse_junit_xml(JEST)
    assert (v.total, v.passed, v.failed) == (2, 2, 0)
    assert v.green


def test_go_shape_failure_and_error():
    v = parse_junit_xml(GO)
    assert v.failed == 1 and v.errored == 1 and v.passed == 1
    assert not v.green
    assert v.failing_ids == {"pkg/auth::TestLogout", "pkg/auth::TestPanic"}


def test_counts_derive_from_body_not_attributes():
    """A forged suite-level summary must not override the actual cases."""
    forged = """<testsuite tests="99" failures="0" errors="0" name="liar">
      <testcase classname="x" name="t1"/>
      <testcase classname="x" name="t2"><failure/></testcase>
    </testsuite>"""
    v = parse_junit_xml(forged)
    assert v.total == 2 and v.failed == 1  # body wins, not tests="99"/failures="0"
    assert not v.green


def test_empty_suite_is_not_green():
    """0 tests, 0 failures is the oldest fake-green and must fail closed."""
    v = parse_junit_xml('<testsuite tests="0" failures="0" name="empty"></testsuite>')
    assert v.total == 0
    assert not v.green


def test_from_cases_consistency():
    v = parse_junit_xml(PYTEST)
    assert v.total == len(v.cases)
    assert v.passed + v.failed + v.errored + v.skipped == v.total


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not xml at all",
        "<unknownroot/>",
        "<testsuite><testcase/></testsuite>",  # testcase missing name
    ],
)
def test_malformed_fails_closed(bad):
    with pytest.raises(VerdictParseError):
        parse_junit_xml(bad)


def test_doctype_refused():
    payload = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE testsuite [<!ENTITY x "boom">]>'
        "<testsuite><testcase classname='a' name='t'/></testsuite>"
    )
    with pytest.raises(VerdictParseError):
        parse_junit_xml(payload)


def test_namespaced_tags():
    ns = """<ns:testsuite xmlns:ns="http://x" name="n">
      <ns:testcase classname="a" name="t1"/>
      <ns:testcase classname="a" name="t2"><ns:failure/></ns:testcase>
    </ns:testsuite>"""
    v = parse_junit_xml(ns)
    assert v.total == 2 and v.failed == 1
