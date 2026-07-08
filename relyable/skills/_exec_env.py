"""_exec_env.py — the scrubbed environment for executing untrusted skill code.

Every lane that EXECUTES a skill's own code (self_spec suites and goldens, cold
goldens, exogenous property checks) must not hand the skill the operator's
environment: a skill that dumps ``os.environ`` to stdout would exfiltrate LLM
API keys and other secrets STRAIGHT INTO THE EVIDENCE ARTIFACT (the scan payload
preserves stdout-derived bytes). The Trail of Bits ``csv-summarizer`` demo skill
is exactly this shape — its ``__main__`` prints every env var.

So: allowlist, never inherit. Locale/encoding vars keep interpreters honest;
PATH keeps runners resolvable; HOME/TMPDIR keep well-behaved tools working.
Everything else — keys, tokens, cloud creds, session vars — is withheld.

Stdlib only.
"""

from __future__ import annotations

import os

# The variables untrusted skill code may see. Deliberately boring.
_ALLOWED = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TMP",
    "TEMP",
    "PYTHONIOENCODING",
    "SYSTEMROOT",  # Windows: subprocess needs it to start at all
    "COMSPEC",
)


def scrubbed_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """An execution environment for untrusted skill code: allowlisted inherited
    vars only, plus ``PYTHONDONTWRITEBYTECODE`` (no cache turds in temp dirs).

    ``extra`` lets a caller add deliberate, named variables (never a passthrough
    of ``os.environ``)."""
    env = {k: v for k in _ALLOWED if (v := os.environ.get(k)) is not None}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env
