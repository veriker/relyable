"""relyable.memory reference anchor — pin the sealed reference; catch tampering.

The anchor turns "pin the reference before recall" from advice into an enforced
property: the gate recomputes the reference tree's digest and refuses on mismatch,
fail-closed BEFORE any verify. A reference tampered after it was pinned is caught
even if the tampered version would have admitted the note.
"""

from __future__ import annotations

from pathlib import Path

from relyable.memory import (
    ADMIT,
    REJECT,
    admit_note,
    compute_reference_anchor,
)
from relyable.memory.examples import recall_grader, safe_versions

GRADER_SRC = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent

_SAFE_NOTE = {"package": "acme-http", "version": "1.4.2"}
_REAL_SAFE_VERSIONS = Path(safe_versions.__file__).read_text(encoding="utf-8")


def _sealed_ref(tmp_path) -> Path:
    """A standalone sealed reference dir holding only safe_versions.py (so the
    recall grader can import it), independent of the package examples dir."""
    d = tmp_path / "sealed"
    d.mkdir()
    (d / "safe_versions.py").write_text(_REAL_SAFE_VERSIONS, encoding="utf-8")
    return d


def test_anchor_is_deterministic(tmp_path):
    ref = _sealed_ref(tmp_path)
    assert compute_reference_anchor(ref) == compute_reference_anchor(ref)
    assert len(compute_reference_anchor(ref)) == 64  # sha256 hex


def test_matching_anchor_admits(tmp_path):
    ref = _sealed_ref(tmp_path)
    anchor = compute_reference_anchor(ref)
    v = admit_note(
        "ok",
        _SAFE_NOTE,
        grader_src=GRADER_SRC,
        reference_path=ref,
        reference_anchor=anchor,
    )
    assert v.verdict == ADMIT


def test_wrong_anchor_refuses_even_a_safe_note(tmp_path):
    ref = _sealed_ref(tmp_path)
    v = admit_note(
        "ok",
        _SAFE_NOTE,
        grader_src=GRADER_SRC,
        reference_path=ref,
        reference_anchor="0" * 64,
    )
    assert v.verdict == REJECT
    assert v.reason_code == "REFERENCE_ANCHOR_MISMATCH"


def test_tampered_reference_is_caught(tmp_path):
    """Pin the reference, then tamper it to whitelist everything. A would-be-stale
    note is refused on the anchor — the tampered reference never gets consulted."""
    ref = _sealed_ref(tmp_path)
    anchor = compute_reference_anchor(ref)
    # tamper: rewrite the sealed reference so is_safe() always returns True
    (ref / "safe_versions.py").write_text(
        "def is_known_package(p):\n return True\ndef is_safe(p, v):\n return True\n",
        encoding="utf-8",
    )
    v = admit_note(
        "evil",
        {"package": "acme-http", "version": "9.9.9"},  # would pass the tampered ref
        grader_src=GRADER_SRC,
        reference_path=ref,
        reference_anchor=anchor,
    )
    assert v.verdict == REJECT
    assert v.reason_code == "REFERENCE_ANCHOR_MISMATCH"


def test_anchor_without_reference_path_refuses(tmp_path):
    v = admit_note(
        "x",
        _SAFE_NOTE,
        grader_src=GRADER_SRC,
        reference_path=None,
        reference_anchor="abc",
    )
    assert v.verdict == REJECT
    assert v.reason_code == "REFERENCE_ANCHOR_NO_REFERENCE"


def test_no_anchor_is_advisory(tmp_path):
    """Backward-compatible: no anchor supplied -> no enforcement, note re-derives
    normally against the reference."""
    ref = _sealed_ref(tmp_path)
    v = admit_note("ok", _SAFE_NOTE, grader_src=GRADER_SRC, reference_path=ref)
    assert v.verdict == ADMIT


# --- CLI ----------------------------------------------------------------------
def test_cli_anchor_prints_digest(tmp_path, capsys):
    from relyable.memory.cli import main

    ref = _sealed_ref(tmp_path)
    rc = main(["anchor", str(ref)])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == compute_reference_anchor(ref)


def test_cli_check_with_anchor(tmp_path, capsys):
    from relyable.memory.cli import main

    ref = _sealed_ref(tmp_path)
    anchor = compute_reference_anchor(ref)
    import json

    note = json.dumps(_SAFE_NOTE)
    ok = main(
        [
            "check",
            "--note-id",
            "n",
            "--note",
            note,
            "--grader",
            str(GRADER_SRC),
            "--reference",
            str(ref),
            "--reference-anchor",
            anchor,
        ]
    )
    capsys.readouterr()
    bad = main(
        [
            "check",
            "--note-id",
            "n",
            "--note",
            note,
            "--grader",
            str(GRADER_SRC),
            "--reference",
            str(ref),
            "--reference-anchor",
            "0" * 64,
        ]
    )
    capsys.readouterr()
    assert ok == 0
    assert bad == 1
