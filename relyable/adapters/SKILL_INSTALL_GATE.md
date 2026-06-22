# Native-skill install gate

Re-derive a third-party agent skill against **your own** held-out goldens before it
is admitted — for skills that ship a runnable entrypoint (ClawHub `SKILL.md` +
scripts, Hermes skill dirs, local/Git skills). This is the producer-agnostic seam
that turns a native skill into a veriker bundle the existing `relyable.skills` gate
admits unchanged, plus an OpenClaw `security.installPolicy` command that uses it.

## What this is — and is not

A native `SKILL.md` carries **no machine-checkable pass-label** (its frontmatter has
no test/grader/verdict field). So this is **not** "re-derive the producer's claim."
It is a **consumer-spec conformance gate**: *you* supply a grader (held-out goldens +
the I/O check), and a skill is admitted iff its own entrypoint reproduces them.

- **Functional axis, not security.** It catches "this skill does not do what your
  spec needs." It does **not** detect malware, prompt-injection, or credential
  theft — run it **alongside** ClawScan / VirusTotal / static analysis, not instead.
- **In scope:** skills with a runnable entrypoint and a definable I/O contract
  (convert / scrape / SQL / codegen), **including tool BUNDLES** — one `SKILL.md`
  routing to N bundled `scripts/*` (each a CLI). A bundle is re-derived **one verdict
  per tool** (`pack_native_tool_bundles` → `enumerate_tools`); the honest report is
  "K of N tools re-derive" — only the tools the consumer grades count, the rest are
  unjudgeable (never a fabricated pass). **Out of scope:** prose / instruction-only
  skills — there is no deterministic oracle, so packing raises `OutOfScope` rather
  than fabricate a verdict.
- **The grader is your trust root.** No default — the goldens are domain-specific
  and must be yours. The skill body never contributes its own pass criteria.

## Pieces

| Module | Role |
|---|---|
| `relyable.adapters._skillpack.pack_native_skill` | parse `SKILL.md` → scope-gate → build a re-derivable veriker bundle (artifact-tree mode); single entrypoint |
| `relyable.adapters._skillpack.enumerate_tools` / `pack_native_tool_bundles` | the tool-BUNDLE generalization: enumerate N bundled tools → one re-derivable bundle per tool (each carrying the whole skill tree, so a shared `_common.py` travels) |
| `relyable.adapters._skillpack.Invocation` | how the grader runs the entrypoint (`entrypoint`, `runner`, `input_mode`, `output_mode`) |
| `relyable.skills.examples.exec_skill_grader` | worked grader for the stdin→stdout class: **runs** the entrypoint vs. embedded goldens (companion to `interval_grader`) |
| `relyable.skills.examples.json_toolkit_grader` | worked grader for the file-arg tool-bundle class (input file + query/output path + flags), keyed by per-tool kind |
| `relyable.adapters.installpolicy` (`relyable-installpolicy`) | OpenClaw `security.installPolicy` command (stdin/stdout JSON); adjudicates a tool bundle per tool and aggregates allow/block |

