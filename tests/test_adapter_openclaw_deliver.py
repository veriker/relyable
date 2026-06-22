"""test_adapter_openclaw_deliver.py — the OpenClaw deliver-edge gate (Python side).

The output-edge sibling of ``test_adapter_openclaw.py``. The TS plugin's integration
proof (the real ``message_sending`` hook + the subprocess boundary) lives in
``relyable/adapters/openclaw/plugin/deliver-gate.test.mjs`` (run via ``node --test``).
This file exercises the Python side the plugin spawns: the batch gate over REAL
relyable re-derivations and the CLI as an actual subprocess (the exact stdin-JSON /
stdout-JSON contract the plugin uses). A deliverable that re-derives is delivered; a
fabricated one is suppressed (the openclaw#49876 fail-closed posture).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from relyable.adapters.openclaw import (
    DeliverGateConfig,
    admitted_deliverable_ids,
    cancelled_deliverable_ids,
    gate_deliverables,
)
from relyable.memory import compute_reference_anchor
from relyable.memory.examples import recall_grader, recompute_grader, safe_versions

RECOMPUTE_GRADER = Path(recompute_grader.__file__)
SEALED_GRADER = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent
PRODUCT_ROOT = Path(__file__).resolve().parents[1]

GOOD = {
    "deliverable_id": "brief",
    "payload": {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}},
}
FABRICATED = {
    "deliverable_id": "fake-brief",
    "payload": {"items": [3, 1, 2], "result": {"count": 3, "sum": 99, "max": 3}},
}


# --- recompute mode (no reference) --------------------------------------------
def test_batch_delivers_good_suppresses_fabricated():
    cfg = DeliverGateConfig(grader_src=RECOMPUTE_GRADER)
    results = gate_deliverables([GOOD, FABRICATED], cfg)
    assert admitted_deliverable_ids(results) == ["brief"]
    assert cancelled_deliverable_ids(results) == ["fake-brief"]
    by_id = {r.deliverable_id: r for r in results}
    assert by_id["brief"].verdict == "ADMIT" and by_id["brief"].cancelled is False
    assert by_id["fake-brief"].verdict == "REJECT" and by_id["fake-brief"].cancelled


def test_malformed_candidate_suppressed_not_skipped():
    cfg = DeliverGateConfig(grader_src=RECOMPUTE_GRADER)
    results = gate_deliverables([{"deliverable_id": "x"}], cfg)  # no payload
    assert results[0].verdict == "REJECT"
    assert results[0].reason_code == "MALFORMED_CANDIDATE"
    assert results[0].cancelled is True


def test_id_falls_back_when_unnamed():
    cfg = DeliverGateConfig(grader_src=RECOMPUTE_GRADER)
    results = gate_deliverables([{"payload": GOOD["payload"]}], cfg)
    assert results[0].deliverable_id == "deliverable_0"
    assert results[0].verdict == "ADMIT"


# --- sealed-reference mode ----------------------------------------------------
def test_sealed_reference_delivers_known_good_suppresses_unknown():
    cfg = DeliverGateConfig(grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR)
    good = {
        "deliverable_id": "pkg",
        "payload": {"package": "acme-http", "version": "1.4.2"},
    }
    bad = {
        "deliverable_id": "poison",
        "payload": {"package": "acme-http", "version": "9.9.9"},
    }
    results = gate_deliverables([good, bad], cfg)
    assert admitted_deliverable_ids(results) == ["pkg"]
    assert cancelled_deliverable_ids(results) == ["poison"]


def test_reference_anchor_mismatch_suppressed_fail_closed():
    cfg = DeliverGateConfig(
        grader_src=SEALED_GRADER,
        reference_path=REFERENCE_DIR,
        reference_anchor="sha256:" + "0" * 64,
    )
    good = {
        "deliverable_id": "pkg",
        "payload": {"package": "acme-http", "version": "1.4.2"},
    }
    results = gate_deliverables([good], cfg)
    assert results[0].verdict == "REJECT"
    assert results[0].reason_code == "REFERENCE_ANCHOR_MISMATCH"


def test_reference_anchor_match_delivers():
    anchor = compute_reference_anchor(REFERENCE_DIR)
    cfg = DeliverGateConfig(
        grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR, reference_anchor=anchor
    )
    good = {
        "deliverable_id": "pkg",
        "payload": {"package": "acme-http", "version": "1.4.2"},
    }
    results = gate_deliverables([good], cfg)
    assert admitted_deliverable_ids(results) == ["pkg"]


# --- the CLI as a real subprocess (the plugin's actual contract) --------------
def _run_cli(candidates, env):
    return subprocess.run(
        [sys.executable, "-m", "relyable.adapters.openclaw.deliver_cli"],
        input=json.dumps({"candidates": candidates}),
        capture_output=True,
        text=True,
        cwd=PRODUCT_ROOT,
        env=env,
    )


def test_cli_subprocess_deliver_suppress():
    import os

    env = {**os.environ, "RELYABLE_OPENCLAW_DELIVER_GRADER": str(RECOMPUTE_GRADER)}
    proc = _run_cli([GOOD, FABRICATED], env)
    assert proc.returncode == 1  # a suppressed deliverable -> non-zero (fail closed)
    out = json.loads(proc.stdout)
    assert out["admitted"] == ["brief"]
    assert out["cancelled"] == ["fake-brief"]
    assert {r["deliverable_id"]: r["verdict"] for r in out["results"]} == {
        "brief": "ADMIT",
        "fake-brief": "REJECT",
    }


def test_cli_subprocess_all_deliver_exit_zero():
    import os

    env = {**os.environ, "RELYABLE_OPENCLAW_DELIVER_GRADER": str(RECOMPUTE_GRADER)}
    proc = _run_cli([GOOD], env)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["admitted"] == ["brief"]


def test_cli_subprocess_missing_grader_is_usage_error():
    import os

    env = {
        k: v for k, v in os.environ.items() if k != "RELYABLE_OPENCLAW_DELIVER_GRADER"
    }
    proc = _run_cli([GOOD], env)
    assert proc.returncode == 2
    assert "RELYABLE_OPENCLAW_DELIVER_GRADER is required" in proc.stderr


# --- config from env ----------------------------------------------------------
def test_config_from_env_requires_grader():
    import pytest

    with pytest.raises(
        ValueError, match="RELYABLE_OPENCLAW_DELIVER_GRADER is required"
    ):
        DeliverGateConfig.from_env({})


def test_config_from_env_parses():
    cfg = DeliverGateConfig.from_env(
        {
            "RELYABLE_OPENCLAW_DELIVER_GRADER": str(SEALED_GRADER),
            "RELYABLE_OPENCLAW_DELIVER_REFERENCE": str(REFERENCE_DIR),
            "RELYABLE_OPENCLAW_DELIVER_NO_RUN": "1",
        }
    )
    assert cfg.grader_src == SEALED_GRADER
    assert cfg.reference_path == REFERENCE_DIR
    assert cfg.permit_execution is False
