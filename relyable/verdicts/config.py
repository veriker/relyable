"""config.py — the gate's configuration AND its trust anchor.

`honesty.toml` is the developer's pinned policy: which command produces the
verdict, where the report lands, the flaky budget, the baseline location, and
which ratchets are enabled at what thresholds. The agent is evaluated AGAINST
this config; it does not get to author it.

That is the whole trust story, so the config is also an **anchor**. An agent
that could silently weaken the gate (swap `pytest` for `echo pass`, drop a
threshold, disable a ratchet) by editing honesty.toml or the baseline would
route around everything. The anchor is the SHA-256 over the config + baseline
bytes; the trusted side (CI secret / human) pins the expected value out-of-band.
At evaluation the gate recomputes it and, if an expected anchor was supplied,
refuses to run a config whose bytes changed (`ConfigAnchorMismatch`). With no
expected anchor the gate still runs but records the computed anchor and marks
the policy UNPINNED, so a reviewer can see the gate's own config was not
verified. This mirrors the veriker SpecAnchor: authority is supplied by the
trusted side, never selected by the producer.

Example honesty.toml:

    [test]
    command = ["python", "-m", "pytest", "-q", "--junitxml=report.xml"]
    report_path = "report.xml"
    timeout_seconds = 600
    max_reruns = 0

    [baseline]
    path = ".honesty/baseline.json"

    [ratchets]
    no_shrink = true
    no_new_skip = true

Stdlib only (tomllib, 3.11+).
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """honesty.toml is missing, malformed, or missing a required field."""


class ConfigAnchorMismatch(Exception):
    """The live config/baseline bytes do not match the expected anchor — the
    gate's own policy was changed. Fail-closed."""


@dataclass(frozen=True, slots=True)
class GateConfig:
    command: tuple[str, ...]
    report_path: str
    baseline_path: str
    report_format: str = "junit"
    timeout_seconds: float | None = None
    max_reruns: int = 0
    ratchets: dict[str, Any] = field(default_factory=dict)
    config_path: Path | None = None

    def ratchet_enabled(self, name: str) -> bool:
        val = self.ratchets.get(name)
        if isinstance(val, bool):
            return val
        if isinstance(val, dict):
            return bool(val.get("enabled", True))
        return False

    def ratchet_params(self, name: str) -> dict[str, Any]:
        val = self.ratchets.get(name)
        return dict(val) if isinstance(val, dict) else {}


def load_config(path: Path) -> GateConfig:
    path = path.resolve()
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc

    test = raw.get("test")
    if not isinstance(test, dict):
        raise ConfigError(f"{path}: missing required [test] table")

    command = test.get("command")
    if not (
        isinstance(command, list)
        and command
        and all(isinstance(a, str) for a in command)
    ):
        raise ConfigError(f"{path}: [test].command must be a non-empty list of strings")

    report_path = test.get("report_path")
    if not isinstance(report_path, str) or not report_path:
        raise ConfigError(f"{path}: [test].report_path must be a non-empty string")

    report_format = test.get("report_format", "junit")
    if report_format != "junit":
        raise ConfigError(
            f"{path}: [test].report_format {report_format!r} unsupported (only 'junit' in v1)"
        )

    timeout = test.get("timeout_seconds")
    if timeout is not None and not isinstance(timeout, (int, float)):
        raise ConfigError(f"{path}: [test].timeout_seconds must be a number")

    max_reruns = test.get("max_reruns", 0)
    if not isinstance(max_reruns, int) or max_reruns < 0:
        raise ConfigError(f"{path}: [test].max_reruns must be an int >= 0")

    baseline = raw.get("baseline", {})
    baseline_path = (
        baseline.get("path", ".honesty/baseline.json")
        if isinstance(baseline, dict)
        else ".honesty/baseline.json"
    )

    ratchets = raw.get("ratchets", {})
    if not isinstance(ratchets, dict):
        raise ConfigError(f"{path}: [ratchets] must be a table")

    return GateConfig(
        command=tuple(command),
        report_path=report_path,
        baseline_path=baseline_path,
        report_format=report_format,
        timeout_seconds=float(timeout) if timeout is not None else None,
        max_reruns=max_reruns,
        ratchets=ratchets,
        config_path=path,
    )


def compute_anchor(config_path: Path, baseline_path: Path | None) -> str:
    """SHA-256 over the config bytes and (if present) the baseline bytes. This is
    the commitment the trusted side pins out-of-band."""
    h = hashlib.sha256()
    h.update(b"honesty-config\0")
    h.update(config_path.read_bytes())
    h.update(b"\0honesty-baseline\0")
    if baseline_path is not None and baseline_path.is_file():
        h.update(baseline_path.read_bytes())
    else:
        h.update(b"<absent>")
    return h.hexdigest()


def verify_anchor(computed: str, expected: str | None) -> None:
    """Raise ConfigAnchorMismatch when an expected anchor was supplied and the
    live bytes do not match it. A None expected anchor is the UNPINNED case —
    permitted, but the gate records the policy as unverified."""
    if expected is None:
        return
    if computed.lower() != expected.lower():
        raise ConfigAnchorMismatch(
            "gate config/baseline bytes do not match the pinned anchor — the "
            "policy was modified. Re-pin deliberately (out-of-band) or revert. "
            f"expected={expected[:16]}… computed={computed[:16]}…"
        )
