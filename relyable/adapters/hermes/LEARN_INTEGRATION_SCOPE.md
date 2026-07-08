# `/learn` integration scope — re-derivation gate on Hermes skill *distillation*

Status: **scoped, not built** (2026-06-23). Companion to `DISCOVERY.md` (the
skill-admission seam) and `guard.py` (the gate that sits on it).

## What changed upstream

Hermes shipped `/learn` on 2026-06-23 — commit `e32ebc6aa`, PR **#51506**,
`feat(skills): /learn — distill a reusable skill from anything you describe`.

Mechanism (verified from `agent/learn_prompt.py` @ `e32ebc6aa`):

- `/learn` is a **prompt builder**, not a distillation engine.
  `build_learn_prompt(user_request)` wraps the request in a standards-guided
  instruction and hands it to the live agent as a normal turn. The agent gathers
  sources with its existing tools (`read_file`, `search_files`, `web_extract`,
  conversation history) and authors **one `SKILL.md`** via the `skill_manage`
  tool (`action="create"`).
- The embedded authoring standard mandates an 8-section body. Section 8 is
  literally: **`## Verification` — "a single command/check that proves the skill
  worked."**
- Every surface (CLI, gateway, TUI, dashboard "Learn a skill" panel) funnels
  through `build_learn_prompt` → `skill_manage` create. The save is gated only by
  Hermes's optional human `write_approval` gate.

## Why this is an integration point, not just a thesis example

**1. Same chokepoint, more volume.** `skill_manage` `action="create"` runs
Hermes's `_create_skill`, which calls `_security_scan_skill(skill_dir)` — the
exact seam `guard.py::rederive_skill_guard` is shaped for (contract: `None` ⇒
admit, error-string ⇒ Hermes `shutil.rmtree`s the skill). `/learn` opens **no new
surface**; it is a new firehose of agent-authored skills into the seam relyable
already gates. No new splice to write.

**2. It converts our biggest "out of scope" case into an in-scope one.** `guard.py`
explicitly excludes *"a prose-only skill with no checkable claim — nothing to
re-derive, out of scope."* A hand-written `SKILL.md` is usually exactly that.
`/learn`'s mandated `## Verification` section is an agent-emitted, **structured
checkable-claim slot on every skill it produces** — the missing producer-side hook
that lets a raw `SKILL.md` be packaged into a veriker bundle and re-derived. It
widens the surface of skills-that-carry-a-claim from ~nothing to ~all `/learn`
output.

**3. It composes with an existing approval gate.** `/learn` is user-initiated and
the save passes through Hermes's `write_approval` gate. Inserting an automated
re-derivation verdict *before* that approve is expected UX, not an intrusion into a
passive background loop.

## The trap (this IS the relyable value-prop — do not lose it)

The `## Verification` command is **self-authored**: same model, same sources that
wrote the skill. It is a textbook `self_spec`, and relyable's own finding
(`relyable/skills/self_spec.py`) is that self-authored specs catch the author's
blind spots at **A≈0**. **Running the agent's own `## Verification` line and
admitting on green reproduces the author=executor=inspector gap that Hermes #25833
names and relyable exists to close** — i.e. it would be theater.

Therefore the `## Verification` text is consumed as an **untrusted claim/hint**,
never as the arbiter. The decision stays what `gate.py` already enforces:
re-derive against the **consumer's** pinned grader (`grader_src`, no default),
env-clean from authentic bytes. This is consistent with how
`build_native_skill_bundle` already treats a producer-supplied `invocation` hint —
"untrusted; a lying entrypoint simply fails to re-derive (fail-closed)."

The author≠inspector property is enforced by machinery that already exists:
`rederive(..., require_separation=True)` with `artifact_principal` =
HOST-attested Hermes session model (the L1 source that overrides the forgeable L0
`author_principal` in `skill/meta.json`). A skill whose producing principal equals
the grader's author is REJECTED before the grader runs.

## The shim (mostly packaging over existing machinery)

