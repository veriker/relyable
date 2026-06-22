"""Worked examples for relyable.skills — a stdlib-only consumer grader.

``interval_grader.py`` is a self-contained re-derivation grader the skills binding
can pin as ``grader_src``. It demonstrates the contract a real consumer grader
must satisfy: read the candidate, run it on held-out goldens the grader itself
owns, exit 0 iff it reproduces. Copy it as a starting point for your own domain.
"""
