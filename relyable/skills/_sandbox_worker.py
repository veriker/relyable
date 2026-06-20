"""_sandbox_worker.py — run one skill re-derivation INSIDE a sandbox.

veriker runs the grader pack with a hardcoded ``subprocess.run([sys.executable,
pack, …])`` — a child process on the SAME host with full permissions, no security
isolation (veriker says so itself). relyable therefore cannot inject a sandbox into
that inner call; the only honest boundary is to run the WHOLE re-derivation inside a
sandbox. This module is that in-sandbox entrypoint: ``relyable.skills.rederive``
calls it via a ``Sandbox`` (a subprocess, a ``docker run``, …), it re-derives the
skill in-process (sandbox=None, so no recursion), and emits the verdict as a single
sentinel-prefixed JSON line on stdout. The parent parses that line back into an
``AdmissionVerdict`` and stamps the isolation level the sandbox actually provided.

Invoked as ``python -m relyable.skills._sandbox_worker --bundle-dir … --grader-src …``.
Inside a ContainerSandbox the image must have relyable + veriker installed and the
bundle dir + grader reachable in the mount.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

# The sentinel lives in gate.py (the parser side); importing it here keeps gate from
# importing this worker, which would double-import under ``python -m``.
from relyable.skills.gate import VERDICT_SENTINEL


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    ap.add_argument("--grader-src", required=True)
    ap.add_argument("--pack-filename", default=None)
    ap.add_argument("--permit-execution", action="store_true")
    ap.add_argument("--grader-principal", default=None)
    ap.add_argument("--require-separation", action="store_true")
    ap.add_argument("--artifact-principal", default=None)
    args = ap.parse_args(argv)

    # Imported here (not at module top) so importing this module is cheap and so the
    # import cost is paid inside the sandbox, where it belongs.
    from relyable.skills import rederive  # noqa: PLC0415

    verdict = rederive(
        Path(args.bundle_dir),
        grader_src=Path(args.grader_src),
        permit_execution=args.permit_execution,
        pack_filename=args.pack_filename,
        grader_principal=args.grader_principal,
        require_separation=args.require_separation,
        artifact_principal=args.artifact_principal,
        sandbox=None,  # already inside the sandbox — never recurse
    )
    print(VERDICT_SENTINEL + json.dumps(dataclasses.asdict(verdict)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
