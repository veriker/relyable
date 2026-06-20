"""cli.py — the CI surface. `relyable run | baseline | anchor`.

Drops into any pipeline as an exit-0/1 step:

    relyable run                      # evaluate; exit 1 on any failure
    relyable run --anchor $HONESTY_ANCHOR   # also enforce the config anchor
    relyable baseline                 # snapshot the current green suite
    relyable anchor                   # print the anchor to pin in CI

`run` exits non-zero if the verdict isn't a conclusive green OR any ratchet
fails OR the config anchor doesn't match. `--json` emits a machine-readable
result for downstream tooling (and is what the MCP tool reuses).

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .baseline import from_verdict, write_baseline
from .config import (
    ConfigAnchorMismatch,
    ConfigError,
    GateConfig,
    compute_anchor,
    load_config,
)
from .gate import GateResult, evaluate
from .sandbox import ContainerSandbox, Sandbox, SubprocessSandbox

_DEFAULT_CONFIG = "honesty.toml"


def _make_sandbox(spec: str | None) -> Sandbox:
    if not spec or spec == "subprocess":
        return SubprocessSandbox()
    if spec.startswith("docker:"):
        image = spec.split(":", 1)[1]
        if not image:
            raise SystemExit("--sandbox docker:<image> requires an image name")
        return ContainerSandbox(image)
    raise SystemExit(
        f"unknown --sandbox {spec!r} (use 'subprocess' or 'docker:<image>')"
    )


def gate_result_to_dict(result: GateResult) -> dict:
    v = result.run.verdict
    return {
        "ok": result.ok,
        "verdict": None
        if v is None
        else {
            "green": v.green,
            "total": v.total,
            "passed": v.passed,
            "failed": v.failed,
            "errored": v.errored,
            "skipped": v.skipped,
            "failing_ids": sorted(v.failing_ids),
        },
        "run_conclusive": result.run.conclusive,
        "run_reason": result.run.reason,
        "flaky_ids": list(result.run.flaky_ids),
        "ratchets": [
            {"name": r.name, "ok": r.ok, "inactive": r.inactive, "detail": r.detail}
            for r in result.ratchets
        ],
        "anchor": result.anchor,
        "anchor_pinned": result.anchor_pinned,
        "baseline_present": result.baseline_present,
        "reasons": list(result.reasons),
    }


def _load(config_path: Path) -> GateConfig:
    try:
        return load_config(config_path)
    except ConfigError as exc:
        raise SystemExit(f"config error: {exc}") from exc


def _cmd_run(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = _load(Path(args.config))
    expected = args.anchor or os.environ.get("HONESTY_ANCHOR")
    try:
        result = evaluate(
            workspace,
            config,
            expected_anchor=expected,
            sandbox=_make_sandbox(args.sandbox),
        )
    except ConfigAnchorMismatch as exc:
        if args.json:
            print(
                json.dumps(
                    {"ok": False, "error": "anchor_mismatch", "detail": str(exc)}
                )
            )
        else:
            print(f"FAIL  relyable\n  FAIL  anchor: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(gate_result_to_dict(result), indent=2))
    else:
        out = result.render()
        print(
            out if result.ok else out, file=sys.stderr if not result.ok else sys.stdout
        )
    return 0 if result.ok else 1


def _cmd_baseline(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = _load(Path(args.config))
    result = evaluate(workspace, config, sandbox=_make_sandbox(args.sandbox))
    if not result.run.ok:
        print(
            "refusing to baseline a non-green suite — fix the suite first:\n"
            + result.render(),
            file=sys.stderr,
        )
        return 1
    baseline = from_verdict(
        result.run.verdict,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    baseline_file = (workspace / config.baseline_path).resolve()
    write_baseline(baseline_file, baseline)
    anchor = compute_anchor(config.config_path, baseline_file)
    print(f"baseline written: {baseline_file}")
    print(f"  {baseline.total} test(s) recorded")
    print(f"pin this anchor in CI (HONESTY_ANCHOR): {anchor}")
    return 0


def _cmd_anchor(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    config = _load(Path(args.config))
    baseline_file = (workspace / config.baseline_path).resolve()
    print(compute_anchor(config.config_path, baseline_file))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="relyable",
        description="Re-derive an agent's test verdict and ratchet against test-gaming.",
    )
    p.add_argument("--config", default=_DEFAULT_CONFIG, help="path to honesty.toml")
    p.add_argument("--workspace", default=".", help="repo root to evaluate")
    p.add_argument(
        "--sandbox",
        default="subprocess",
        help="'subprocess' (default) or 'docker:<image>'",
    )
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="evaluate the gate; exit 1 on failure")
    run.add_argument(
        "--anchor", default=None, help="expected config anchor (or $HONESTY_ANCHOR)"
    )
    run.add_argument("--json", action="store_true", help="machine-readable output")
    run.set_defaults(func=_cmd_run)

    base = sub.add_parser(
        "baseline", help="snapshot the current green suite as the baseline"
    )
    base.set_defaults(func=_cmd_baseline)

    anc = sub.add_parser("anchor", help="print the current config anchor")
    anc.set_defaults(func=_cmd_anchor)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
