"""relyable.skills — admit a stored skill only if its claimed verdict re-derives.

The skills binding of relyable: an agent (or a registry it pulls from) ships a
skill body plus an *asserted* "this passes" label. This binding never reads that
label for the decision. It assembles the candidate into a real veriker bundle,
pins the grader to the **consumer's own trusted copy**, and lets veriker's
verifier re-run the candidate against held-out goldens through the gated
re-derivation lane. A skill is usable iff that re-derivation reproduces — a
poisoned or unverifiable label is **inert** (dropped, never passed through as a
weak signal).

    from relyable.skills import admit_directory, usable_skills

    verdicts = admit_directory(reg_dir, grader_src=my_grader, permit_execution=True)
    for v in usable_skills(verdicts):
        ...  # only skills veriker independently re-derived

The grader (held-out goldens + reference solver) is supplied by the consumer and
is the trust root — see ``relyable/skills/examples/interval_grader.py`` for a
worked, stdlib-only grader. This binding consumes ``relyable.gate``; it shares
the gate's doctrine with the memory binding but keeps its own skill-bundle shape.

Evidence: ALE Exp 3 (gate value isolated where skills are not self-vettable),
Exp 4/5 (a poisoned/unlabeled registry is itself harmful — label integrity must
be infrastructure), Exp 6 powered (the re-derivable label is harm-neutralization,
restoring the baseline an unvetted registry erodes). Honest boundary (Exp 2):
where skills are cheaply self-vettable the gate is redundant, not harmful.
"""

from __future__ import annotations

from .bundle import build_skill_bundle
from .gate import ADMIT, REJECT, AdmissionVerdict, rederive
from .registry import admit_directory, usable_skills
from .property_grader import make_property_grader, property_predicate_source
from .scaffold import Detection, ScaffoldResult, detect_rung, scaffold_grader
from .verdict_grader import make_verdict_grader, write_verdict_grader

__all__ = [
    "ADMIT",
    "REJECT",
    "AdmissionVerdict",
    "Detection",
    "ScaffoldResult",
    "admit_directory",
    "build_skill_bundle",
    "detect_rung",
    "make_property_grader",
    "make_verdict_grader",
    "property_predicate_source",
    "rederive",
    "scaffold_grader",
    "usable_skills",
    "write_verdict_grader",
]
