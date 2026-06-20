# relyable.verdicts — un-fakeable "all tests pass"

> The **verdict surface** of the [relyable](../../) agent-trust suite (on the
> veriker substrate). Consumes `relyable.gate`.

A trusted gate that makes a coding agent's **"all tests pass"** un-fakeable and
its test suite un-gameable. It targets the #1 developer complaint about coding
agents: claiming tests pass when they didn't run / didn't pass, and writing
tests to pass instead of writing code to pass tests.

The core idea, in one line:

> The agent's verdict is a **claim**, never trusted — it is **re-derived**. The
> gate runs the suite itself and produces the verdict; the agent's prose is not
> an input. And the suite cannot quietly shrink below a committed baseline.

## Two layers

1. **Enforcement** (what you rely on): a trusted harness that *owns test
   execution*. The agent requests a run; the gate runs it and returns the real
   result. Framework-agnostic via the JUnit-XML verdict interchange.
2. **Attestation** (the moat): wrap each verdict in a re-derivable veriker audit
   bundle so "tests pass" travels as a checkable claim, not prose. See
   [Audit-bundle attestation](#audit-bundle-attestation) below.

## Use it in CI (the broadest surface)

```bash
relyable baseline                      # once, on a known-good tree:
                                       #   snapshots the suite + prints an anchor
relyable run --anchor $HONESTY_ANCHOR  # in CI: exit 1 on any failure
```

`run` fails (exit 1) when the verdict isn't a **conclusive green**, when any
**ratchet** fails, or when the **config anchor** doesn't match. Example output:

```
FAIL  relyable
  OK    verdict (gate-run): 2 test(s): 1 passed, 0 failed, 0 errored, 1 skipped — green
  FAIL  ratchet:no_shrink: test count 2 < baseline 3; 2 previously-passing test(s) no longer passing
  FAIL  ratchet:no_new_skip: 1 test(s) newly skipped vs baseline
```

The suite is *green* and the gate still says **FAIL** — that's the gaming the
verdict alone can't catch.

## Use it inside an agent (make the lie impossible in the loop)

Run the MCP server as the agent's **only** test-results tool and remove the
agent's raw test-runner access at the harness level:

```bash
relyable-mcp        # exposes one tool: run_tests
```

Now the agent cannot self-assert outcomes — `run_tests` runs the suite through
the gate and returns the re-derived verdict plus a `claim` string the agent
reports verbatim. Any harness can wrap the dependency-free
`relyable.verdicts.agent_tool.run_tests(...)` the same way.

## How it stays trustworthy: the config anchor

The whole trust story is that the agent is evaluated *against* `honesty.toml`,
not allowed to author it. So the config + baseline are an **anchor** (a SHA the
trusted side pins out-of-band, e.g. `$HONESTY_ANCHOR` from a CI secret). A diff
that weakens the gate — swapping the command, dropping a threshold, disabling a
ratchet, editing the baseline — changes the bytes and trips
`ConfigAnchorMismatch`. (This is the veriker SpecAnchor pattern: authority is
supplied by the trusted side, never selected by the producer.) With no anchor
pinned the gate still runs but marks the policy **UNPINNED** so reviewers know.

## Configuration

See [`honesty.toml`](../../honesty.toml) — `[test]` (the verdict-producing command
+ report path + flaky budget), `[baseline]`, and `[ratchets]`.

Any framework that emits **JUnit XML** works: pytest (`--junitxml`),
jest/vitest (jest-junit), go (`go-junit-report` / gotestsum), cargo
(nextest junit). Point `command` at the run that writes the report and set
`report_path` to where it lands.

## Ratchets (anti-gaming)

| Ratchet | Catches | Status |
|---|---|---|
| `no_shrink` | deleted tests, a previously-passing test going away, coverage dropping | shipped |
| `no_new_skip` | skipping a failing test (`skip`/`xfail`/`.only`/`t.Skip`) | shipped |
| `diff_coverage` | new/changed lines left uncovered | shipped |
| `mutation` | tautological / assertion-free tests (opt-in: mutmut / Stryker behind the gate) | shipped |

`diff_coverage` intersects the added/changed lines from `git diff <base_ref>`
with a Cobertura coverage report and fails when their covered fraction drops
below `min_percent`. It needs two things present: a coverage report (so your
`[test].command` must emit one, e.g. `pytest --cov --cov-report=xml`) and a git
repo with a valid `base_ref`. **Both are fail-closed**: an enabled
`diff_coverage` with a missing report, a non-git tree, or an unknown ref BLOCKS
— it never silently passes. Config: `diff_coverage = { enabled = true,
min_percent = 90, coverage_xml = "coverage.xml", base_ref = "origin/main" }`.

`mutation` drives a **real** mutation engine behind the gate — mutmut (Python)
or Stryker (JS/TS) — and fails when surviving mutants exceed `max_survivors`. A
survivor is a mutated source line the suite still passes: direct evidence of a
test that asserts nothing useful, which the other ratchets can't see. It is
**opt-in and slow** (minutes; default-disabled) — wire it as a CI-nightly or
pre-merge gate. The adapter shells the engine (no pip dependency on either) and
parses its native report; an absent engine, a crash, or a missing report is
**fail-closed**. Config: `mutation = { enabled = true, engine = "mutmut",
max_survivors = 0, timeout_seconds = 1800 }`.

## Audit-bundle attestation

`relyable.verdicts.audit_emit` turns a gate verdict into a **re-derivable veriker
audit bundle**, so "tests pass" travels as a checkable claim rather than prose:

```python
from relyable.verdicts.audit_emit import emit_from_gate_result, verify_bundle

bundle = emit_from_gate_result(
    "out/bundle", workspace=ws, config=cfg, result=gate_result,
    created_at="2026-06-14T00:00:00Z",
)
assert verify_bundle(bundle).ok
```

The bundle pins the committed `evidence/report.xml` and a claimed
`outputs/test_verdict.json`. A SHA-pinned spec binds the verdict to a
verifier-side primitive that **re-parses the report** and compares `exact`; a
tampered claim rides RED (`REDERIVATION_MISMATCH`) even after every manifest SHA
is re-stamped, because the verdict is re-derived, never read from the claim.

**Honest scope:** the bundle attests that the claimed verdict was correctly
derived from *this committed report*, and the report is integrity-pinned — **not**
that re-running the suite reproduces it (test runs aren't reproducible without
sealed deps; out of scope). This is the open Axis-2 re-derivation pattern; see
`examples/agent_honesty_minimal` in the veriker audit-bundle package.

## What this does and does NOT prove

**Does:** an agent cannot produce a green verdict without the suite actually
passing under the gate's runner — even with a fully re-stamped tree — and cannot
shrink/skip below the committed baseline without the gate catching it.

**Does not:** make *all* test-gaming impossible. If the agent writes both the
code and the tests and there's no external oracle, a tautological test that
passes is a *legitimate* green. The ratchets raise the cost and catch the common
patterns; the mutation ratchet is the strongest lever but not a completeness
proof.

**Sandboxing is the host's job.** `SubprocessSandbox` is weak — correct when the
gate already runs inside an isolated CI job. For untrusted code on a shared
host use `--sandbox docker:<image>` (network off by default).
