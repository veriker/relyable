"""relyable.memory — re-derive a recalled note at recall.

Two modes: recompute (the note is a cached computation; the grader re-runs it from
the note's own inputs, no reference needed) and sealed-reference (the note is a
fact; the grader checks it against a sealed first-party reference imported from the
gate-set PYTHONPATH, never the bundle). In both, the recalled payload is never
trusted as a value — the verdict is veriker's re-derivation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from relyable.memory import ADMIT, REJECT, admit_note, build_note_bundle
from relyable.memory.examples import recall_grader, recompute_grader, safe_versions
from relyable.gate import verify_attested_bundle

GRADER_SRC = Path(recall_grader.__file__)
REFERENCE_DIR = Path(safe_versions.__file__).parent
RECOMPUTE_GRADER = Path(recompute_grader.__file__)


def _admit(note_id, payload, **kw):
    kw.setdefault("grader_src", GRADER_SRC)
    kw.setdefault("reference_path", REFERENCE_DIR)
    return admit_note(note_id, payload, **kw)


# --- mode 1: recompute (turnkey — no reference_path) --------------------------
def test_recompute_admits_correct_cache():
    """A cached computation that still recomputes from its own inputs is admitted —
    with NO reference_path (the authority is determinism)."""
    note = {"items": [3, 1, 2], "result": {"count": 3, "sum": 6, "max": 3}}
    v = admit_note("agg", note, grader_src=RECOMPUTE_GRADER)
    assert v.verdict == ADMIT
    assert v.rederived is True


def test_recompute_refuses_tampered_cache():
    """A poisoned cached result that no longer recomputes is refused — the cached
    value is compared against, never trusted."""
    note = {"items": [3, 1, 2], "result": {"count": 3, "sum": 999, "max": 3}}
    v = admit_note("agg", note, grader_src=RECOMPUTE_GRADER)
    assert v.verdict == REJECT
    assert v.rederived is False


def test_recompute_refuses_wrong_shape():
    v = admit_note(
        "agg", {"items": "not-a-list", "result": {}}, grader_src=RECOMPUTE_GRADER
    )
    assert v.verdict == REJECT


# --- mode 2: sealed reference (fact-check against an out-of-band authority) ----
def test_sealed_safe_note_admits():
    v = _admit("ok", {"package": "acme-http", "version": "1.4.2"})
    assert v.verdict == ADMIT
    assert v.reason_code == "RE_DERIVED"
    assert v.rederived is True


def test_stale_version_refused():
    """A recalled version not in the sealed catalog does not re-derive -> REJECT."""
    v = _admit("stale", {"package": "acme-http", "version": "1.0.0"})
    assert v.verdict == REJECT
    assert v.rederived is False


def test_unknown_package_refused():
    v = _admit("unk", {"package": "nope-pkg", "version": "1.0.0"})
    assert v.verdict == REJECT


def test_malformed_note_refused():
    v = _admit("bad", {"package": "acme-http"})  # no version
    assert v.verdict == REJECT


def test_recalled_value_never_trusted():
    """Even a note whose payload *claims* it is safe is refused unless it actually
    re-derives against the sealed reference — the payload is not an input."""
    v = _admit(
        "liar",
        {
            "package": "acme-http",
            "version": "9.9.9",
            "claimed": "safe",
            "verified": True,
        },
    )
    assert v.verdict == REJECT


def test_wont_run_is_could_not_conclude():
    v = _admit(
        "noexec", {"package": "acme-http", "version": "1.4.2"}, permit_execution=False
    )
    assert v.verdict == REJECT
    assert v.rederived is False


def test_admission_is_deterministic():
    a = _admit("d", {"package": "widget-core", "version": "3.1.0"})
    b = _admit("d", {"package": "widget-core", "version": "3.1.0"})
    assert (
        (a.verdict, a.reason_code)
        == (b.verdict, b.reason_code)
        == (ADMIT, "RE_DERIVED")
    )


# --- the distinctive axis: the sealed reference is out-of-band -----------------
def test_poisoned_bundle_cannot_smuggle_a_fake_reference(tmp_path):
    """A poisoned note ships its OWN fake safe_versions.py (always 'safe') inside
    the bundle. The grader strips the bundle dir from sys.path and imports the
    sealed reference from the gate-set PYTHONPATH, so the fake never loads and a
    stale/poisoned version is still refused."""
    bdir = build_note_bundle(
        tmp_path / "evil",
        note_id="evil",
        payload={"package": "acme-http", "version": "9.9.9"},
        grader_src=GRADER_SRC,
    )
    # smuggle a fake reference that would whitelist everything
    (bdir / "re_derive" / "safe_versions.py").write_text(
        "def is_known_package(p):\n return True\ndef is_safe(p, v):\n return True\n",
        encoding="utf-8",
    )
    res = verify_attested_bundle(
        bdir,
        grader_src=GRADER_SRC,
        permit_execution=True,
        env_pythonpath=str(REFERENCE_DIR),
    )
    # The smuggled file is also an undeclared extra -> veriker conservation rejects
    # it; and even if declared, the grader would not import it. Either way: refused.
    assert res.ok is False


def test_no_reference_path_refuses(tmp_path):
    """Without a reference on PYTHONPATH the grader cannot import the sealed module
    and the note is refused (fail-closed), never spuriously admitted."""
    v = admit_note(
        "noref",
        {"package": "acme-http", "version": "1.4.2"},
        grader_src=GRADER_SRC,
        reference_path=None,
    )
    assert v.verdict == REJECT


# --- the gate-shared poisoned-inert axes (inherited from relyable.gate) --------
def test_grader_pin_rejects_self_consistent_lying_grader(tmp_path):
    """A hand-assembled bundle whose manifest is self-consistent with a lying
    exit(0) grader still fails the digest-pin — ADMIT is impossible unless the
    consumer's own grader graded the note."""
    bdir = build_note_bundle(
        tmp_path / "evil",
        note_id="evil",
        payload={"package": "acme-http", "version": "9.9.9"},
        grader_src=GRADER_SRC,
    )
    lying = "import sys\nsys.exit(0)\n"
    grader = bdir / "re_derive" / GRADER_SRC.name
    grader.write_text(lying, encoding="utf-8")
    man = json.loads((bdir / "manifest.json").read_text())
    man["files"][f"re_derive/{GRADER_SRC.name}"] = hashlib.sha256(
        lying.encode()
    ).hexdigest()
    (bdir / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    res = verify_attested_bundle(
        bdir,
        grader_src=GRADER_SRC,
        permit_execution=True,
        env_pythonpath=str(REFERENCE_DIR),
    )
    assert res.grader_ok is False
    assert res.grader_reason_code == "GRADER_MISMATCH"


def test_digest_rail_is_veriker_strict_sha(tmp_path):
    """Swap the recalled payload after the manifest is written -> veriker strict-SHA
    rejects (bad_file_sha)."""
    bdir = build_note_bundle(
        tmp_path / "swap",
        note_id="swap",
        payload={"package": "acme-http", "version": "1.4.2"},
        grader_src=GRADER_SRC,
    )
    (bdir / "skill" / "candidate.py").write_text(
        "RECALLED = {'package': 'acme-http', 'version': '9.9.9'}\n", encoding="utf-8"
    )
    res = verify_attested_bundle(
        bdir,
        grader_src=GRADER_SRC,
        permit_execution=True,
        env_pythonpath=str(REFERENCE_DIR),
    )
    assert res.ok is False
    assert res.first_reason_code == "bad_file_sha"
