# Tool-bundle re-derivation — captured run + strategic reading

In-process run of `rederive_bundle.py` over the real `clean-json-toolkit` (installed
from ClawHub at `~/.openclaw/skills/clean-json-toolkit`, v0.2.0), 2026-06-18, against
`relyable` @ `session/tool-bundle-slice` + veriker 0.1.2.

## Honest run

```
$ python rederive_bundle.py
Skill: clean-json-toolkit   tools: 7
Consumer grader: json_toolkit_grader.py
  held-out goldens:
    clean-json-toolkit:flatten       2 cell(s)
    clean-json-toolkit:query         3 cell(s)

Per-tool re-derivation:
    clean-json-toolkit:check_deps    UNJUDGEABLE  plugin_failed
    clean-json-toolkit:flatten       ADMIT        RE_DERIVED
    clean-json-toolkit:inspect       UNJUDGEABLE  plugin_failed
    clean-json-toolkit:merge         UNJUDGEABLE  plugin_failed
    clean-json-toolkit:patch         UNJUDGEABLE  plugin_failed
    clean-json-toolkit:query         ADMIT        RE_DERIVED
    clean-json-toolkit:validate      UNJUDGEABLE  plugin_failed

K of N: 2 of 7 tools re-derive -> ['clean-json-toolkit:flatten', 'clean-json-toolkit:query']
OpenClaw install-policy decision: {'protocolVersion': 1, 'decision': 'allow'}
```

## Broken-tool run (`--break query`)

`query.py`'s `--raw` mode is sabotaged so it leaves quotes on string scalars — it
still runs and exits 0, but no longer reproduces the consumer goldens.

```
$ python rederive_bundle.py --break query
...
    clean-json-toolkit:query         REJECT       plugin_failed
...
K of N: 1 of 7 tools re-derive -> ['clean-json-toolkit:flatten']
OpenClaw install-policy decision: {'protocolVersion': 1, 'decision': 'block',
  'reason': "bundled tool 'clean-json-toolkit:query' did not re-derive (plugin_failed):
   ... [SKILL_REDER_FAIL] cell0: mismatch (got \"'1.2'\\n\")"}
```

The sabotage is caught at the cell that asserts `.meta.version --raw` prints `1.2`
(not `'1.2'`). `flatten` is untouched, so it still ADMITs — the gate localizes the
failure to the broken tool, not the whole bundle.

## Strategic reading

1. **The tool-bundle class is now covered honestly.** Before this slice, a real
   ClawHub bundle (>1 entrypoint) was `AMBIGUOUS_ENTRYPOINT` → unjudgeable. Now it
   re-derives one bundle per tool and reports **K of N**. The funnel's earlier
   false-reject of this class is closed.

2. **"K of N", never "verified".** 2 of 7 tools re-derive because the consumer wrote
   goldens for 2. The other 5 are **unjudgeable** (fail-closed `no_goldens_for_kind`),
   not silently passed. This is the same honesty rail as the funnel: the gate sizes
   the slice it can *truthfully* gate and refuses the rest.

3. **Grader provisioning is still the binding constraint — but tractable per tool.**
   Each tool is a small, clean CLI with a definable I/O contract, so a consumer grader
   is 2–3 hand-written cells per tool (see `json_toolkit_grader.py`). The work scales
   with *tools the consumer depends on*, not total marketplace volume.

4. **The unjudgeable-vs-contradicted split is load-bearing.** veriker maps every
   non-zero pack exit to `RE_DERIVATION_MISMATCH`, so "I have no goldens for this tool"
   and "this tool is broken" both surface as REJECTED. The gate distinguishes them via
   the grader's `no_goldens_for_kind` marker in the verdict detail — without it, a
   bundle would be blocked merely for shipping tools the consumer doesn't grade. That
   would be a false block, the mirror-image of a fabricated pass.

5. **Scope unchanged.** Functional conformance only; the consumer's grader is the
   trust root; no LLM-judge. `flatten`'s goldens are concrete held-out I/O pairs
   (including an unflatten roundtrip) — *not* the prose-stated "roundtrip-safe"
   property the `prose_property_prove` demo found `prove` correctly refuses to certify
   without goldens. Goldens are exactly what closes that gap.
