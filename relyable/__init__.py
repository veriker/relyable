"""relyable — an agent-trust suite on the veriker substrate.

Surfaces:
  * ``relyable.verdicts`` — re-derive an agent's test verdict; ratchet against
    test-gaming (the verdict surface).
  * ``relyable.gate`` — the shared re-derivation admission gate (skills/memory
    bindings consume it).

Each surface admits only what re-derives; the agent cannot self-attest past it.
"""
