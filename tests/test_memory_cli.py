"""relyable-memory CLI — exit-code + JSON contract over the recall fault matrix."""

from __future__ import annotations

import json
from pathlib import Path

from relyable.memory.cli import main
from relyable.memory.examples import recall_grader, safe_versions

GRADER = str(Path(recall_grader.__file__))
REFERENCE = str(Path(safe_versions.__file__).parent)


def _args(note, **over):
    a = [
        "check",
        "--note-id",
        over.get("note_id", "n"),
        "--note",
        json.dumps(note),
        "--grader",
        GRADER,
        "--reference",
        REFERENCE,
    ]
    if over.get("json"):
        a.append("--json")
    if over.get("no_run"):
        a.append("--no-run")
    return a


def test_cli_safe_note_exits_zero(capsys):
    rc = main(_args({"package": "acme-http", "version": "1.4.2"}, json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["verdict"] == "ADMIT"


def test_cli_stale_note_exits_nonzero(capsys):
    rc = main(_args({"package": "acme-http", "version": "1.0.0"}))
    capsys.readouterr()
    assert rc == 1


def test_cli_no_run_refuses(capsys):
    rc = main(_args({"package": "acme-http", "version": "1.4.2"}, no_run=True))
    capsys.readouterr()
    assert rc == 1


def test_cli_bad_json_exits_two(capsys):
    rc = main(["check", "--note-id", "n", "--note", "{not json", "--grader", GRADER])
    capsys.readouterr()
    assert rc == 2
