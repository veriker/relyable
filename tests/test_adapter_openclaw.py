"""test_adapter_openclaw.py — the OpenClaw recall gate (Python side).

The TS plugin's integration proof (the real before_prompt_build hook + the
subprocess boundary) lives in
``relyable/adapters/openclaw/plugin/recall-gate.test.mjs`` (run via ``node --test``).
This file exercises the Python side the plugin spawns: the batch gate over REAL
relyable.memory re-derivations (recompute + sealed-reference modes) and the CLI as
an actual subprocess (the exact stdin-JSON / stdout-JSON contract the plugin uses).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from relyable.adapters.openclaw import (
    RecallGateConfig,
    admitted_note_ids,
    gate_recalled_notes,
)
from relyable.memory import compute_reference_anchor
from relyable.memory.examples import recall_grader, recompute_grader, safe_versions

RECOMPUTE_GRADER = Path(recompute_grader.__file__)
SEALED_GRADER = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent
PRODUCT_ROOT = Path(__file__).resolve().parents[1]

GOOD_CACHE = {
    "note_id": "agg",
    "payload": {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}},
}
STALE_CACHE = {
    "note_id": "stale",
    "payload": {"items": [3, 1, 2], "result": {"count": 3, "sum": 99, "max": 3}},
}


# --- recompute mode (no reference) --------------------------------------------
def test_batch_admits_good_refuses_stale():
    cfg = RecallGateConfig(grader_src=RECOMPUTE_GRADER)
    results = gate_recalled_notes([GOOD_CACHE, STALE_CACHE], cfg)
    assert admitted_note_ids(results) == ["agg"]
    by_id = {r.note_id: r for r in results}
    assert by_id["agg"].verdict == "ADMIT" and by_id["agg"].rederived is True
    assert by_id["stale"].verdict == "REJECT" and by_id["stale"].rederived is False


def test_malformed_candidate_refused_not_skipped():
    cfg = RecallGateConfig(grader_src=RECOMPUTE_GRADER)
    results = gate_recalled_notes([{"note_id": "x"}], cfg)  # no payload
    assert results[0].verdict == "REJECT"
    assert results[0].reason_code == "MALFORMED_CANDIDATE"


# --- sealed-reference mode ----------------------------------------------------
def test_sealed_reference_admits_known_good_refuses_unknown():
    cfg = RecallGateConfig(grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR)
    good = {"note_id": "pkg", "payload": {"package": "acme-http", "version": "1.4.2"}}
    bad = {"note_id": "poison", "payload": {"package": "acme-http", "version": "9.9.9"}}
    results = gate_recalled_notes([good, bad], cfg)
    assert admitted_note_ids(results) == ["pkg"]


def test_reference_anchor_mismatch_refuses_fail_closed():
    # A pinned reference whose digest no longer matches is refused before any verify.
    cfg = RecallGateConfig(
        grader_src=SEALED_GRADER,
        reference_path=REFERENCE_DIR,
        reference_anchor="sha256:" + "0" * 64,
    )
    good = {"note_id": "pkg", "payload": {"package": "acme-http", "version": "1.4.2"}}
    results = gate_recalled_notes([good], cfg)
    assert results[0].verdict == "REJECT"
    assert results[0].reason_code == "REFERENCE_ANCHOR_MISMATCH"


def test_reference_anchor_match_admits():
    anchor = compute_reference_anchor(REFERENCE_DIR)
    cfg = RecallGateConfig(
        grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR, reference_anchor=anchor
    )
    good = {"note_id": "pkg", "payload": {"package": "acme-http", "version": "1.4.2"}}
    results = gate_recalled_notes([good], cfg)
    assert admitted_note_ids(results) == ["pkg"]


# --- the CLI as a real subprocess (the plugin's actual contract) --------------
def _run_cli(candidates, env):
    return subprocess.run(
        [sys.executable, "-m", "relyable.adapters.openclaw.cli"],
        input=json.dumps({"candidates": candidates}),
        capture_output=True,
        text=True,
        cwd=PRODUCT_ROOT,
        env=env,
    )


def test_cli_subprocess_admit_refuse():
    import os

    env = {**os.environ, "RELYABLE_OPENCLAW_GRADER": str(RECOMPUTE_GRADER)}
    proc = _run_cli([GOOD_CACHE, STALE_CACHE], env)
    assert proc.returncode == 1  # a refused candidate -> non-zero (fail closed)
    out = json.loads(proc.stdout)
    assert out["admitted"] == ["agg"]
    assert {r["note_id"]: r["verdict"] for r in out["results"]} == {
        "agg": "ADMIT",
        "stale": "REJECT",
    }


def test_cli_subprocess_all_admit_exit_zero():
    import os

    env = {**os.environ, "RELYABLE_OPENCLAW_GRADER": str(RECOMPUTE_GRADER)}
    proc = _run_cli([GOOD_CACHE], env)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["admitted"] == ["agg"]


def test_cli_subprocess_missing_grader_is_usage_error():
    import os

    env = {k: v for k, v in os.environ.items() if k != "RELYABLE_OPENCLAW_GRADER"}
    proc = _run_cli([GOOD_CACHE], env)
    assert proc.returncode == 2
    assert "RELYABLE_OPENCLAW_GRADER is required" in proc.stderr


# --- config from env ----------------------------------------------------------
def test_config_from_env_requires_grader():
    import pytest

    with pytest.raises(ValueError, match="RELYABLE_OPENCLAW_GRADER is required"):
        RecallGateConfig.from_env({})


def test_config_from_env_parses():
    cfg = RecallGateConfig.from_env(
        {
            "RELYABLE_OPENCLAW_GRADER": str(SEALED_GRADER),
            "RELYABLE_OPENCLAW_REFERENCE": str(REFERENCE_DIR),
            "RELYABLE_OPENCLAW_NO_RUN": "1",
        }
    )
    assert cfg.grader_src == SEALED_GRADER
    assert cfg.reference_path == REFERENCE_DIR
    assert cfg.permit_execution is False