The bundle uses the builder's **artifact-tree mode** (`build_attested_bundle(...,
artifact_dir=)`): the whole skill tree is copied verbatim under `skill/` and every
file digest-bound, so multi-file / non-Python skills are carried natively. No veriker
change — the candidate-loading contract lives in the grader pack.

## Writing a grader

Copy `relyable/skills/examples/exec_skill_grader.py` and replace `GOLDENS` with your
own held-out cells, keyed by *kind*. Each cell is `(input_text, expected_output_text)`;
the grader runs the entrypoint (allowlisted runner: `python` / `sh` / `node`) on each
input and requires an exact match. **No veriker import, stdlib only** — it is run in a
subprocess as the consumer's pinned authority. The `invocation` in `meta.json` only
tells the grader which file to run; a lying entrypoint cannot pass (it must reproduce
the goldens) and one not inside the bundle fails closed.

## OpenClaw `security.installPolicy` wiring

OpenClaw runs a trusted local command after staging a skill and before install
continues; a non-zero exit / timeout / malformed JSON / block decision stops the
install. Point it at `relyable-installpolicy`:

```json5
// ~/.openclaw/openclaw.json — security.installPolicy
// Shape verified against the openclaw 2026.6.8 config schema (`openclaw config schema`).
{
  security: {
    installPolicy: {
      enabled: true,            // REQUIRED — arms the gate
      targets: ["skill"],       // install targets the policy guards
      exec: {
        source: "exec",         // REQUIRED discriminator
        command: "/path/to/venv/bin/relyable-installpolicy",
        timeoutMs: 30000,
        passEnv: [
          "RELYABLE_INSTALLPOLICY_GRADER",
          "RELYABLE_INSTALLPOLICY_KIND_MAP",
          "RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE",
          "RELYABLE_INSTALLPOLICY_PERMIT_EXECUTION"
        ],
        env: {
          RELYABLE_INSTALLPOLICY_GRADER: "/path/to/my_grader.py",
          RELYABLE_INSTALLPOLICY_KIND_MAP: "{\"csv-to-json\": \"csvjson\"}"
        }
      }
    }
  }
}
```

Apply it non-interactively with `openclaw config patch --file policy.json5`
(`--dry-run` first to validate against the schema).

### Protocol (protocolVersion 1)

- **stdin** — one JSON object: `{protocolVersion, openclawVersion, targetType,
  targetName, sourcePath, sourcePathKind, source, origin, request, skill}`.
- **stdout** — `{"protocolVersion": 1, "decision": "allow"}` or
  `{"protocolVersion": 1, "decision": "block", "reason": "..."}`.
- The skill maps to a grader *kind* via `origin.slug` → `RELYABLE_INSTALLPOLICY_KIND_MAP`
  (default: the slug itself). A kind with no goldens is **unjudgeable**.

### Env knobs

| Var | Default | Meaning |
|---|---|---|
| `RELYABLE_INSTALLPOLICY_GRADER` | *(required)* | path to your trusted grader; missing → **block** (fail-closed) |
| `RELYABLE_INSTALLPOLICY_KIND_MAP` | `{}` | JSON `{slug: kind}`; maps a skill slug to a grader kind |
| `RELYABLE_INSTALLPOLICY_PERMIT_EXECUTION` | on | `"0"` disables running the skill (every skill becomes unjudgeable). On = vets **by running** the entrypoint — configure `exec` on a sandboxed/trusted host |
| `RELYABLE_INSTALLPOLICY_ON_UNJUDGEABLE` | `block` | decision for targets it can't adjudicate (plugins, prose-only, unknown kind). `allow` = functional-only gate that blocks only what it proves non-conformant |

### Decision logic

- skill re-derives against your grader → **allow**
- skill actively contradicts the goldens → **block** (`reason` carries the code + detail)
- can't adjudicate (plugin, prose-only/`OutOfScope`, no goldens, execution off) →
  per `ON_UNJUDGEABLE`
- malformed request / wrong protocol / unreadable `sourcePath` / missing grader →
  **block** (fail-closed)

## Status

**Exercised live against openclaw `2026.6.8`** (2026-06-18): a real `openclaw skills
install` of a poisoned skill is **blocked by the gate**, and the honest skill installs
— see `demos/openclaw_poisoned_label/live_openclaw/` (`run_live.sh` + `LIVE_RUN.md`).
The **tool-bundle** class is verified live too: the real `clean-json-toolkit` (7 tools)
installs (its `query`+`flatten` re-derive against consumer goldens; the 5 ungraded
tools are unjudgeable, not blocks), and a copy with a broken `query` is blocked —
see `demos/tool_bundle_rederive/` (`run_live.sh` + `LIVE_RUN.md`).
The protocol shape is source-verified (the `security.installPolicy` schema from the
installed package + `docs.openclaw.ai/tools/skills-config`). The `exec` knobs
`maxOutputBytes` / `trustedDirs` / `noOutputTimeoutMs` are accepted by the schema but
not individually load-tested. Tests: `tests/test_skillpack.py`,
`tests/test_installpolicy.py`. The remaining real work is **grader provisioning** for
arbitrary skills — that stays the consumer's job by design.
