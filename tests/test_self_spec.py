"""test_self_spec.py — the author-grounded self-spec pass.

Two layers: (1) the conservative S-B parser in isolation (the highest-risk surface —
a mis-extraction would manufacture a false accusation), and (2) end-to-end grading
through the veriker gate, asserting every verdict in the taxonomy fires on a
purpose-built synthetic skill: REPRODUCES, CONTRADICTS, and each UNJUDGEABLE reason.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from relyable.skills import self_spec as ss
from relyable.skills.self_spec import ToolVerdict


# --- skill builders --------------------------------------------------------


def _mk(skill_dir: Path, skill_md: str, tool_rel: str, tool_body: str) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(skill_md), encoding="utf-8")
    tp = skill_dir / tool_rel
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(textwrap.dedent(tool_body), encoding="utf-8")
    return skill_dir


_GET_OK = """\
    import sys, json
    print(json.load(sys.stdin)[sys.argv[1].lstrip(".")])
"""
_GET_BROKEN = """\
    import sys, json
    print(str(json.load(sys.stdin)[sys.argv[1].lstrip(".")]) + "!")
"""
_GET_NONDET = """\
    import sys, json, random
    json.load(sys.stdin)
    print(random.randint(0, 9))
"""
_GET_ENVFAIL = """\
    import nonexistent_module_xyzzy  # noqa
    print("never reached")
"""

_PIPE_MD = """\
    ---
    name: echo-json
    ---
    # echo-json
    ```sh
    $ echo '{"v": 42}' | python scripts/get.py .v
    42
    ```
