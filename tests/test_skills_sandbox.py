"""Sandbox isolation for the skills re-derivation path.

veriker runs the grader pack with a hardcoded in-process subprocess, so the only
honest boundary is to run the WHOLE re-derivation behind a Sandbox. These cover:
the in-process default is labeled "host"; a SubprocessSandbox really runs the worker
(spawn -> veriker -> pack) and stamps "subprocess"; failures (no verdict / timeout)
fail closed; ContainerSandbox builds the right docker argv (no Docker needed); and
the adapter parses RELYABLE_HERMES_SANDBOX.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import skills_fixtures as fixtures
from skills_fixtures import GRADER_SRC

from relyable.skills import rederive
from relyable.verdicts.sandbox import (
    ContainerSandbox,
    ExecResult,
    SubprocessSandbox,
)


def _build(dest: Path, skill_id: str, body: str):
    return fixtures._build(dest, skill_id, "merge", body, "VALIDATED")


# --- the in-process default is honestly labeled "host" -------------------------
def test_in_process_default_is_host(tmp_path):
    bundle = _build(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    v = rederive(bundle, grader_src=GRADER_SRC, permit_execution=True)
    assert v.verdict == "ADMIT"
    assert v.isolation_level == "host"


# --- a real SubprocessSandbox runs the worker end-to-end and stamps its label --
def test_subprocess_sandbox_admits_and_stamps(tmp_path):
    bundle = _build(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    v = rederive(
        bundle,
        grader_src=GRADER_SRC,
        permit_execution=True,
        sandbox=SubprocessSandbox(),
    )
    assert v.verdict == "ADMIT"
    assert v.reason_code == "RE_DERIVED"
    assert v.isolation_level == "subprocess"


def test_subprocess_sandbox_rejects_bad_skill(tmp_path):
    bundle = _build(tmp_path, "merge_le_idiom", fixtures.MERGE_LE_IDIOM)
    v = rederive(
        bundle,
        grader_src=GRADER_SRC,
        permit_execution=True,
        sandbox=SubprocessSandbox(),
    )
    assert v.verdict == "REJECT"
    assert v.rederived_label == "REJECTED"  # the pack ran in-sandbox and contradicted
    assert v.isolation_level == "subprocess"


def test_subprocess_sandbox_preserves_verdict_fields(tmp_path):
    """The reconstructed verdict carries the worker's real fields (forged flag)."""
    bundle = _build(tmp_path, "merge_le_idiom", fixtures.MERGE_LE_IDIOM)
    v = rederive(
        bundle,
        grader_src=GRADER_SRC,
        permit_execution=True,
        sandbox=SubprocessSandbox(),
    )
    assert v.skill_id == "merge_le_idiom"
    assert v.forged_label is True  # claimed VALIDATED, re-derived REJECTED


# --- fail-closed when the sandbox returns no usable verdict --------------------
class _StubSandbox:
    label = "stub"

    def __init__(self, result: ExecResult) -> None:
        self._r = result

    def run(self, command, *, cwd, env=None, timeout=None) -> ExecResult:
        return self._r


def test_sandbox_no_verdict_fails_closed(tmp_path):
    bundle = _build(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    stub = _StubSandbox(ExecResult(1, "garbage, no sentinel\n", "boom", False))
    v = rederive(bundle, grader_src=GRADER_SRC, permit_execution=True, sandbox=stub)
    assert v.verdict == "REJECT"
    assert v.reason_code == "SANDBOX_NO_VERDICT"
    assert v.isolation_level == "stub"


def test_sandbox_timeout_fails_closed(tmp_path):
    bundle = _build(tmp_path, "merge_good", fixtures.MERGE_GOOD)
    stub = _StubSandbox(ExecResult(124, "", "timed out", True))
    v = rederive(bundle, grader_src=GRADER_SRC, permit_execution=True, sandbox=stub)
    assert v.verdict == "REJECT"
    assert v.reason_code == "SANDBOX_TIMEOUT"


# --- ContainerSandbox builds the right docker argv (no Docker required) --------
def test_container_sandbox_argv(monkeypatch, tmp_path):
    import relyable.verdicts.sandbox as sb

    captured = {}

    class _CP:
        returncode = 0
        stdout = "RELYABLE_VERDICT_JSON:{}"
        stderr = ""

    def fake_run(args, **kw):
        captured["args"] = args
        return _CP()

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    box = ContainerSandbox("relyable/grader:latest")
    box.run(["python", "-m", "relyable.skills._sandbox_worker"], cwd=tmp_path)

    argv = captured["args"]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "relyable/grader:latest" in argv
    assert argv[-3:] == ["python", "-m", "relyable.skills._sandbox_worker"]
    assert box.label == "container"


def test_subprocess_sandbox_label():
    assert SubprocessSandbox().label == "subprocess"


# --- the adapter parses RELYABLE_HERMES_SANDBOX --------------------------------
def test_adapter_sandbox_env_parsing():
    from relyable.adapters.hermes import HermesGuardConfig

    base = {"RELYABLE_HERMES_GRADER": str(GRADER_SRC)}
    assert HermesGuardConfig.from_env(base).sandbox is None
    sub = HermesGuardConfig.from_env({**base, "RELYABLE_HERMES_SANDBOX": "subprocess"})
    assert sub.sandbox.label == "subprocess"
    con = HermesGuardConfig.from_env(
        {
            **base,
            "RELYABLE_HERMES_SANDBOX": "container",
            "RELYABLE_HERMES_SANDBOX_IMAGE": "img:1",
        }
    )
    assert con.sandbox.label == "container"


def test_adapter_container_requires_image():
    from relyable.adapters.hermes import HermesGuardConfig

    with pytest.raises(ValueError, match="SANDBOX_IMAGE"):
        HermesGuardConfig.from_env(
            {
                "RELYABLE_HERMES_GRADER": str(GRADER_SRC),
                "RELYABLE_HERMES_SANDBOX": "container",
            }
        )


def test_adapter_invalid_sandbox_mode_raises():
    from relyable.adapters.hermes import HermesGuardConfig

    with pytest.raises(ValueError, match="none.subprocess.container"):
        HermesGuardConfig.from_env(
            {"RELYABLE_HERMES_GRADER": str(GRADER_SRC), "RELYABLE_HERMES_SANDBOX": "vm"}
        )
