"""agent_tool.py — the harness-agnostic agent tool.

This is the surface that makes "all tests pass" un-fakeable *inside the agent
loop*. Wired as the agent's ONLY path to test results (raw test-runner access
removed at the harness level), an agent can no longer self-assert outcomes: it
calls `run_tests`, and the gate runs the suite itself and returns the re-derived
verdict plus a `claim` sentence the agent is instructed to surface verbatim.

Kept dependency-free so any harness can wrap it — the MCP server (mcp_server.py)
is one thin wrapper; a function-calling tool, a LangChain tool, or a bespoke
agent loop are others. It never raises into the agent: every failure (bad
config, anchor mismatch, could-not-conclude) comes back as a structured result
with ok=False, because "the tool errored" must not read to the agent as "tests
passed".

The natural-language `claim` is the antidote to the prose lie: instead of the
agent writing "I ran the tests and they all pass", it reports the gate's own
sentence, which carries the re-derived counts and the config anchor.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import ConfigAnchorMismatch, ConfigError, load_config
from .gate import GateResult, evaluate
from .sandbox import Sandbox


def _claim(result: GateResult) -> str:
    """The sentence the agent should report verbatim instead of self-asserting."""
    v = result.run.verdict
    anchor = result.anchor[:12]
    if v is None or not result.run.conclusive:
        return (
            f"Honesty gate could NOT conclude a verdict ({result.run.reason}); "
            "tests are not known to pass. [gate-verified]"
        )
    head = "PASS" if result.ok else "FAIL"
    failed_ratchets = [r.name for r in result.ratchets if not r.ok]
    extra = ""
    if not result.ok and v.green and failed_ratchets:
        extra = f" Suite is green but ratchets failed: {', '.join(failed_ratchets)}."
    return (
        f"Honesty gate {head}: {v.passed} passed, {v.failed} failed, "
        f"{v.errored} errored, {v.skipped} skipped (re-derived by relyable; "
        f"anchor {anchor}…).{extra} [gate-verified]"
    )


def run_tests(
    workspace: str | Path = ".",
    config: str | Path = "honesty.toml",
    *,
    expected_anchor: str | None = None,
    sandbox: Sandbox | None = None,
) -> dict[str, Any]:
    """Run the project's suite through the gate and return a structured result.

    Never raises: configuration / anchor / could-not-conclude failures return
    a dict with ok=False and a `claim` that does NOT assert passing tests.
    """
    expected_anchor = expected_anchor or os.environ.get("HONESTY_ANCHOR")
    ws = Path(workspace).resolve()

    try:
        cfg = load_config(Path(config))
    except ConfigError as exc:
        return {
            "ok": False,
            "error": "config_error",
            "claim": (
                f"Honesty gate could not load its config ({exc}); tests are not "
                "known to pass. [gate-verified]"
            ),
            "detail": str(exc),
        }

    try:
        result = evaluate(ws, cfg, expected_anchor=expected_anchor, sandbox=sandbox)
    except ConfigAnchorMismatch as exc:
        return {
            "ok": False,
            "error": "anchor_mismatch",
            "claim": (
                "Honesty gate REFUSED to run: its config/baseline was modified "
                "and no longer matches the pinned anchor. The gate may have been "
                "weakened; tests are not known to pass. [gate-verified]"
            ),
            "detail": str(exc),
        }

    from .cli import gate_result_to_dict  # local import avoids a cycle at module load

    payload = gate_result_to_dict(result)
    payload["claim"] = _claim(result)
    payload["guidance"] = (
        "Report the `claim` string to the user verbatim. Do not assert test "
        "outcomes in your own words — this gate verdict is the authoritative "
        "source. If ok is false, the work is not done."
    )
    return payload
