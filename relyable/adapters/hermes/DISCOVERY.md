# Hermes skills adapter — extension-surface discovery

*Captured 2026-06-15 before writing adapter code. Every concrete claim is pinned to
a primary source verified this session (live `gh` / GitHub raw). No interface here
is invented; where a fact was not verifiable it is marked as such.*

## Verdict

**DETERMINABLE — a stable in-process Python integration point exists, but there is
NO dedicated skill-load plugin hook.** Integration is a source-edit/patch into the
skill-write guard, consistent with what issue #25833 asks the project to build.

## The harness is real (independently verified)

- `NousResearch/hermes-agent` exists. Verified this session with
  `gh repo view NousResearch/hermes-agent --json name,description,primaryLanguage,stargazerCount,isPrivate`
  → `{"name":"hermes-agent","description":"The agent that grows with you",`
  `"primaryLanguage":{"name":"Python"},"stargazerCount":194330,"isPrivate":false}`.
- It is a **Python** agent harness (not just the Hermes model family): "The
  self-improving AI agent … creates skills from experience."
- Issue **#25833** exists and matches verbatim. `gh issue view 25833 --repo
  NousResearch/hermes-agent --json number,title,state` →
  `{"number":25833,"state":"OPEN","title":"Self-created skills lack mechanism-level
  guarantees for correctness and execution consistency"}`. Body contains "the agent
  is simultaneously the author, executor, and quality inspector of its own skills"
  and asks for a re-execution / `verified` check that "Block[s] or warn[s] when
  verification fails."

Version anchor (per the discovery clone): repo `version = "0.16.0"`, Python 3.13,
latest release tag `v2026.6.5`; symbol line numbers below are at commit
`2a08b8c86fc9b94518b9b50d0f6cc0e5834e958b` (HEAD on 2026-06-15) and should be
re-confirmed against the integrator's pinned Hermes version before patching.

## The seam: `tools/skill_manager_tool.py::_security_scan_skill`

- `_security_scan_skill(skill_dir) -> Optional[str]` (`tools/skill_manager_tool.py`,
  ~line 78). Returns `None` to admit, an **error string** to reject. It already
  wraps the project's own `scan_skill(...) -> should_allow_install(...) -> return
  error` pattern.
- Callers `_create_skill` (~line 485) and `_edit_skill` (~line 542) run it AFTER the
  atomic write and **roll the skill back on a non-empty return**:
  ```python
  scan_error = _security_scan_skill(skill_dir)
  if scan_error:
      shutil.rmtree(skill_dir, ignore_errors=True)   # DROP, not warn
      return {"success": False, "error": scan_error}
  ```
- Public dispatch `skill_manage(action, name, content, …)` (~line 894) routes all
  create/edit/patch/delete and first runs `_apply_skill_write_gate(...)`.

**`relyable.adapters.hermes.rederive_skill_guard(skill_dir, cfg)` matches this
contract exactly** (`None` => admit, string => drop) so it slots in as (or beside)
the `_security_scan_skill` call. The existing `_GUARD_AVAILABLE` try/except import
(~line 53) is the template for adding relyable as an optional dependency.

## There is NO skill-lifecycle plugin hook

- `hermes_cli/plugins.py::VALID_HOOKS` (~line 128) =
  `{pre_tool_call, post_tool_call, transform_terminal_output, transform_tool_result,
  transform_llm_output, pre/post_llm_call, pre/post_api_request, api_request_error,
  on_session_start/end/finalize/reset, subagent_start/stop, pre_gateway_dispatch,
  pre_approval_request, post_approval_response}` — **no skill hook.**
- `PluginContext.register_hook(name, cb)` stores unknown hooks but only **warns**;
  the core never invokes a `skill_load` hook. So a pure-plugin wiring is not
  available — the integration must add the call to `skill_manager_tool.py`.
- Read-time path `tools/skills_tool.py::skill_view` / `_serve_plugin_skill` has an
  injection scan that today **logs-and-still-serves** (warn-not-drop) — the exact
  weakness #25833 names; a relyable check there would convert it to a hard drop, but
  note local agent-created skills (the #25833 population) do NOT pass through
  `_serve_plugin_skill`, so the **create-time guard is the load-bearing seam**.

## Language boundary

Hermes core is **Python 3.13**. `relyable` imports **directly in-process** — no
subprocess / CLI / MCP shim. (Contrast OpenClaw, which is TypeScript and needs the
subprocess boundary.)

## Bundle-shape caveat (honest scope)

`relyable.skills` re-derives a **veriker bundle** (`manifest.json` + `skill/` + the
pinned grader), the form `relyable.skills.build_skill_bundle` produces. A raw Hermes
`SKILL.md` must be packaged into a bundle first (a producer-side step). A prose-only
skill carrying no checkable claim has nothing to re-derive and is out of scope for
this gate — relyable covers the correctness/consistency axis (#25833), not arbitrary
prose. The integration test reconstructs the documented `_create_skill` rollback
flow faithfully and drives real bundles through it (it does not require a live
Hermes install or API key).

## Producing the grader (the consumer's trust root)

The grader (`RELYABLE_HERMES_GRADER`) is the one thing relyable never ships — it is
the consumer's held-out authority. Two ways to produce one without hand-writing
goldens per skill:

- **Code skill in a project that already has a test suite** → generate a grader from
  that suite (`relyable.skills.verdict_grader.write_verdict_grader(dest,
  project_root=…, target_path=…, test_cmd=[…])`). It drops the candidate into place
  and runs the suite; the agent that wrote the skill did not author the suite, so it
  is a non-circular trust root. The test command is baked in as a literal (consumer
  authority) — a producer-supplied bundle cannot redirect it. Run it in a disposable
  host: `permit_execution=True` runs the candidate, and `isolate=True` protects only
  the file tree, not the host.
- **Domain skill with a reference solver** → hand-write a grader on the
  `interval_grader` shape (held-out seeds + reference + exact/set compare).

## Separation of duties (opt-in)

Set `RELYABLE_HERMES_REQUIRE_SEPARATION=1` to enforce that the principal that
produced a skill differs from the principal that authored the grader — the gate-level
guard against an agent grading its own homework. Supply:

- `RELYABLE_HERMES_GRADER_PRINCIPAL` — who authored the grader.
- `RELYABLE_HERMES_SESSION_PRINCIPAL` — the **host-attested** producing principal
  (Hermes's current session model id). The adapter stamps this as the artifact
  principal; because the producer cannot write it, it is the stronger source (L1) and
  overrides the producer-supplied `skill/meta.json` author (L0, forgeable). Each
  verdict records which source was used (`principal_source` = `host` / `meta` /
  `none`). Without a session principal the gate falls back to the meta author; with
  neither principal it fails closed (`MISSING_PRINCIPAL`).

## Isolation (running untrusted candidate code)

`permit_execution=True` runs the candidate skill to vet it. veriker runs the grader
pack with a hardcoded in-process subprocess (same host, full permissions — it says so
itself), so relyable cannot isolate that inner call; the only honest boundary is to
run the whole re-derivation behind a sandbox. `RELYABLE_HERMES_SANDBOX` selects it:
`none` (default — the host/CI/managed agent is the boundary; correct when relyable
already runs inside an isolated job), `subprocess` (an extra process boundary, NOT a
security boundary), or `container` (`docker run`, network off — set
`RELYABLE_HERMES_SANDBOX_IMAGE` to an image carrying relyable + veriker). Each verdict
records the isolation actually used (`isolation_level`).

Hermes runs skills in-process on the host with no sandbox of its own (DISCOVERY: the
`hermes-agent` default backend is local). So on a bare host either run the whole
harness in a devcontainer (the pattern Anthropic/OpenAI converge on) or set
`RELYABLE_HERMES_SANDBOX=container` — relyable is then the component adding the
isolation Hermes lacks, around the same code Hermes would otherwise run unsandboxed.
Container path-mapping of arbitrary host bundle paths into the mount is a documented
follow-up; the `subprocess` path is the fully-wired one today.

## Not verified this session (flag before relying)

- Whether the autonomous skill-creator (`agent/background_review.py`) writes through
  `skill_manage`/`_create_skill` or writes `SKILL.md` directly — must be confirmed so
  the create-time guard actually covers self-created skills. Check the write path in
  `agent/background_review.py` / `agent/turn_finalizer.py`.
- Exact current line numbers (above are at HEAD `2a08b8c8`; re-pin per Hermes version).

## Primary sources

- Repo: https://github.com/NousResearch/hermes-agent
- Issue #25833: https://github.com/NousResearch/hermes-agent/issues/25833
- Siblings: /issues/416, /issues/13534, /issues/15204 (skill validation/linting,
  pre-creation validation, skill-review side effects)
- Skill create gate: https://github.com/NousResearch/hermes-agent/blob/main/tools/skill_manager_tool.py
- Skill load path: https://github.com/NousResearch/hermes-agent/blob/main/tools/skills_tool.py
- Plugin/hook API (no skill hook): https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/plugins.py
