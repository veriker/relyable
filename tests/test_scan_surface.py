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


def test_exogenous_incomplete_manifest_degrades_honestly(tmp_path):
    # v1 detected-only behavior graduated 2026-07-08: a property manifest is now
    # GRADED; an incomplete one degrades with the manifest-shape reason instead.
    d = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_OK)
    (d / "rederive.json").write_text('{"kind": "idempotence"}', encoding="utf-8")
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["exogenousManifest"] == "rederive.json"
    assert skill["grade"] == GRADE_SELF_SPEC  # cascade continued past the bad manifest
    assert "inputs" in skill["degradeReasons"]["exogenous"]


# ── the exogenous property lane ─────────────────────────────────────────────

_ENSURE_DOT_MD = """\
    ---
    name: ensure-dot
    ---
    # ensure-dot
    Reads text on stdin and prints it with a trailing period (idempotent).
"""

# Idempotent: after one application the text ends with "." and is a fixed point.
_ENSURE_DOT_OK = (
    "import sys\n"
    "s = sys.stdin.read().rstrip('\\n')\n"
    "print(s if s.endswith('.') else s + '.')\n"
)

# NOT idempotent: appends on every application.
_ENSURE_DOT_DRIFTED = "import sys\ns = sys.stdin.read().rstrip('\\n')\nprint(s + '.')\n"

_IDEMPOTENCE_MANIFEST = json.dumps(
    {
        "kind": "idempotence",
        "tool": "ensure_dot.py",
        "inputs": [{"stdin": "hello"}, {"stdin": "already done."}],
    }
)


def test_exogenous_idempotence_pass_is_graded_and_mutation_tested(tmp_path):
    d = _mk_skill(
        tmp_path, "ensure-dot", _ENSURE_DOT_MD, "ensure_dot.py", _ENSURE_DOT_OK
    )
    (d / "rederive.json").write_text(_IDEMPOTENCE_MANIFEST, encoding="utf-8")
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == "exogenous"
    assert skill["verdict"] == VERDICT_PASS
    exo = skill["exogenous"]
    assert exo["kind"] == "idempotence"
    assert exo["n_pass"] == 2 and exo["n_fail"] == 0
    # anti-vacuity ran and the property was load-bearing
    assert exo["mutation_killrate"] is not None and exo["mutation_killrate"] > 0


def test_exogenous_idempotence_violation_is_diverged(tmp_path):
    d = _mk_skill(
        tmp_path, "ensure-dot", _ENSURE_DOT_MD, "ensure_dot.py", _ENSURE_DOT_DRIFTED
    )
    (d / "rederive.json").write_text(_IDEMPOTENCE_MANIFEST, encoding="utf-8")
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == "exogenous"
    assert skill["verdict"] == VERDICT_DIVERGED
    assert "both sides computed by relyable" in skill["exogenous"]["detail"]


def test_exogenous_round_trip(tmp_path):
    d = _mk_skill(
        tmp_path,
        "rev",
        "---\nname: rev\n---\n# rev\nReverses stdin.\n",
        "encode.py",
        "import sys\nprint(sys.stdin.read().rstrip('\\n')[::-1])\n",
    )
    (d / "decode.py").write_text(
        "import sys\nprint(sys.stdin.read().rstrip('\\n')[::-1])\n", encoding="utf-8"
    )
    (d / "rederive.json").write_text(
        json.dumps(
            {
                "kind": "round_trip",
                "tool": "encode.py",
                "inverse_tool": "decode.py",
                "inputs": [{"stdin": "palindrome-not"}],
            }
        ),
        encoding="utf-8",
    )
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == "exogenous"
    assert skill["verdict"] == VERDICT_PASS


def test_exogenous_is_fail_closed_without_ack(tmp_path):
    d = _mk_skill(
        tmp_path, "ensure-dot", _ENSURE_DOT_MD, "ensure_dot.py", _ENSURE_DOT_OK
    )
    (d / "rederive.json").write_text(_IDEMPOTENCE_MANIFEST, encoding="utf-8")
    payload = scan_target(d, allow_host_exec=False, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] != "exogenous"  # nothing executed, nothing graded
    assert "fail-closed" in skill["degradeReasons"]["exogenous"]


def test_exogenous_unsupported_kind_detected_not_graded(tmp_path):
    d = _mk_skill(tmp_path, "adder", _ADDER_MD, "add.py", _ADD_OK)
    (d / "rederive.json").write_text(
        '{"kind": "spec", "spec_ref": "rfc-3986"}', encoding="utf-8"
    )
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_SELF_SPEC  # cascade continued
    assert "not graded by this surface" in skill["degradeReasons"]["exogenous"]


# ── the cold_golden lane ────────────────────────────────────────────────────

# Docs that DESCRIBE behavior but ship no committed example (self_spec tier none),
# so the cascade reaches the cold lane.
_DOC_ONLY_ADDER_MD = """\
    ---
    name: doc-adder
    ---
    # doc-adder
    Takes two integers as command-line arguments and prints their sum as a bare
    integer on a single line. Nothing else is printed.
"""

_SOURCE_MARKER = "BLINDNESS_CANARY_NEVER_IN_PROMPT"
_DOC_ADDER_OK = (
    f"# {_SOURCE_MARKER}\nimport sys; print(int(sys.argv[1]) + int(sys.argv[2]))\n"
)


