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
    detect_invocation,
    enumerate_tools,
    pack_native_skill,
    pack_native_tool_bundles,
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

# A second stdin->stdout tool (kind "linecount") for tool-bundle tests.
LINECOUNT_PY = "import sys\nprint(sum(1 for line in sys.stdin if line.strip()))\n"


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


def test_inline_json_metadata_does_not_crash(tmp_path):
    """Real ClawHub SKILL.md files carry inline-flow metadata (e.g.
    `metadata: {"clawdbot": {...}}`) that the subset parser returns as a STRING, not a
    dict. Reading the relyable hint off it must not raise AttributeError — it falls
    back to single-script entrypoint detection and admits."""
    reg = tmp_path / "reg"
    d = tmp_path / "src" / "csvjson"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        '---\nname: csvjson\nmetadata: {"clawdbot": {"emoji": "📦"}}\n---\n# csvjson\n',
        encoding="utf-8",
    )
    (d / "convert.py").write_text(CONVERT_OK, encoding="utf-8")
    pack_native_skill(d, reg / "csvjson", grader_src=GRADER, kind="csvjson")
    assert _admit_one(reg).verdict == ADMIT


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


# --- tool-BUNDLE class (one SKILL.md routing to N bundled tools) ----------------


def test_helper_module_not_ambiguous(tmp_path):
    """A one-tool skill that ships a shared ``_helper.py`` is single-entrypoint —
    the helper is imported BY the tool, not invoked as one — so detect_invocation
    resolves it instead of raising AMBIGUOUS."""
    skill = _skill(
        tmp_path / "src", "one", {"run.py": CONVERT_OK, "_helper.py": "# shared\n"}
    )
    inv = detect_invocation(skill, parse_frontmatter((skill / "SKILL.md").read_text()))
    assert inv.entrypoint == "run.py"


def test_enumerate_tools_lists_all_excludes_helpers(tmp_path):
    skill = _skill(
        tmp_path / "src",
        "multi",
        {"a.py": CONVERT_OK, "b.py": LINECOUNT_PY, "_common.py": "# helper\n"},
    )
    invs = enumerate_tools(skill, parse_frontmatter((skill / "SKILL.md").read_text()))
    assert {Path(i.entrypoint).name for i in invs} == {"a.py", "b.py"}


def _kind_map(stems: dict[str, str]):
    return lambda inv: stems[Path(inv.entrypoint).stem]


def test_tool_bundle_all_tools_admit(tmp_path):
    """Both bundled tools re-derive against their own kind's goldens — N of N."""
    reg = tmp_path / "reg"
    skill = _skill(
        tmp_path / "src",
        "multi",
        {"a.py": CONVERT_OK, "b.py": LINECOUNT_PY, "_common.py": "# helper\n"},
    )
    pack_native_tool_bundles(
        skill,
        reg,
        grader_src=GRADER,
        kind_for=_kind_map({"a": "csvjson", "b": "linecount"}),
    )
    verdicts = admit_directory(reg, grader_src=GRADER, permit_execution=True)
    assert {v.kind for v in verdicts} == {"csvjson", "linecount"}
    assert all(v.verdict == ADMIT for v in verdicts)


def test_tool_bundle_k_of_n_forged_tool_rejected(tmp_path):
    """One tool re-derives, one is forged — exactly K of N admit, honestly."""
    reg = tmp_path / "reg"
    skill = _skill(
        tmp_path / "src", "multi", {"a.py": CONVERT_OK, "b.py": CONVERT_FORGED}
    )
    pack_native_tool_bundles(
        skill,
        reg,
        grader_src=GRADER,
        kind_for=_kind_map({"a": "csvjson", "b": "csvjson"}),
    )
    verdicts = admit_directory(reg, grader_src=GRADER, permit_execution=True)
    by_stem = {v.skill_id.rsplit("-", 1)[-1]: v for v in verdicts}
    assert by_stem["a"].verdict == ADMIT
    assert by_stem["b"].verdict == REJECT
    assert {v.skill_id for v in usable_skills(verdicts)} == {"multi-a"}


def test_tool_bundle_default_kind_convention(tmp_path):
    """Without kind_for, kind defaults to ``<skill-slug>:<tool-stem>``."""
    reg = tmp_path / "reg"
    skill = _skill(tmp_path / "src", "multi", {"a.py": CONVERT_OK, "b.py": CONVERT_OK})
    bundles = pack_native_tool_bundles(skill, reg, grader_src=GRADER)
    assert set(bundles) == {"a", "b"}
    metas = {
        json.loads((reg / stem / "skill" / "meta.json").read_text())["kind"]
        for stem in bundles
    }
    assert metas == {"multi:a", "multi:b"}
