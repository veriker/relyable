"""relyable.gate — the shared re-derivation admission gate.

A host-side, out-of-band gate that admits only what re-derives: it assembles a
real veriker bundle around a candidate, pins the grader to the consumer's own
trusted copy, and runs veriker's BundleVerifier over the gated
re_derivation_invocation lane. The agent cannot self-attest past it.

relyable's skills and memory bindings consume this; the verdict surface
(`relyable.verdicts`) uses its own runner.
"""

from .admission import (
    GRADER_MISMATCH,
    MISSING_PRINCIPAL,
    NO_GRADER,
    SAME_PRINCIPAL,
    AttestedVerifyResult,
    build_attested_bundle,
    file_digest,
    flatten_reasons,
    verify_attested_bundle,
)

__all__ = [
    "AttestedVerifyResult",
    "GRADER_MISMATCH",
    "MISSING_PRINCIPAL",
    "NO_GRADER",
    "SAME_PRINCIPAL",
    "build_attested_bundle",
    "file_digest",
    "flatten_reasons",
    "verify_attested_bundle",
]
