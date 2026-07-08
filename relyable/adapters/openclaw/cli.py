"""cli.py — the batch recall-gate the OpenClaw TS plugin spawns.

OpenClaw plugins run in-process Node (TypeScript); relyable is Python. The plugin
bridges the language boundary by spawning this CLI: it sets the gate config in the
environment (see ``config.RecallGateConfig.from_env``) and writes the candidate
recalled notes as JSON to stdin; the CLI writes the per-note verdicts as JSON to
stdout. The plugin then injects only the admitted notes.

Input (stdin JSON):
    {"candidates": [{"note_id": "latest_acme", "payload": {...}}, ...]}

Output (stdout JSON):
    {"results": [{"note_id": ..., "verdict": "ADMIT"|"REJECT",
                  "reason_code": ..., "detail": ..., "rederived": bool}, ...],
     "admitted": ["latest_acme", ...]}

Exit code: 0 if every candidate re-derived, 1 if any was refused (so a CI/pipeline
invocation also fails closed), 2 on a usage/parse error. The gate decision is in
the JSON regardless of exit code — the plugin reads ``admitted``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from .config import RecallGateConfig
from .recall_gate import admitted_note_ids, gate_recalled_notes


def main(argv: list[str] | None = None) -> int:
    # Config comes from the environment the plugin sets (no flags: the plugin is the
    # caller, not a human). argv is accepted for symmetry / testability only.
    if argv:
        print(f"unexpected arguments: {argv}", file=sys.stderr)
        return 2
    try:
        config = RecallGateConfig.from_env()
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

    results = gate_recalled_notes(candidates, config)
    admitted = admitted_note_ids(results)
    print(
        json.dumps(
            {"results": [asdict(r) for r in results], "admitted": admitted},
            indent=2,
        )
    )
    return 0 if len(admitted) == len(results) and results else 1


if __name__ == "__main__":
    sys.exit(main())
