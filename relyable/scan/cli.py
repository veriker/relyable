"""cli.py — ``relyable-scan``: the scanner-harness CLI.

    relyable-scan <target> --json [--allow-host-exec] [--timeout N]

One JSON object (``relyable-scan-v1``) on stdout. Evidence-first: findings never
change the exit code (a DIVERGED skill still exits 0 — the harness preserves the
raw payload and any policy lives downstream). Exit 2 = usage / unreadable target;
that is a scan FAILURE, not a finding.

``--json`` is accepted (and is the only output mode) so the invocation is stable
if a human-readable mode is added later — a harness pinning ``--json`` never
breaks. ``--allow-host-exec`` is the explicit operator/harness ack that the host
is disposable (a container sandbox); without it, untrusted skill code is never
executed and executable tools report ``UNJUDGEABLE_NO_SANDBOX``.
``RELYABLE_SCAN_ALLOW_HOST_EXEC=1`` is the env-var form of the same ack.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from relyable.scan import scan_target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="relyable-scan",
        description=(
            "Graded functional-rederivation evidence for a native skill "
            "directory (relyable-scan-v1 JSON on stdout)."
        ),
    )
    ap.add_argument("target", help="SKILL.md file, a skill dir, or a dir of skill dirs")
    ap.add_argument(
        "--json", action="store_true", help="emit JSON (the default and only mode)"
    )
    ap.add_argument(
        "--allow-host-exec",
        action="store_true",
        help="ack that this host is disposable/sandboxed; required to execute skill code",
    )
    ap.add_argument(
        "--timeout", type=float, default=30.0, help="per-cell timeout seconds"
    )
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "force the cold_golden lane off even when an LLM key is present "
            "(deterministic runs; the lane degrades honestly in the payload)"
        ),
    )
    args = ap.parse_args(argv)

    allow = args.allow_host_exec or os.environ.get(
        "RELYABLE_SCAN_ALLOW_HOST_EXEC", ""
    ).strip().lower() in {"1", "true", "yes"}

    payload = scan_target(
        args.target, allow_host_exec=allow, timeout=args.timeout, no_llm=args.no_llm
    )
    json.dump(payload, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    if payload.get("error") is not None:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
