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


# --- tool-BUNDLE class (one SKILL.md routing to N bundled tools) ----------------

ECHO_PY = "import sys\nsys.stdout.write(sys.stdin.read())\n"
UPPER_PY = "import sys\nsys.stdout.write(sys.stdin.read().upper())\n"
UPPER_BROKEN = "import sys\nsys.stdout.write(sys.stdin.read().lower())\n"

# A hermetic consumer grader keyed by the per-tool kind "<slug>:<stem>" the install
# gate assigns. Stdin->stdout tools; prints the no-goldens sentinel for an unknown
# kind so the gate counts it UNJUDGEABLE (not a block). stdlib only, no veriker.
TB_GRADER = """\
import argparse, json, subprocess, sys
from pathlib import Path
GOLDENS = {"tb:echo": [("hi\\n", "hi")], "tb:upper": [("hi\\n", "HI")]}
ap = argparse.ArgumentParser(); ap.add_argument("--bundle-dir", required=True)
b = Path(ap.parse_args().bundle_dir)
meta = json.loads((b / "skill" / "meta.json").read_text())
cells = GOLDENS.get(meta.get("kind"))
if not cells:
    print("no_goldens_for_kind: %r" % meta.get("kind"), file=sys.stderr); sys.exit(1)
ep = (b / "skill" / meta["invocation"]["entrypoint"]).resolve()
for i, (inp, exp) in enumerate(cells):
    r = subprocess.run([sys.executable, str(ep)], input=inp, capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() != exp:
        print("cell%d mismatch %r" % (i, r.stdout), file=sys.stderr); sys.exit(1)
sys.exit(0)
"""


def _tb_grader(tmp_path: Path) -> str:
    g = tmp_path / "tb_grader.py"
    g.write_text(TB_GRADER, encoding="utf-8")
    return str(g)


def _stage_bundle(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "tb"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: tb\n---\n# tb\n", encoding="utf-8")
    for rel, body in files.items():
        (d / rel).write_text(body, encoding="utf-8")
    return d


def test_tool_bundle_all_tools_rederive_allowed(tmp_path):
    src = _stage_bundle(tmp_path, {"echo.py": ECHO_PY, "upper.py": UPPER_PY})
    d = installpolicy.run(
        _req(src, "tb"), {"RELYABLE_INSTALLPOLICY_GRADER": _tb_grader(tmp_path)}
    )
    assert d == {"protocolVersion": 1, "decision": "allow"}


def test_tool_bundle_broken_graded_tool_blocked(tmp_path):
    src = _stage_bundle(tmp_path, {"echo.py": ECHO_PY, "upper.py": UPPER_BROKEN})
    d = installpolicy.run(
        _req(src, "tb"), {"RELYABLE_INSTALLPOLICY_GRADER": _tb_grader(tmp_path)}
    )
    assert d["decision"] == "block"
    assert "tb:upper" in d["reason"] and "did not re-derive" in d["reason"]


def test_tool_bundle_ungraded_tool_does_not_block(tmp_path):
    """A tool the consumer has no goldens for is unjudgeable, not a contradiction —
    the bundle still installs because the graded tools re-derive."""
    src = _stage_bundle(
        tmp_path,
        {"echo.py": ECHO_PY, "upper.py": UPPER_PY, "extra.py": "print('whatever')\n"},
    )
    d = installpolicy.run(
        _req(src, "tb"), {"RELYABLE_INSTALLPOLICY_GRADER": _tb_grader(tmp_path)}
    )
    assert d == {"protocolVersion": 1, "decision": "allow"}


def test_tool_bundle_no_goldens_unjudgeable(tmp_path):
    """No bundled tool matches any golden -> unjudgeable -> ON_UNJUDGEABLE policy."""
    src = _stage_bundle(tmp_path, {"x.py": ECHO_PY, "y.py": UPPER_PY})  # slug not "tb"
    grader = _tb_grader(tmp_path)
    blocked = installpolicy.run(
        _req(src, "other"), {"RELYABLE_INSTALLPOLICY_GRADER": grader}
    )
    assert blocked["decision"] == "block" and "unjudgeable" in blocked["reason"]
    allowed = installpolicy.run(
        _req(src, "other"),
        {
            "RELYABLE_INSTALLPOLICY_GRADER": grader,
            "RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE": "allow",
        },
    )
    assert allowed == {"protocolVersion": 1, "decision": "allow"}
