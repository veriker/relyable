# LIVE run — tool-bundle gate inside a real `openclaw skills install`

Captured 2026-06-18 from `run_live.sh` against **openclaw 2026.6.8** (`844f405`) +
**veriker 0.1.2**, with `relyable-installpolicy` wired as `security.installPolicy`
and the consumer's `json_toolkit_grader.py` as the trust root. This is the real
install flow — `openclaw skills install` staging the skill and running the policy
command before the install continues — not the in-process `installpolicy.run` of
`rederive_bundle.py`.

```
== 0. prerequisites ==
OpenClaw 2026.6.8 (844f405)
== 1. wire relyable-installpolicy (json_toolkit_grader) as security.installPolicy ==
Applied 9 config update(s). Restart the gateway to apply.
== 2. live: install the HONEST clean-json-toolkit from ClawHub (expect ALLOW) ==
Downloading clean-json-toolkit@0.2.0 from ClawHub…
Installing to /home/max/.openclaw/skills/clean-json-toolkit…
Installed clean-json-toolkit@0.2.0 -> /home/max/.openclaw/skills/clean-json-toolkit
  -> honest bundle INSTALLED (query+flatten re-derived; 5 ungraded tools did not block)
== 3. stage a BROKEN copy (sabotage query.py's --raw) ==
  -> query.py --raw now leaves quotes on string scalars (contradicts goldens)
== 4. live: install the BROKEN copy (expect BLOCK) ==
Install policy target=skill:clean-json-toolkit request=skill-install/update origin=path
  pathKind=directory source=local-path/user: blocked by install policy: bundled tool
  'clean-json-toolkit:query' did not re-derive (plugin_failed):
  [typed_check_plugins:re_derivation_invocation] plugin_failed: plugin
  're_derivation_invocation' reported failure: [SKILL_REDER_FAIL] cell0: mismatch (got "'1.2'\n")
  -> broken bundle BLOCKED and absent from disk (correct)
== 5. honest bundle still intact on disk (broken --force did not clobber it) ==
  -> on-disk query.py is the honest one (correct)

LIVE SELF-CHECK: PASS (honest tool-bundle installed, broken-tool bundle blocked by real OpenClaw)
```

## What this establishes

- **The bundle class installs through the real gate.** `clean-json-toolkit` ships 7
  tools (>1 entrypoint) — the exact shape the install gate previously declared
  `AMBIGUOUS_ENTRYPOINT` / unjudgeable. With the tool-bundle path it is adjudicated
  per tool and **allowed**, because the two tools the consumer grades (`query`,
  `flatten`) re-derive and the other five are unjudgeable (no goldens), not
  contradictions.
- **A broken tool is blocked by real OpenClaw**, with the block reason naming the
  specific tool and the specific failing cell (`clean-json-toolkit:query … cell0
  mismatch`). The blocked bundle never lands on disk.
- **`--force` on the blocked install did not clobber** the already-installed honest
  copy: the policy runs after staging and before the install continues, so the block
  pre-empts the on-disk replacement.

## Reproduce

```bash
bash demos/tool_bundle_rederive/run_live.sh
# Reuses $OPENCLAW_DIR (default /tmp/oclive) + $VENV (default /tmp/relyenv) if present,
# else builds fresh scratch. Backs up + restores ~/.openclaw/openclaw.json.
```

Honesty caveats: `PERMIT_EXECUTION=1` means the gate vets **by running** each tool on
the host — configure `exec` on a sandboxed/trusted host. This is a
functional-conformance gate, not a malware scanner — run it alongside
ClawScan/VirusTotal. The `KIND_MAP` maps both the ClawHub slug and the staged
`-broken` dir to the `clean-json-toolkit` kind prefix so per-tool kinds resolve to
the consumer's goldens (`clean-json-toolkit:query`, etc.).
