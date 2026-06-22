# relyable demos

Runnable demonstrations of relyable's skill-vetting surface against real agent skill
directories (OpenClaw / ClawHub).

| demo | what it shows | evidence |
|---|---|---|
| [`directory_funnel/`](directory_funnel/) | honest sizing of how much of a real skills directory the gate can adjudicate (most skills are prose → out of scope by design) | `FUNNEL_RUN.md` over real ClawHub samples (18-skill v1, M=1; 58-skill v2) |
| [`prose_property_prove/`](prose_property_prove/) | the prose-skill compromise: prove a prose-stated property (roundtrip-safe) of a real ClawHub tool, no goldens — and watch it correctly REFUSE when the property is too weak | `PROVE_RUN.md` over clean-json-toolkit `flatten.py` (VACUOUS) |
| [`tool_bundle_rederive/`](tool_bundle_rederive/) | the tool-BUNDLE class: one SKILL.md routing to N bundled tools, re-derived one verdict each — honest "K of N tools re-derive", with the install gate now adjudicating the class the funnel false-rejected | `TOOL_BUNDLE_RUN.md` (in-process, 2 of 7) + `LIVE_RUN.md` (real `openclaw skills install`, 2026.6.8) |
| [`self_spec/`](self_spec/) | the orthogonal author-grounded axis: grade each skill against ITS OWN committed spec (shipped suite / documented examples / fixtures), no consumer goldens — REPRODUCES / CONTRADICTS / UNJUDGEABLE | `SELF_SPEC_RUN.md`: mechanism fires (R=1/C=1 on fixtures), A=0 over 18 installed skills. `sample_clawhub.py` + `CLAWHUB_SAMPLE_RUN.md`: at scale ~1% of a random ~1,000-skill sample ship any checkable spec (9/966, 95% CI 0.49–1.76%) — behavior is pinned almost nowhere |
| [`cold_golden/`](cold_golden/) | the spec-less long tail: a COLD agent reads only a skill's description (never the code), manufactures a golden or ABSTAINS, then the code is run and compared mechanically — coverage where the author shipped no spec, with fail-closed abstention + anti-vacuity mutation gate so it maps holes instead of papering them | `CONTROL_RUN.json`: teeth (PASS kill=100% honest / DIVERGED on sabotage). `COLD_GOLDEN_RUN.md`: three samples — 18 curated (1 load-bearing PASS), 40 random (0 PASS; mostly prose + live-API wrappers), and the addressable cut (Haiku-filter 194→21 local-deterministic: still 0 PASS, 18 abstain because docs aren't written to the byte). Plus `metamorphic.py` — engineers around that wall with format-proof `invariance`/`idempotence` checks (the T2 PROVABLE_KINDS, CLI-level): recovers the canonicalizer subclass (2 HOLDS on the slice exact-match could only abstain on). **0 false greens, 0 false accusations** across all of it |

All demos hold the same honesty rails: the gate is a **functional-conformance** gate
(not security, not prose-quality), it requires the **consumer's** grader, and it
**refuses** (rather than fabricates a verdict) on anything it cannot re-derive.

Grounding: the trust-label premise — agents follow a "verified" label *blindly*
(position-anchoring, not vetting), so a forged label is the attack surface, and a
re-derivable label is harm-neutralization not uplift — is from the ALE experiment
line summarized in [`../relyable/skills/README.md`](../relyable/skills/README.md).
