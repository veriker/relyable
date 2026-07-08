"""deliver_cli.py — the batch deliver-edge gate the OpenClaw TS plugin spawns.

OpenClaw plugins run in-process Node (TypeScript); relyable is Python. The
``message_sending`` plugin bridges the language boundary by spawning this CLI: it
sets the gate config in the environment (see ``config.DeliverGateConfig.from_env``)
and writes the candidate deliverables as JSON to stdin; the CLI writes the per-
deliverable verdicts as JSON to stdout. The plugin then suppresses (cancels) any
deliverable that did not re-derive.

Input (stdin JSON):
    {"candidates": [{"deliverable_id": "cron-brief", "payload": {...}}, ...]}

Output (stdout JSON):
    {"results": [{"deliverable_id": ..., "verdict": "ADMIT"|"REJECT",
                  "reason_code": ..., "detail": ..., "rederived": bool}, ...],
     "admitted": ["cron-brief", ...],
     "cancelled": [...]}

Exit code: 0 if every deliverable re-derived, 1 if any was suppressed (so a
CI/pipeline invocation also fails closed), 2 on a usage/parse error. The gate
decision is in the JSON regardless of exit code — the plugin reads ``cancelled``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from .config import DeliverGateConfig
from .deliver_gate import (
    admitted_deliverable_ids,
    cancelled_deliverable_ids,
    gate_deliverables,
)


def main(argv: list[str] | None = None) -> int:
    # Config comes from the environment the plugin sets (no flags: the plugin is the
    # caller, not a human). argv is accepted for symmetry / testability only.
    if argv:
        print(f"unexpected arguments: {argv}", file=sys.stderr)
        return 2
    try:
        config = DeliverGateConfig.from_env()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    try:
        request = json.loads(sys.stdin.read() or "{}")
    except ValueError as e:
        print(f"stdin is not valid JSON: {e}", file=sys.stderr)
        return 2
    candidates = request.get("candidates")
    if not isinstance(candidates, list):
        print("input JSON must have a 'candidates' array", file=sys.stderr)
        return 2

    results = gate_deliverables(candidates, config)
    admitted = admitted_deliverable_ids(results)
    cancelled = cancelled_deliverable_ids(results)
    print(
        json.dumps(
            {
                "results": [asdict(r) for r in results],
                "admitted": admitted,
                "cancelled": cancelled,
            },
            indent=2,
        )
    )
    return 0 if len(admitted) == len(results) and results else 1


if __name__ == "__main__":
    sys.exit(main())
