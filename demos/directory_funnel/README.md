# Directory funnel — honest sizing of a marketplace's re-derivable surface

`funnel.py` answers the question the poisoned-label demo doesn't: *across a whole
skills directory, how much can the install gate actually adjudicate?* It classifies
every skill with the same scope gate the install gate uses and reports the funnel:

```
N skills → M with a runnable entrypoint + I/O contract (CANDIDATES)
             → K of M auto-scaffold a trust root (T1 suite) vs need consumer goldens
         → (N−M) prose / instruction / external-CLI (out of scope by design)
```

## Run it

```bash
# Over any directory of native skills (one subdir each, with SKILL.md):
python funnel.py /path/to/skills_dir
python funnel.py /path/to/skills_dir --json

# Or fetch a real ClawHub sample into a scratch home and funnel it:
PYTHON=/path/to/venv/bin/python bash collect_clawhub_sample.sh
```

## Why this is the honest artifact, not a vanity metric

The temptation in a marketplace pitch is "we vet every skill." The funnel refuses
that: most ClawHub skills are prose/instruction with no deterministic oracle, so the
gate is **out of scope** for them by design (it refuses rather than fabricate a
verdict). The funnel sizes the slice the gate can *truthfully* gate — the
executable-skill class — and shows that **grader provisioning** (where the goldens
come from), not skill volume, is the binding constraint.

See `FUNNEL_RUN.md` for a captured run over 18 real ClawHub skills (M=1) and the full
strategic reading.
