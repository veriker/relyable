"""test_adapter_hermes_learn.py — the Hermes ``/learn`` re-derivation gate.

Drives the REAL adapter (``rederive_learned_skill_guard``) through the REAL Hermes
skill-write rollback contract (``fake_hermes.create_skill`` reproduces upstream
``_create_skill``), packaging a raw ``/learn`` ``SKILL.md`` tree into a REAL veriker
bundle and re-deriving its entrypoint against a consumer grader. Not mocked.

The load-bearing test is ``test_self_verified_but_broken_skill_dropped``: a skill
whose self-authored ``## Verification`` PASSES (proven by running it) but whose
entrypoint FAILS the consumer's held-out golden is dropped anyway — the A~=0
self-spec blind spot (``relyable/skills/self_spec.py``) caught. This is exactly the
author=executor=inspector gap Hermes #25833 names, and the reason a /learn gate
re-derives against a consumer golden instead of trusting the agent's own check.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fake_hermes

from relyable.adapters.hermes import (
    HermesGuardConfig,
    package_learned_skill,
    parse_verification,
    rederive_learned_skill_guard,
)

# --- the consumer's trust root: a grader keyed by skill slug, with held-out -----
# goldens that include a BLANK line (the case a non-blank counter must get right).
# A real consumer ships their own; this stands in for it, pinned here, never bundle-
# supplied. Stdlib only (auditor independence), like the worked exec_skill_grader.
GRADER_SRC = r"""#!/usr/bin/env python3
import argparse, json, subprocess, sys
from pathlib import Path

GOLDENS = {
    # non-blank line count; cells 0 and 2 carry BLANK lines a buggy "count all
    # physical lines" implementation gets wrong.
    "count-nonblank": [("a\n\nb\n", "2"), ("x\ny\nz\n", "3"), ("\n\n", "0")],
}
_RUNNER = {"python": [sys.executable], "sh": ["sh"], "node": ["node"]}