A `/learn`-aware path in this adapter. New code is small; the gate, bundle builder,
and config are unchanged.

1. **Hook point** (unchanged): the one-line call already specified in `DISCOVERY.md`
   — add `rederive_skill_guard(skill_dir, config)` to Hermes's `_security_scan_skill`
   so it runs on `_create_skill`. `/learn` saves route through this for free.

2. **Package the freshly-created `SKILL.md` tree into a veriker bundle.** The
   `/learn` artifact is a native multi-file skill (SKILL.md + optional `scripts/`),
   so use the existing native builder, not the single-`candidate.py` one:

   ```python
   from relyable.skills import build_native_skill_bundle
   bundle = build_native_skill_bundle(
       dest=tmp_bundle_dir,
       skill_id=skill_name,
       kind="hermes-learn",
       artifact_dir=skill_dir,            # the SKILL.md tree Hermes just wrote
       grader_src=config.grader_src,      # consumer's trusted grader (never producer)
       invocation=verification_hint,      # parsed from `## Verification` — UNTRUSTED hint
       author_principal=config.session_principal,  # producer = Hermes session model
   )
   ```

3. **Lift `## Verification` as a hint, not a check.** Parse section 8 out of the
   created `SKILL.md` and pass it as the `invocation` hint (e.g.
   `{"runner": "terminal", "check": "<the verification command>"}`). The
   consumer's grader may *consult* it but the verdict is the grader's
   re-derivation against held-out goldens — the hint travels in the bundle and is
   treated as producer-influenced / untrusted.

4. **Re-derive through the existing gate** with separation on:
   `rederive_skill_guard(bundle, config_with(require_separation=True))`. `None` ⇒
   Hermes admits; reason-string ⇒ Hermes rolls back the skill. No new verdict
   logic.

5. **Config** is the existing `HermesGuardConfig.from_env`:
   `RELYABLE_HERMES_GRADER` (required), `RELYABLE_HERMES_PERMIT_EXECUTION`,
   `RELYABLE_HERMES_SESSION_PRINCIPAL` (the L1 author stamp),
   `RELYABLE_HERMES_REQUIRE_SEPARATION=1`, optional sandbox vars.

## What `/learn` does NOT solve (state honestly)

- **Grader-provisioning is still the binding constraint.** `gate.py` has no default
  grader — the held-out golden is the consumer's to write, per-domain. `/learn`
  makes a learned skill *bundleable with a claim*; it does **not** supply a trust
  root. A learned skill with no consumer golden for its domain is
  could-not-conclude under `permit_execution=False` (unadmitted / absent from
  `usable`) — fail-closed, by design. This is the same ceiling as the ClawHub
  funnel (M=1/18 — the re-derivation surface is small because graders are scarce,
  not because claims are).
- **Many `/learn` skills are procedures, not executable code.** For a pure-prose
  procedure with no machine-checkable behavior, there may be nothing for a grader
  to re-derive even with a consumer golden. `/learn` raises the *count* of skills
  carrying a structured claim; gradeability of any given one still depends on a
  domain golden existing.

Net: `/learn` removes the *"no checkable claim"* blocker (affordance #2 above),
leaving grader-provisioning as the one remaining gap — a cleaner place to stand
than before, and a non-accusatory framing (the agent's own distill-and-save loop,
the exact author=executor=inspector instance #25833 asks the project to close).

## Provenance

- Upstream: `NousResearch/hermes-agent` @ `e32ebc6aa` (PR #51506), `agent/learn_prompt.py`,
  `website/docs/user-guide/features/skills.md`, `tests/agent/test_learn_prompt.py`
  (all prompt-construction tests; **zero** execution/verification tests — confirms
  `## Verification` is never run upstream).
- relyable seam + contract: `DISCOVERY.md`, `guard.py`, `gate.py::rederive`,
  `bundle.py::build_native_skill_bundle`, `config.py::HermesGuardConfig`,
  `skills/self_spec.py` (the A≈0 self-spec finding).
