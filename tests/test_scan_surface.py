"""test_scan_surface.py — the relyable-scan scanner-harness surface.

Covers the relyable-scan-v1 contract the clawscan adapter pins:
  - one JSON object, schemaVersion + axis stamped, evidence-first exit codes
  - the grade cascade: self_spec wired (PASS / DIVERGED), exogenous detection
    recorded, non_rederivable as the honest floor (never a fabricated pass)
  - fail-closed execution: without --allow-host-exec nothing runs and tools
    report UNJUDGEABLE_NO_SANDBOX
  - no secret values in the payload (llmLaneAvailable is presence-only)
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from relyable.scan import (
    GRADE_NON_REDERIVABLE,
    GRADE_SELF_SPEC,
    SCHEMA_VERSION,
    VERDICT_DIVERGED,
    VERDICT_OUT_OF_SCOPE,
    VERDICT_PASS,
    VERDICT_UNJUDGEABLE,
    scan_target,
)
from relyable.scan.cli import main as scan_main

_ADDER_MD = """\
    ---
    name: adder
    ---
    # adder
    ```console
    $ python add.py 2 3
    5
    ```
"""

_ADD_OK = "import sys; print(int(sys.argv[1]) + int(sys.argv[2]))\n"
_ADD_BROKEN = "import sys; print(int(sys.argv[1]) + int(sys.argv[2]) + 1)\n"


def _mk_skill(root: Path, name: str, md: str, tool_rel: str, tool_body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(textwrap.dedent(md), encoding="utf-8")
    tp = d / tool_rel
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(textwrap.dedent(tool_body), encoding="utf-8")
    return d


def _mk_prose_skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: prose-only\n---\nJust advice. No entrypoint, no examples.\n",
        encoding="utf-8",
    )
    return d


def test_self_spec_pass(tmp_path):
    d = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_OK)
    payload = scan_target(d, allow_host_exec=True, env={})
    assert payload["schemaVersion"] == SCHEMA_VERSION
    assert payload["axis"] == "functional-rederivation"
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_SELF_SPEC
    assert skill["selfSpecTier"] == "S-B"
    assert skill["verdict"] == VERDICT_PASS
    # exogenous was attempted and its degrade reason recorded — never silent
    assert "exogenous" in skill["attempted"]
    assert "exogenous" in skill["degradeReasons"]


def test_self_spec_diverged(tmp_path):
    d = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_BROKEN)
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_SELF_SPEC
    assert skill["verdict"] == VERDICT_DIVERGED
    assert "CONTRADICTS" in skill["tools"].values()


def test_fail_closed_without_host_exec_ack(tmp_path):
    d = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_OK)
    payload = scan_target(d, allow_host_exec=False, env={})
    (skill,) = payload["skills"]
    assert payload["allowHostExec"] is False
    assert skill["verdict"] == VERDICT_UNJUDGEABLE
    assert set(skill["tools"].values()) == {"UNJUDGEABLE_NO_SANDBOX"}


def test_prose_skill_is_honest_floor_not_fabricated_pass(tmp_path):
    d = _mk_prose_skill(tmp_path, "prose-only")
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_NON_REDERIVABLE
    assert skill["verdict"] == VERDICT_OUT_OF_SCOPE
    assert skill["tools"] == {}
    assert "cold_golden" in skill["degradeReasons"]


def test_exogenous_manifest_detected_and_reported(tmp_path):
    d = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_OK)
    (d / "rederive.json").write_text('{"kind": "idempotence"}', encoding="utf-8")
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["exogenousManifest"] == "rederive.json"
    assert "not wired into scan v1" in skill["degradeReasons"]["exogenous"]


def test_directory_of_skills_and_skillmd_file_targets(tmp_path):
    _mk_skill(tmp_path, "a", _ADDER_MD, "add.py", _ADD_OK)
    _mk_prose_skill(tmp_path, "b")
    payload = scan_target(tmp_path, allow_host_exec=True, env={})
    assert [s["skill"] for s in payload["skills"]] == ["a", "b"]
    # a SKILL.md FILE target resolves to its parent dir (the clawscan shape)
    payload2 = scan_target(tmp_path / "a" / "SKILL.md", allow_host_exec=True, env={})
    assert [s["skill"] for s in payload2["skills"]] == ["a"]


def test_llm_lane_presence_only_never_value(tmp_path):
    d = _mk_prose_skill(tmp_path, "prose-only")
    secret = "sk-super-secret-value-xyzzy"
    payload = scan_target(d, env={"ANTHROPIC_API_KEY": secret})
    assert payload["llmLaneAvailable"] is True
    assert secret not in json.dumps(payload)
    assert scan_target(d, env={})["llmLaneAvailable"] is False


def test_cli_evidence_first_exit_codes(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("RELYABLE_SCAN_ALLOW_HOST_EXEC", raising=False)
    diverged = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_BROKEN)
    rc = scan_main([str(diverged), "--json", "--allow-host-exec"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0  # DIVERGED is a finding, not a scan failure
    assert payload["skills"][0]["verdict"] == VERDICT_DIVERGED

    rc_missing = scan_main([str(tmp_path / "does-not-exist"), "--json"])
    payload_missing = json.loads(capsys.readouterr().out)
    assert rc_missing == 2  # unreadable target IS a scan failure
    assert payload_missing["error"]