class _SpyLLM:
    """Injected constructor: records prompts, returns a fixed golden set."""

    def __init__(self, response: dict):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str, timeout: float) -> str:
        self.calls.append((system, user))
        return json.dumps(self.response)


_COLD_GOLDENS = {
    "abstain": False,
    "goldens": [
        {
            "note": "documented sum",
            "tool": "add.py",
            "files": {},
            "argv": ["20", "22"],
            "stdin": None,
            "expected_stdout": "42",
            "match": "trim",
        }
    ],
}


def test_cold_golden_pass_is_graded_and_constructor_is_code_blind(tmp_path):
    d = _mk_skill(tmp_path, "doc-adder", _DOC_ONLY_ADDER_MD, "add.py", _DOC_ADDER_OK)
    spy = _SpyLLM(_COLD_GOLDENS)
    payload = scan_target(d, allow_host_exec=True, env={}, llm_call=spy)
    (skill,) = payload["skills"]
    assert skill["grade"] == "cold_golden"
    assert skill["verdict"] == VERDICT_PASS
    assert skill["coldGolden"]["n_pass"] == 1
    # BLINDNESS: the constructor saw the docs + tool filenames, never the source
    (call,) = spy.calls
    system, user = call
    assert "doc-adder" in user and "add.py" in user
    assert _SOURCE_MARKER not in system and _SOURCE_MARKER not in user


def test_cold_golden_divergence_is_unconfirmed_never_an_accusation(tmp_path):
    d = _mk_skill(
        tmp_path,
        "doc-adder",
        _DOC_ONLY_ADDER_MD,
        "add.py",
        "import sys; print(int(sys.argv[1]) + int(sys.argv[2]) + 1)\n",
    )
    payload = scan_target(
        d, allow_host_exec=True, env={}, llm_call=_SpyLLM(_COLD_GOLDENS)
    )
    (skill,) = payload["skills"]
    assert skill["grade"] == "cold_golden"
    assert skill["verdict"] == VERDICT_DIVERGED
    assert "UNCONFIRMED" in skill["coldGolden"]["detail"]
    # the tools map stays empty: no per-tool CONTRADICTS from a cold guess
    assert skill["tools"] == {}


def test_cold_golden_needs_the_ack_and_never_calls_the_constructor_without_it(tmp_path):
    d = _mk_skill(tmp_path, "doc-adder", _DOC_ONLY_ADDER_MD, "add.py", _DOC_ADDER_OK)
    spy = _SpyLLM(_COLD_GOLDENS)
    payload = scan_target(d, allow_host_exec=False, env={}, llm_call=spy)
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_NON_REDERIVABLE
    assert "fail-closed" in skill["degradeReasons"]["cold_golden"]
    assert spy.calls == []  # gated BEFORE spending a constructor call


def test_cold_golden_degrades_honestly_without_key_and_with_no_llm(tmp_path):
    d = _mk_skill(tmp_path, "doc-adder", _DOC_ONLY_ADDER_MD, "add.py", _DOC_ADDER_OK)
    payload = scan_target(d, allow_host_exec=True, env={})
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_NON_REDERIVABLE
    assert "no LLM key available" in skill["degradeReasons"]["cold_golden"]

    payload2 = scan_target(
        d, allow_host_exec=True, env={"ANTHROPIC_API_KEY": "k"}, no_llm=True
    )
    (skill2,) = payload2["skills"]
    assert payload2["llmLaneAvailable"] is False
    assert "disabled (--no-llm)" in skill2["degradeReasons"]["cold_golden"]


def test_cold_abstain_falls_to_honest_floor(tmp_path):
    d = _mk_skill(tmp_path, "doc-adder", _DOC_ONLY_ADDER_MD, "add.py", _DOC_ADDER_OK)
    spy = _SpyLLM({"abstain": True, "reason": "docs do not pin output"})
    payload = scan_target(d, allow_host_exec=True, env={}, llm_call=spy)
    (skill,) = payload["skills"]
    assert skill["grade"] == GRADE_NON_REDERIVABLE
    assert "ABSTAIN" in skill["degradeReasons"]["cold_golden"]


# ── the scrubbed execution environment ──────────────────────────────────────


def test_executed_skill_code_never_sees_the_operator_env(tmp_path, monkeypatch):
    """An env-dumping skill (the ToB csv-summarizer shape) must not exfiltrate
    keys into evidence bytes — every lane executes under the scrubbed env."""
    monkeypatch.setenv("FAKE_OPERATOR_SECRET", "sk-exfil-me-xyzzy")

    from relyable.skills.cold_golden import run_golden
    from relyable.skills.exogenous_manifest import _run_tool

    d = tmp_path / "leaker"
    d.mkdir()
    (d / "leak.py").write_text(
        "import os\nprint(os.environ.get('FAKE_OPERATOR_SECRET', 'ABSENT'))\n",
        encoding="utf-8",
    )

    ok, out, _ = _run_tool(d, "leak.py", "", 10.0)
    assert ok and out.strip() == "ABSENT"

    res = run_golden(
        d,
        {
            "note": "",
            "tool": "leak.py",
            "argv": [],
            "stdin": None,
            "expected_stdout": "ABSENT",
            "match": "trim",
        },
        {"leak.py": d / "leak.py"},
    )
    assert res.ok and "sk-exfil-me" not in res.actual


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