def _norm(s): return s.replace("\r\n", "\n").rstrip("\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    a = ap.parse_args()
    b = Path(a.bundle_dir)
    meta = json.loads((b / "skill" / "meta.json").read_text())
    cells = GOLDENS.get(meta.get("kind"))
    if not cells:
        print(f"no_goldens:{meta.get('kind')}", file=sys.stderr); return 1
    inv = meta.get("invocation") or {}
    ep, runner = inv.get("entrypoint"), inv.get("runner")
    if not ep or runner not in _RUNNER:
        print(f"bad_invocation:{ep}/{runner}", file=sys.stderr); return 1
    ep_path = (b / "skill" / ep).resolve()
    if (b / "skill").resolve() not in ep_path.parents or not ep_path.is_file():
        print(f"ep_not_in_bundle:{ep}", file=sys.stderr); return 1
    cmd = _RUNNER[runner] + [str(ep_path)]
    for i, (ci, go) in enumerate(cells):
        r = subprocess.run(cmd, input=ci, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"cell{i}_exit{r.returncode}:{r.stderr[:120]}", file=sys.stderr); return 1
        if _norm(r.stdout) != _norm(go):
            print(f"cell{i}_mismatch:got={r.stdout!r}", file=sys.stderr); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""

# A correct non-blank counter: split on newlines, count lines with content.
GOOD_COUNT = (
    "import sys\n"
    'lines = sys.stdin.read().split("\\n")\n'
    "print(sum(1 for ln in lines if ln.strip()))\n"
)

# The A~=0 blind spot: counts ALL physical lines, ignoring blankness. Passes the
# author's own non-blank-free Verification input, fails the consumer's blank-line cell.
BLIND_COUNT = "import sys\nprint(len(sys.stdin.read().splitlines()))\n"

# The self-authored check the /learn agent would write — GREEN for BOTH the good
# and the blind implementation (its input has no blank lines: the blind spot).
SELF_VERIFICATION = "printf 'a\\nb\\nc\\n' | python scripts/count.py   # prints 3"
SELF_CHECK_INPUT = "a\nb\nc\n"


def _grader(tmp_path: Path) -> Path:
    g = tmp_path / "count_grader.py"
    g.write_text(GRADER_SRC, encoding="utf-8")
    return g


def _cfg(tmp_path: Path, permit_execution: bool = True) -> HermesGuardConfig:
    return HermesGuardConfig(
        grader_src=_grader(tmp_path), permit_execution=permit_execution
    )


def _write_learn_skill(
    root: Path,
    *,
    count_body: str | None = GOOD_COUNT,
    verification: str | None = SELF_VERIFICATION,
    name: str = "count-nonblank",
) -> Path:
    """Write a raw Hermes /learn skill dir (SKILL.md + optional scripts/count.py)."""
    skill = root / name
    skill.mkdir(parents=True)
    body = [f"---\nname: {name}\ndescription: Count non-blank lines from stdin.\n---\n"]
    body.append(f"# {name}\n\nCounts the non-blank lines read on stdin.\n")
    body.append(
        "## How to Run\nInvoke `scripts/count.py` through the `terminal` tool.\n"
    )
    if verification is not None:
        body.append(f"## Verification\n{verification}\n")
    (skill / "SKILL.md").write_text("\n".join(body), encoding="utf-8")
    if count_body is not None:
        (skill / "scripts").mkdir()
        (skill / "scripts" / "count.py").write_text(count_body, encoding="utf-8")
    return skill


# --- the gate occupies _security_scan_skill's slot for a /learn create ----------
def test_good_learned_skill_admitted_and_survives(tmp_path):
    skill = _write_learn_skill(tmp_path)
    result = fake_hermes.create_skill(
        skill, lambda d: rederive_learned_skill_guard(d, _cfg(tmp_path))
    )
    assert result == {"success": True}
    assert skill.is_dir()  # kept, not rolled back


def test_self_verified_but_broken_skill_dropped(tmp_path):
    """THE load-bearing test: self-check GREEN, consumer golden RED -> dropped."""
    skill = _write_learn_skill(tmp_path, count_body=BLIND_COUNT)

    # 1. Prove the agent's OWN ## Verification passes on the blind implementation.
    check = parse_verification((skill / "SKILL.md").read_text())
    assert check == SELF_VERIFICATION  # the check travels, verbatim
    proc = subprocess.run(
        [sys.executable, str(skill / "scripts" / "count.py")],
        input=SELF_CHECK_INPUT,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "3"  # self-check is GREEN for the buggy skill

    # 2. relyable re-derives against the consumer's held-out golden and DROPS it.
    result = fake_hermes.create_skill(
        skill, lambda d: rederive_learned_skill_guard(d, _cfg(tmp_path))
    )
    assert result["success"] is False
    assert "did not re-derive" in result["error"]
    assert not skill.exists()  # rolled back despite a green self-check


def test_prose_only_skill_abstained_and_kept(tmp_path):
    # No executable oracle -> relyable has no re-derivation basis -> abstain (keep),
    # never assert a verdict it cannot derive.
    skill = _write_learn_skill(tmp_path, count_body=None, verification=None)
    result = fake_hermes.create_skill(
        skill, lambda d: rederive_learned_skill_guard(d, _cfg(tmp_path))
    )
    assert result == {"success": True}
    assert skill.is_dir()


def test_no_skill_md_dropped(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    err = rederive_learned_skill_guard(empty, _cfg(tmp_path))
    assert err is not None
    assert "could not be packaged" in err


def test_unverifiable_refused_fail_closed(tmp_path):
    # permit_execution=False: the entrypoint is never run, so even a correct skill
    # is could-not-conclude -> dropped, never admitted on faith.
    skill = _write_learn_skill(tmp_path)
    err = rederive_learned_skill_guard(skill, _cfg(tmp_path, permit_execution=False))
    assert err is not None
    assert "did not re-derive" in err


# --- packaging: ## Verification travels as an UNTRUSTED hint, never the arbiter --
def test_package_lifts_verification_as_untrusted_hint(tmp_path):
    import json

    skill = _write_learn_skill(tmp_path)
    bundle = package_learned_skill(skill, tmp_path / "bundle", _cfg(tmp_path))
    meta = json.loads((bundle / "skill" / "meta.json").read_text())
    inv = meta["invocation"]
    # the entrypoint the grader actually re-derives was auto-detected
    assert inv["entrypoint"] == "scripts/count.py"
    assert inv["runner"] == "python"
    # the self-authored check is carried, and clearly marked untrusted
    assert inv["self_authored_check"] == SELF_VERIFICATION
    assert "UNTRUSTED" in inv["self_authored_check_source"]


def test_package_without_verification_section_still_packages(tmp_path):
    import json

    skill = _write_learn_skill(tmp_path, verification=None)
    bundle = package_learned_skill(skill, tmp_path / "bundle", _cfg(tmp_path))
    meta = json.loads((bundle / "skill" / "meta.json").read_text())
    # no self-authored check present, but the skill is still re-derivable by entrypoint
    assert "self_authored_check" not in meta["invocation"]
    assert meta["invocation"]["entrypoint"] == "scripts/count.py"


# --- parse_verification unit behavior ------------------------------------------
def test_parse_verification_absent_returns_none():
    assert parse_verification("# Title\n\n## When to Use\n- x\n") is None


def test_parse_verification_stops_at_next_heading():
    md = "## Verification\nrun the check\n\n## Pitfalls\nnope\n"
    assert parse_verification(md) == "run the check"


def test_parse_verification_case_insensitive():
    assert parse_verification("## verification\ncheck it\n") == "check it"
