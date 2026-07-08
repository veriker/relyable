"""relyable.adapters — thin per-harness integration shims for the relyable bindings.

An adapter adds **no trust logic**. It calls an existing relyable binding
(``relyable.skills`` / ``relyable.memory``) at the right point in a specific
harness's lifecycle, and drops/refuses anything the binding does not ADMIT. The
trust root — the grader (and, for memory's sealed mode, the reference) — is the
consumer's, supplied as host config; an adapter never ships or hardcodes one.

Subpackages (first integration targets, by verified demand):

  * ``relyable.adapters.hermes`` — wires ``relyable.skills`` into the Hermes
    skill-write admission chokepoint. Hermes is Python, so the gate is an
    in-process call; see ``hermes/DISCOVERY.md`` for the exact seam.
  * ``relyable.adapters.openclaw`` — wires ``relyable.memory`` into OpenClaw's
    ``before_prompt_build`` recall hook. OpenClaw is TypeScript, so the gate runs
    behind a subprocess boundary (a Node plugin spawns the Python CLI); see
    ``openclaw/DISCOVERY.md``.

The surface->harness pairing (skills=Hermes, memory=OpenClaw) is where the
sharpest verified demand sits, not a benefit boundary: either binding applies to
either harness. These two are simply the first adapters built.
"""
