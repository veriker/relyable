"""test_installpolicy.py — relyable as an OpenClaw security.installPolicy command.

Drives the stdin/stdout JSON protocol through ``installpolicy.run`` and asserts the
allow/block decision matches the re-derivation, with the documented fail-closed
behavior on malformed/misconfigured/unjudgeable inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from relyable.adapters import installpolicy
from relyable.skills import examples

GRADER = str(Path(examples.__file__).parent / "exec_skill_grader.py")

CONVERT_OK = (
    "import sys, json, csv\nprint(json.dumps(list(csv.DictReader(sys.stdin))))\n"
)
CONVERT_FORGED = 'print("[]")\n'


def _stage(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n", encoding="utf-8")
    (d / "convert.py").write_text(body, encoding="utf-8")
    return d


def _req(source_path: Path, slug: str = "csvjson") -> str:
    return json.dumps(
        {
            "protocolVersion": 1,
            "openclawVersion": "1.0.0",
            "targetType": "skill",
            "targetName": slug,
            "sourcePath": str(source_path),
            "sourcePathKind": "directory",
            "origin": {"type": "clawhub", "registry": "clawhub", "slug": slug},
            "request": {"kind": "install", "mode": "install"},
        }
    )


def _env(**over) -> dict:
    base = {
        "RELYABLE_INSTALLPOLICY_GRADER": GRADER,
        "RELYABLE_INSTALLPOLICY_KIND_MAP": json.dumps({"csvjson": "csvjson"}),
    }
    base.update(over)
    return base


def test_good_skill_allowed(tmp_path):
    src = _stage(tmp_path, "csvjson", CONVERT_OK)
    d = installpolicy.run(_req(src), _env())
    assert d == {"protocolVersion": 1, "decision": "allow"}


def test_forged_skill_blocked(tmp_path):
    src = _stage(tmp_path, "csvjson", CONVERT_FORGED)
    d = installpolicy.run(_req(src), _env())
    assert d["decision"] == "block"
    assert "did not re-derive" in d["reason"]


def test_malformed_request_blocks(tmp_path):
    assert installpolicy.run("{not json", _env())["decision"] == "block"


def test_wrong_protocol_version_blocks(tmp_path):
    src = _stage(tmp_path, "csvjson", CONVERT_OK)
    req = json.loads(_req(src))
    req["protocolVersion"] = 2
    assert installpolicy.run(json.dumps(req), _env())["decision"] == "block"


def test_missing_grader_config_blocks(tmp_path):
    src = _stage(tmp_path, "csvjson", CONVERT_OK)
    d = installpolicy.run(_req(src), {})  # no RELYABLE_INSTALLPOLICY_GRADER
    assert d["decision"] == "block"
    assert "GRADER" in d["reason"]


def test_plugin_target_unjudgeable_blocks_by_default(tmp_path):
    src = _stage(tmp_path, "csvjson", CONVERT_OK)
    req = json.loads(_req(src))
    req["targetType"] = "plugin"
    assert installpolicy.run(json.dumps(req), _env())["decision"] == "block"


def test_plugin_target_allowed_when_on_unjudgeable_allow(tmp_path):
    src = _stage(tmp_path, "csvjson", CONVERT_OK)
    req = json.loads(_req(src))
    req["targetType"] = "plugin"
    d = installpolicy.run(
        json.dumps(req), _env(RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE="allow")
    )
    assert d == {"protocolVersion": 1, "decision": "allow"}


def test_prose_only_skill_unjudgeable_blocks(tmp_path):
    d = tmp_path / "prose"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: prose\n---\n# tips\n", encoding="utf-8")
    decision = installpolicy.run(_req(d, "prose"), _env())
    assert decision["decision"] == "block"
    assert "unjudgeable" in decision["reason"]
