# Security policy

This document describes how to report a vulnerability in relyable, what is in
and out of scope, and the disclosure timeline. It follows the
[GitHub disclosure conventions](https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository).
relyable is `v0.x` experimental, substrate-grade software; calibrate severity
expectations accordingly.

relyable rides the open [veriker](https://github.com/veriker/veriker)
re-derivation substrate. A vulnerability in the substrate itself (the bundle
format, the `BundleVerifier`, the producer SDK) should be reported to veriker;
report here for issues in relyable's gate, its verdicts/skills/memory surfaces,
the `relyable-*` CLIs, or the Hermes and OpenClaw adapters.

---

## Reporting a vulnerability

**Preferred channel:** email the maintainers with subject prefix
`[RELYABLE SECURITY]`.

- **Contact:** `security@nexiverify.com`
- **Acknowledgement:** within **3 business days** of receipt.
- **First substantive response:** within **10 business days**, including a
  triage verdict (in-scope / out-of-scope / need-more-info) and a target
  embargo date.

Please do **not** open a public GitHub issue for a security report. relyable is
mirrored to a private GitHub repository for staging purposes; public issues
there would defeat the embargo.

A useful report includes: the affected version or commit SHA; a minimal
reproduction (the claim you fed the gate, the command, and the verdict you got
versus the one you expected); and the security property you believe is broken.

---

## Embargo timeline

**Default embargo: 90 days from acknowledgement.** We may shorten it (with your
agreement) if an issue is being actively exploited, or extend it (with your
agreement) if coordination requires it — extensions are never unilateral. We
publish an advisory even for honest-null results: if a report is determined to
be working-as-designed, we publish the analysis so your work is on the record.

---

## Supported versions

| Version | Status |
|---|---|
| `0.x` (current) | Supported — experimental; security fixes land on the active line |

relyable carries no "production / verified" claim at this maturity. There is no
back-port commitment to pre-`0.x` builds because there are none.

---

## In scope

A report is in scope if it concerns relyable's own code and demonstrates that a
claim the gate should **refuse** is instead **admitted** — i.e. a break of the
core property "a claim is never trusted; it is re-derived":

- **A re-derivation bypass** — a skill, recalled note, or test verdict that does
  **not** re-derive against the supplied authority but is nonetheless admitted
  (e.g. a poisoned label or a re-stamped tree moves the verdict).
- **Authority substitution** — the producer selecting or rewriting the thing
  that judges it (the grader, the pinned config anchor, or the sealed memory
  reference) without tripping the fail-closed mismatch.
- **A fail-closed violation** — an input that makes a `relyable-*` command or
  the gate raise an unhandled exception or exit "green" when it could not
  actually conclude.
- **The anti-vacuity `prove` gate certifying a vacuous property** — a property
  that does not kill the mutants being accepted as non-vacuous.

---

## Out of scope

These will be acknowledged and closed without an advisory:

- **Sandboxing untrusted candidate code.** Skill and memory vetting runs
  candidate code when you opt in (`permit_execution=True`). Isolating that
  execution is the **host's** responsibility, by design and as documented in
  the README — run it where that is acceptable.
- **Incompleteness of your own authority.** A tautological test you wrote, a
  grader that is not exhaustive, or a sealed reference that is itself wrong are
  the consumer's responsibility. The gate guarantees a claim was *re-derived
  against your authority*, not that your authority is complete; the mutation
  ratchet is the strongest lever, not a completeness proof.
- **DoS via legitimately expensive suites or candidates.** A test suite or
  grader that is simply slow or large is an operator rate-limiting concern.
- **Vulnerabilities in the veriker substrate or other upstream dependencies.**
  Report substrate issues to [veriker](https://github.com/veriker/veriker);
  report library issues to the library.
- **Non-security bugs.** These go through the normal issue process.

If a report straddles the boundary, default to reporting; we will triage and
tell you the verdict and the rationale.

---

## Document version

- **Initial publication:** 2026-06-16
- **Next review:** at the next `0.x` tag, or when the contact email or embargo
  timeline changes.
