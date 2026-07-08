#!/usr/bin/env python3
"""json_toolkit_grader.py — a worked re-derivation GRADER for a TOOL BUNDLE.

Companion to ``exec_skill_grader.py``. That grader handles the simple
stdin->stdout tool class; this one handles a real ClawHub *tool bundle* — a single
SKILL.md routing to several bundled ``scripts/*.py``, EACH a small CLI that takes
FILE arguments (an input path + a query/output path + flags), not stdin. The
clean-json-toolkit skill (query / flatten / inspect / validate / merge / patch) is
the worked target.

Each tool of the bundle is packed into its OWN veriker bundle
(``relyable.adapters._skillpack.pack_native_tool_bundles``); this grader is pinned
into every one of them. It reads ``skill/meta.json`` -> {kind, invocation}, looks up
the held-out goldens for that tool's ``kind``, and re-derives by RUNNING the tool's
own entrypoint on each golden's inputs and comparing its output.

WHY THIS IS NOT "the producer grading its own homework": the consumer pins THIS
exact file (their trusted copy) into every bundle's re_derive/; the producer's
bundle supplies only the skill body + an ``invocation`` HINT (which file to run).
The GOLDENS below are consumer-distribution, pinned here, never bundle-supplied. A
lying entrypoint cannot pass — it must actually reproduce the goldens. A tool whose
``kind`` has no goldens fails closed (``no_goldens_for_kind``), never fabricates a
pass — so admitting "K of N tools" is honest. Per the auditor-independence
contract: NO veriker import, stdlib only.

Golden cell shape (per kind): a dict
    {"inputs": {rel_name: text, ...},   # files written into a fresh temp cwd
     "argv":   [arg, ...],              # passed AFTER the entrypoint; rel paths
                                        # resolve against that temp cwd
     "read":   "stdout" | rel_name,     # where the tool's result lands
     "expected": text}                  # exact (trailing-newline-normalized) match
The entrypoint is invoked with an ABSOLUTE path so ``import _common`` (which Python
resolves from the script's own dir) keeps working regardless of the temp cwd.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# --- consumer-distribution authority (pinned HERE, never bundle-supplied) ------
# Keyed by the per-tool kind that pack_native_tool_bundles assigns,
# "<skill-slug>:<tool-stem>" — e.g. clean-json-toolkit:query. A real consumer
# replaces these with their own held-out goldens for the tools they depend on.
GOLDENS: dict[str, list[dict]] = {
    "clean-json-toolkit:query": [
        {
            "inputs": {"in.json": '{"meta": {"version": "1.2"}}'},
            "argv": ["in.json", ".meta.version", "--raw", "--quiet"],
            "read": "stdout",
            "expected": "1.2",
        },
        {
            "inputs": {
                "in.json": '{"users": [{"email": "a@x.com"}, {"email": "b@y.com"}]}'
            },
            "argv": ["in.json", ".users.[].email", "--raw", "--quiet"],
            "read": "stdout",
            "expected": "a@x.com\nb@y.com",
        },
        {
            "inputs": {"in.json": '{"items": [{"price": 5}, {"price": 9}]}'},
            "argv": ["in.json", ".items.[].price", "--lines", "--quiet"],
            "read": "stdout",
            "expected": "5\n9",
        },
    ],
    "clean-json-toolkit:flatten": [
        {
            "inputs": {"in.json": '{"a": {"b": 1}, "items": [{"id": 7}, {"id": 9}]}'},
            "argv": ["in.json", "out.json", "--quiet"],
            "read": "out.json",
            "expected": '{\n  "a.b": 1,\n  "items.0.id": 7,\n  "items.1.id": 9\n}',
        },
        {
            # Unflatten is the inverse: dot-notation map -> nested structure.
            "inputs": {"flat.json": '{"a.b": 1, "items.0.id": 7, "items.1.id": 9}'},
            "argv": ["flat.json", "nested.json", "--unflatten", "--quiet"],
            "read": "nested.json",
            "expected": (
                '{\n  "a": {\n    "b": 1\n  },\n  "items": [\n    {\n'
                '      "id": 7\n    },\n    {\n      "id": 9\n    }\n  ]\n}'
            ),
        },
    ],
}

# Runners the grader will shell out to (must match _skillpack.RUNNERS).
_RUNNER_CMD = {"python": [sys.executable], "sh": ["sh"], "node": ["node"]}


def _fail(msg: str) -> int:
    print(f"[SKILL_REDER_FAIL] {msg}", file=sys.stderr)
    return 1


def _norm(s: str) -> str:
    """Normalize trailing newlines so a tool that prints/writes a trailing newline
    is not penalized; internal content must still match exactly."""
    return s.replace("\r\n", "\n").rstrip("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle-dir", required=True)
    args = ap.parse_args()
    bundle = Path(args.bundle_dir)

    try:
        meta = json.loads((bundle / "skill" / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"meta_unreadable: {e}")

    kind = meta.get("kind")
    cells = GOLDENS.get(kind)
    if not cells:  # fail-closed: a tool with no goldens never all([]) -> pass
        return _fail(f"no_goldens_for_kind: {kind!r}")

    inv = meta.get("invocation") or {}
    entrypoint = inv.get("entrypoint")
    runner = inv.get("runner")
    if not entrypoint or runner not in _RUNNER_CMD:
        return _fail(f"bad_invocation: entrypoint={entrypoint!r} runner={runner!r}")
    ep_path = (bundle / "skill" / entrypoint).resolve()
    # Containment: the entrypoint must live inside the bundle's skill/ tree.
    if (bundle / "skill").resolve() not in ep_path.parents or not ep_path.is_file():
        return _fail(f"entrypoint_not_in_bundle: {entrypoint!r}")

    cmd = _RUNNER_CMD[runner] + [str(ep_path)]

    for i, cell in enumerate(cells):
        with tempfile.TemporaryDirectory(prefix="json-toolkit-grader-") as td:
            cwd = Path(td)
            for rel, text in cell["inputs"].items():
                (cwd / rel).write_text(text, encoding="utf-8")
            try:
                res = subprocess.run(
                    cmd + list(cell["argv"]),
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                return _fail(f"cell{i}: timeout")
            except OSError as e:  # e.g. runner binary missing
                return _fail(f"cell{i}: runner_unavailable: {e}")
            if res.returncode != 0:
                return _fail(
                    f"cell{i}: entrypoint_exit_{res.returncode}: {res.stderr[:200]}"
                )
            read = cell["read"]
            if read == "stdout":
                got = res.stdout
            else:
                out_file = cwd / read
                if not out_file.is_file():
                    return _fail(f"cell{i}: tool wrote no output file {read!r}")
                got = out_file.read_text(encoding="utf-8")
            if _norm(got) != _norm(cell["expected"]):
                return _fail(f"cell{i}: mismatch (got {got[:120]!r})")
    return 0  # every held-out cell reproduced -> RE_DERIVED


if __name__ == "__main__":
    sys.exit(main())
