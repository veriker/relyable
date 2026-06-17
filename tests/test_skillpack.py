"""test_skillpack.py — the native-skill packaging seam end to end.

Drives ClawHub-style native skills (SKILL.md + scripts) through
``pack_native_skill`` -> ``admit_directory`` and asserts ADMIT/REJECT exactly like
the Hermes adapter tests. Exercises option B (multi-file / non-Python artifact
tree), the scope gate (prose-only -> OutOfScope), and the producer-can't-lie rail
(forged output + lying invocation both REJECT). permit_execution=True throughout —
this gate vets by running the skill's entrypoint on the consumer's goldens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from relyable.adapters._skillpack import (
    AMBIGUOUS_ENTRYPOINT,
    OUT_OF_SCOPE_PROSE_SKILL,
    Invocation,
    OutOfScope,
    pack_native_skill,
    parse_frontmatter,
)
from relyable.skills import ADMIT, REJECT, admit_directory, usable_skills
from relyable.skills import examples

GRADER = Path(examples.__file__).parent / "exec_skill_grader.py"

CONVERT_OK = """\
import sys, json, csv
print(json.dumps(list(csv.DictReader(sys.stdin))))
"""

CONVERT_FORGED = """\
print("[]")  # ignores input, never reproduces the goldens
"""

COUNT_SH = "awk 'NF{c++} END{print c+0}'\n"


def _skill(root: Path, name: str, files: dict[str, str], kind_hint: str = "") -> Path:
    d = root / name
    d.mkdir(parents=True)
    fm = f"---\nname: {name}\nversion: 0.1.0\n"
    if kind_hint:
        fm += kind_hint
    fm += "---\n# " + name + "\nA native ClawHub-style skill.\n"
    (d / "SKILL.md").write_text(fm, encoding="utf-8")
    for rel, body in files.items():
        (d / rel).write_text(body, encoding="utf-8")
    return d


def _admit_one(bundle_parent: Path) -> object:
    verdicts = admit_directory(bundle_parent, grader_src=GRADER, permit_execution=True)
    assert len(verdicts) == 1
    return verdicts[0]


def test_frontmatter_parser_basics():
    fm = parse_frontmatter(
        "---\nname: foo\nmetadata:\n  relyable:\n"
        "    entrypoint: run.py\n  bins: [git, jq]\n---\nbody\n"
    )
    assert fm["name"] == "foo"
    assert fm["metadata"]["relyable"]["entrypoint"] == "run.py"
    assert fm["metadata"]["bins"] == ["git", "jq"]


def test_python_skill_admitted(tmp_path):
    reg = tmp_path / "reg"
    skill = _skill(tmp_path / "src", "csvjson", {"convert.py": CONVERT_OK})
    pack_native_skill(skill, reg / "csvjson", grader_src=GRADER, kind="csvjson")
    v = _admit_one(reg)
    assert v.verdict == ADMIT
    assert v.reason_code == "RE_DERIVED"


def test_shell_multifile_skill_admitted_option_b(tmp_path):
    """Non-Python entrypoint + the SKILL.md alongside it — exercises the artifact
    tree carrying more than one file (option B)."""
    reg = tmp_path / "reg"
    skill = _skill(tmp_path / "src", "linecount", {"count.sh": COUNT_SH})
    dest = reg / "linecount"
    pack_native_skill(skill, dest, grader_src=GRADER, kind="linecount")

    # Manifest digest-binds BOTH the SKILL.md and the script (not just one file).
    manifest = json.loads((dest / "manifest.json").read_text())
    assert "skill/SKILL.md" in manifest["files"]
    assert "skill/count.sh" in manifest["files"]

    v = _admit_one(reg)
    assert v.verdict == ADMIT
    assert v.kind == "linecount"


def test_forged_skill_rejected(tmp_path):
    reg = tmp_path / "reg"
    skill = _skill(tmp_path / "src", "csvjson", {"convert.py": CONVERT_FORGED})
    pack_native_skill(skill, reg / "csvjson", grader_src=GRADER, kind="csvjson")
    v = _admit_one(reg)
    assert v.verdict == REJECT
    assert v.rederived_label == "REJECTED"


def test_lying_invocation_rejected(tmp_path):
    """A correct skill body but an invocation naming a file not in the bundle must
    fail closed — the grader (consumer code) owns the I/O check, not meta."""
    reg = tmp_path / "reg"
    skill = _skill(tmp_path / "src", "csvjson", {"convert.py": CONVERT_OK})
    pack_native_skill(
        skill,
        reg / "csvjson",
        grader_src=GRADER,
        kind="csvjson",
        invocation=Invocation(entrypoint="ghost.py", runner="python"),
    )
    v = _admit_one(reg)
    assert v.verdict == REJECT


def test_prose_only_skill_out_of_scope(tmp_path):
    skill = _skill(tmp_path / "src", "writing-tips", {})  # SKILL.md only, no script
    with pytest.raises(OutOfScope) as ei:
        pack_native_skill(skill, tmp_path / "reg" / "x", grader_src=GRADER)
    assert ei.value.reason_code == OUT_OF_SCOPE_PROSE_SKILL


def test_ambiguous_entrypoint_out_of_scope(tmp_path):
    skill = _skill(tmp_path / "src", "multi", {"a.py": CONVERT_OK, "b.py": CONVERT_OK})
    with pytest.raises(OutOfScope) as ei:
        pack_native_skill(skill, tmp_path / "reg" / "x", grader_src=GRADER)
    assert ei.value.reason_code == AMBIGUOUS_ENTRYPOINT


def test_mixed_registry_exposes_only_admitted(tmp_path):
    reg = tmp_path / "reg"
    src = tmp_path / "src"
    pack_native_skill(
        _skill(src, "good", {"convert.py": CONVERT_OK}),
        reg / "good",
        grader_src=GRADER,
        kind="csvjson",
    )
    pack_native_skill(
        _skill(src, "bad", {"convert.py": CONVERT_FORGED}),
        reg / "bad",
        grader_src=GRADER,
        kind="csvjson",
    )
    verdicts = admit_directory(reg, grader_src=GRADER, permit_execution=True)
    assert len(verdicts) == 2
    usable = usable_skills(verdicts)
    assert {v.skill_id for v in usable} == {"good"}
