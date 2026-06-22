"""mcp_server.py — thin MCP server exposing the honesty gate as the agent's
ONLY test-results tool.

Run it as the agent's test-results provider (Claude Code / Cursor / any MCP
client) and remove the agent's raw test-runner access at the harness level. Then
the agent structurally cannot self-report pass/fail: the single tool here runs
the suite through the gate and returns the re-derived verdict.

Requires the optional `mcp` extra:  pip install "relyable[mcp]"
Run:  relyable-mcp   (or: python -m relyable.verdicts.mcp_server)

The tool logic lives in agent_tool.py (dependency-free); this file is only the
MCP transport shell, so the core package never depends on the MCP SDK.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except (
    ModuleNotFoundError
) as exc:  # pragma: no cover - exercised only without the extra
    raise SystemExit(
        "the MCP server needs the optional 'mcp' extra: pip install \"relyable[mcp]\""
    ) from exc

from . import agent_tool

mcp = FastMCP("relyable")


@mcp.tool()
def run_tests(workspace: str = ".", config: str = "honesty.toml") -> dict[str, Any]:
    """Run this project's test suite through the honesty gate and return the
    RE-DERIVED verdict.

    This is the authoritative and ONLY sanctioned source of test results. Do NOT
    state test outcomes in your own words: report the returned `claim` string
    verbatim. The gate runs the suite itself, so a claim of passing tests it did
    not observe is impossible. If `ok` is false the task is not complete —
    inspect `ratchets` and `reasons` and keep working.
    """
    return agent_tool.run_tests(Path(workspace), Path(config))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
