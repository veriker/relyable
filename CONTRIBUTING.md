# Contributing to relyable

Issues and pull requests are welcome. relyable is a verification tool, so the
bar is correctness and honesty about scope — a check that can be fooled is
worse than no check.

## Developer Certificate of Origin (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/)
1.1 instead of a Contributor License Agreement. You keep the copyright to your
contribution; you certify that you have the right to submit it under the
project's Apache-2.0 license.

Sign off every commit:

```bash
git commit -s -m "your message"
```

This appends a `Signed-off-by: Your Name <you@example.com>` line, which is your
DCO certification. We do **not** use a copyright-assignment CLA.

## Before you open a pull request

- Install from source with the dev extras and run the suite:
  `pip install -e ".[dev]" && pytest`. The tests live in `tests/`.
- The **honesty self-gate** ratchets the test baseline in
  `.honesty/baseline.json` (currently 214 tracked ids). Adding code must not
  silently lower that count — if your change legitimately moves the baseline,
  re-pin it in the same PR and say why. A green run that quietly drops ids is
  the gaming this project exists to catch.
- Keep claims honest: each surface's README states the exact property it
  re-derives and the explicit limits of that claim. "Re-derived against your
  authority" is never written up as "correct spec," and the anti-vacuity prove
  gate's `kills-mutants` result is never written up as "proven correct."
- The verdict re-derivation path is offline and stdlib-only — a test verdict
  can be re-derived with no third-party trust. Changes that add a third-party
  import to that path will fail the import-boundary check, by design. The
  skills and memory bindings re-derive through the open
  [veriker](https://github.com/veriker/veriker) substrate, which relyable
  declares as a real dependency.

## Reporting security issues

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md)
for the disclosure process, scope, and embargo timeline.
