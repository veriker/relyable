"""Worked examples for relyable.memory — two modes of re-deriving a recalled note.

**1. Recompute (turnkey, no external authority) — start here.**
``recompute_grader.py``: the recalled note is a *cached computation*; the grader
RE-RUNS the computation from the note's own inputs and admits only if the cached
result reproduces. The authority is determinism — nothing to curate, and
``reference_path`` is not needed. This is the mode that fits a solo user.

**2. Sealed reference (when the note is a fact you can't recompute).**
``recall_grader.py`` + ``safe_versions.py``: the note is checked against a sealed
first-party reference the consumer controls (here a stand-in known-good catalog).
The grader imports the reference via the gate-set PYTHONPATH and strips the bundle
directory from ``sys.path``, so a poisoned note cannot smuggle in a fake reference.
This mode is only as strong as the reference is authoritative and out-of-band from
the agent — it leans toward consumers who already own such a source (an internal
feed, a registry, the live environment), not toward hand-maintained truth files.

Copy whichever matches your note and replace the computation / reference rule.
"""