"""


# --- S-B parser (isolated) -------------------------------------------------


def test_pipe_form_extracts_stdin_and_argv(tmp_path):
    d = _mk(tmp_path / "echo-json", _PIPE_MD, "scripts/get.py", _GET_OK)
    spec = ss.detect_self_spec(d)
    assert spec.tier == "S-B"
    assert len(spec.goldens) == 1
    g = spec.goldens[0]
    assert g.stdin == '{"v": 42}'
    assert g.argv == [".v"]
    assert g.expected == "42"
    assert g.kind == "echo-json:get"


def test_inline_args_only_form(tmp_path):
    md = """\
        ---
        name: adder
        ---
        ```console
        $ python add.py 2 3
        5
        ```
    """
    d = _mk(
        tmp_path / "adder",
        md,
        "add.py",
        "import sys; print(int(sys.argv[1])+int(sys.argv[2]))\n",
    )
    spec = ss.detect_self_spec(d)
    assert spec.tier == "S-B"
    g = spec.goldens[0]
    assert g.stdin is None and g.argv == ["2", "3"] and g.expected == "5"


def test_labeled_file_input_is_materialized(tmp_path):
    md = """\
        ---
        name: filer
        ---
        `in.json`
        ```json
        {"v": 7}
        ```
        ```sh
        $ python read.py in.json
        7
        ```
    """
    d = _mk(
        tmp_path / "filer",
        md,
        "read.py",
        "import sys, json; print(json.load(open(sys.argv[1]))['v'])\n",
    )
    spec = ss.detect_self_spec(d)
    assert spec.tier == "S-B"
    g = spec.goldens[0]
    assert g.inputs == {"in.json": '{"v": 7}'} and g.argv == ["in.json"]


def test_skip_unmaterializable_file(tmp_path):
    md = """\
        ---
        name: filer
        ---
        ```sh
        $ python read.py data/secret.json .v
        99
        ```
    """
    d = _mk(tmp_path / "filer", md, "read.py", "print('x')\n")
    g, skipped = ss._extract_doc_examples(
        ss._read_md(d / "SKILL.md"), ss._invocations(d), "filer"
    )
    assert g == []
    assert any("unmaterializable_input" in s for s in skipped)


def test_skip_truncated_output(tmp_path):
    md = """\
        ---
        name: lister
        ---
        ```sh
        $ echo 'x' | python list.py
        line1
        ...
        ```
    """
    d = _mk(tmp_path / "lister", md, "list.py", "print('line1')\n")
    g, skipped = ss._extract_doc_examples(
        ss._read_md(d / "SKILL.md"), ss._invocations(d), "lister"
    )
    assert g == []
    assert any("truncated_output" in s for s in skipped)


def test_skip_no_output_block(tmp_path):
    md = """\
        ---
        name: q
        ---
        ```sh
        $ echo '{}' | python q.py
        ```
    """
    d = _mk(tmp_path / "q", md, "q.py", "print('hi')\n")
    g, _ = ss._extract_doc_examples(
        ss._read_md(d / "SKILL.md"), ss._invocations(d), "q"
    )
    assert g == []


def test_skip_unknown_tool(tmp_path):
    md = """\
        ---
        name: q
        ---
        ```sh
        $ some-other-cli do-thing
        ok
        ```
    """
    d = _mk(tmp_path / "q", md, "q.py", "print('hi')\n")
    g, skipped = ss._extract_doc_examples(
        ss._read_md(d / "SKILL.md"), ss._invocations(d), "q"
    )
    assert g == []
    assert any("no_known_tool" in s for s in skipped)


def test_skip_redirection(tmp_path):
    md = """\
        ---
        name: q
        ---
        ```sh
        $ echo '{}' | python q.py > out.txt
        done
        ```
    """
    d = _mk(tmp_path / "q", md, "q.py", "print('hi')\n")
    g, skipped = ss._extract_doc_examples(
        ss._read_md(d / "SKILL.md"), ss._invocations(d), "q"
    )
    assert g == []
    assert any("redirection" in s for s in skipped)


def test_split_top_pipe_ignores_quoted_pipe():
    assert ss._split_top_pipe("echo 'a|b' | tool") == ["echo 'a|b'", "tool"]


# --- grader generation -----------------------------------------------------


def test_make_grader_is_valid_python_with_tricky_text():
    cells = {
        "k:t": [
            {
                "inputs": {},
                "stdin": None,
                "argv": ["--x"],
                "read": "stdout",
                "expected": "has 'quotes' and\nnewline {braces}",
            }
        ]
    }
    src = ss.make_self_spec_grader(cells)
    ast.parse(src)  # must be syntactically valid
    assert "no_goldens_for_kind" in src
    assert "import relyable" not in src and "import veriker" not in src  # stdlib only


# --- end-to-end grading through the gate -----------------------------------


def test_grade_reproduces(tmp_path):
    d = _mk(tmp_path / "echo-json", _PIPE_MD, "scripts/get.py", _GET_OK)
    res = ss.grade_self_spec(d)
    assert res.tier == "S-B"
    assert res.per_tool["echo-json:get"] == ToolVerdict.REPRODUCES


def test_grade_contradicts(tmp_path):
    d = _mk(tmp_path / "echo-json", _PIPE_MD, "scripts/get.py", _GET_BROKEN)
    res = ss.grade_self_spec(d)
    assert res.per_tool["echo-json:get"] == ToolVerdict.CONTRADICTS


def test_grade_nondet_caught_by_preflight(tmp_path):
    d = _mk(tmp_path / "echo-json", _PIPE_MD, "scripts/get.py", _GET_NONDET)
    res = ss.grade_self_spec(d)
    assert res.per_tool["echo-json:get"] == ToolVerdict.UNJUDGEABLE_NONDET


def test_grade_env_failure(tmp_path):
    d = _mk(tmp_path / "echo-json", _PIPE_MD, "scripts/get.py", _GET_ENVFAIL)
    res = ss.grade_self_spec(d)
    assert res.per_tool["echo-json:get"] == ToolVerdict.UNJUDGEABLE_ENV


def test_prose_skill_is_no_spec(tmp_path):
    d = tmp_path / "prose"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: prose\n---\n# prose\nJust instructions, no tools.\n"
    )
    spec = ss.detect_self_spec(d)
    assert spec.tier == "none"
    res = ss.grade_self_spec(d, spec)
    assert res.per_tool["_skill"] == ToolVerdict.UNJUDGEABLE_NO_SPEC


def test_fixture_pairing_single_stdin_tool(tmp_path):
    md = "---\nname: up\n---\n# up\nUppercase stdin.\n"
    d = _mk(
        tmp_path / "up",
        md,
        "up.py",
        "import sys; print(sys.stdin.read().strip().upper())\n",
    )
    (d / "examples").mkdir()
    (d / "examples" / "a.in").write_text("hello")
    (d / "examples" / "a.out").write_text("HELLO")
    spec = ss.detect_self_spec(d)
    assert spec.tier == "S-C"
    assert len(spec.goldens) == 1 and spec.goldens[0].expected == "HELLO"
    res = ss.grade_self_spec(d, spec)
    assert res.per_tool["up:up"] == ToolVerdict.REPRODUCES
