"""test_adapter_hermes_memory.py — relyable as a Hermes MemoryProvider (recall gate).

Drives the provider's prefetch/gate over recompute- and sealed-reference-mode notes
and asserts only re-deriving notes are injected — mirroring the OpenClaw memory
adapter's contract on Hermes's `MemoryProvider.prefetch` surface. Reuses the same
worked graders/fixtures as the OpenClaw memory tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from relyable.adapters.hermes.memory_provider import RelyableMemoryProvider
from relyable.memory import compute_reference_anchor
from relyable.memory.examples import recall_grader, recompute_grader, safe_versions

RECOMPUTE_GRADER = Path(recompute_grader.__file__)
SEALED_GRADER = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent

GOOD = {
    "note_id": "agg",
    "payload": {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}},
    "keywords": ["aggregate", "sum"],
}
STALE = {
    "note_id": "stale",
    "payload": {"items": [3, 1, 2], "result": {"count": 3, "sum": 99, "max": 3}},
    "keywords": ["aggregate", "sum"],
}


def _provider(notes, **kw):
    return RelyableMemoryProvider(notes, grader_src=RECOMPUTE_GRADER, **kw)


def test_prefetch_injects_only_rederiving_note():
    p = _provider([GOOD, STALE])
    out = p.prefetch("recompute the aggregate sum")
    assert "agg" in out and "stale" not in out  # stale cache dropped


def test_gate_recall_audit_trail_has_both_verdicts():
    p = _provider([GOOD, STALE])
    survivors, verdicts = p.gate_recall("aggregate sum")
    assert [n["note_id"] for n in survivors] == ["agg"]
    by_id = {v.note_id: v for v in verdicts}
    assert by_id["agg"].verdict == "ADMIT" and by_id["agg"].rederived
    assert by_id["stale"].verdict == "REJECT" and not by_id["stale"].rederived


def test_empty_query_recalls_nothing():
    p = _provider([GOOD])
    assert p.prefetch("") == ""


def test_no_match_returns_empty():
    p = _provider([GOOD])
    assert p.prefetch("something entirely unrelated to xyzzy") == ""


def test_fully_poisoned_store_is_inert():
    p = _provider([STALE, {**STALE, "note_id": "stale2"}])
    survivors, _ = p.gate_recall("aggregate sum")
    assert survivors == []
    assert p.prefetch("aggregate sum") == ""


def test_malformed_note_never_recalled():
    p = _provider([{"keywords": ["aggregate"]}])  # no note_id/payload
    assert p.gate_recall("aggregate")[0] == []


def test_permit_execution_off_refuses_all():
    p = _provider([GOOD], permit_execution=False)
    survivors, verdicts = p.gate_recall("aggregate sum")
    assert survivors == []
    assert verdicts[0].verdict == "REJECT"


def test_sealed_reference_mode_admits_known_refuses_poison():
    good = {
        "note_id": "pkg",
        "payload": {"package": "acme-http", "version": "1.4.2"},
        "keywords": ["acme"],
    }
    poison = {
        "note_id": "poison",
        "payload": {"package": "acme-http", "version": "9.9.9"},
        "keywords": ["acme"],
    }
    p = RelyableMemoryProvider(
        [good, poison], grader_src=SEALED_GRADER, reference_path=REFERENCE_DIR
    )
    survivors, _ = p.gate_recall("acme version")
    assert [n["note_id"] for n in survivors] == ["pkg"]


def test_reference_anchor_mismatch_refuses_fail_closed():
    good = {
        "note_id": "pkg",
        "payload": {"package": "acme-http", "version": "1.4.2"},
        "keywords": ["acme"],
    }
    real = compute_reference_anchor(REFERENCE_DIR)
    p = RelyableMemoryProvider(
        [good],
        grader_src=SEALED_GRADER,
        reference_path=REFERENCE_DIR,
        reference_anchor=real[:-3] + "000",  # tampered pin
    )
    survivors, verdicts = p.gate_recall("acme")
    assert survivors == []
    assert verdicts[0].reason_code == "REFERENCE_ANCHOR_MISMATCH"


def test_provider_abc_surface():
    p = _provider([GOOD])
    assert p.name == "relyable"
    assert p.is_available() is True
    assert p.get_tool_schemas() == []
    p.initialize("sess-1")  # no raise
    assert p._session_id == "sess-1"


def test_from_env_builds_provider(tmp_path):
    notes_file = tmp_path / "notes.json"
    notes_file.write_text(json.dumps([GOOD]), encoding="utf-8")
    p = RelyableMemoryProvider.from_env(
        {
            "RELYABLE_HERMES_MEMORY_GRADER": str(RECOMPUTE_GRADER),
            "RELYABLE_HERMES_MEMORY_NOTES": str(notes_file),
        }
    )
    assert p.is_available()
    assert "agg" in p.prefetch("aggregate sum")
