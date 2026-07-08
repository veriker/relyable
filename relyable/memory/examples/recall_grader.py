#!/usr/bin/env python3
"""recall_grader.py — a worked re-derivation GRADER for relyable.memory.

A relyable grader (installed into a bundle's ``re_derive/`` and run by veriker's
re-derivation lane). It re-derives a recalled note against the SEALED first-party
reference (``safe_versions``):

    exit 0 (admit)  iff the recalled {package, version} IS sealed-known-good;
    exit 1 (reject) otherwise — an unknown package, or a version not in the sealed
                    catalog (the gate admits ONLY a re-derivable recalled note).

The recalled note is the bundle's candidate body (``RECALLED = {...}``): gated and
exec'd here, NEVER trusted as a value. The sealed reference is imported from the
gate-set PYTHONPATH (the consumer's trusted tree), and this file STRIPS its own
directory (the bundle's re_derive/) from sys.path FIRST — so a poisoned bundle
shipping a fake ``safe_versions.py`` cannot override the sealed one. NO veriker
import here; stdlib + the trusted reference only.

Replace ``RECALLED`` parsing + the ``is_safe`` rule with your domain to make a
real recall grader.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# SECURITY: strip THIS file's directory (the bundle's re_derive/) and "" from
# sys.path so `import safe_versions` resolves ONLY via the gate-set PYTHONPATH (the
# consumer's sealed reference tree), never from a bundle shipping a fake reference
# that always says "safe". Done before any non-stdlib import.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if p and os.path.abspath(p) != _HERE]


def _fail(msg: str) -> int:
    print(f"[RECALL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def _recalled(snippet: str):
    """Exec the candidate body and read its ``RECALLED`` binding (the recalled
    note). Gated here, never trusted."""
    ns: dict = {}
    try:
        exec(snippet, ns)  # noqa: S102 — candidate from memory; gated, never trusted
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"candidate_exec_fail: {type(e).__name__}: {e}") from e
    return ns.get("RECALLED")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    bundle = Path(ap.parse_args().bundle_dir)

    try:
        import safe_versions  # trusted tree only (bundle dir stripped from path)
    except Exception as e:  # noqa: BLE001
        return _fail(f"reference_import_fail: {type(e).__name__}: {e}")

    try:
        snippet = (bundle / "skill" / "candidate.py").read_text(encoding="utf-8")
    except OSError as e:
        return _fail(f"candidate_unreadable: {e}")
    try:
        note = _recalled(snippet)
    except ValueError as e:
        return _fail(str(e))

    if not isinstance(note, dict):
        return _fail("recalled_note_not_a_dict")
    package = note.get("package")
    version = note.get("version")
    if not isinstance(package, str) or not isinstance(version, str):
        return _fail("recalled_note_missing_package_or_version")
    if not safe_versions.is_known_package(package):
        return _fail(f"unknown_package: {package!r}")

    # The re-derivation: admit ONLY a recalled note that IS sealed-known-good.
    if safe_versions.is_safe(package, version):
        return 0
    return _fail(f"note_not_re_derivable: {package} {version!r} (not sealed-safe)")


if __name__ == "__main__":
    sys.exit(main())
