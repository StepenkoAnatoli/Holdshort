# Verifier-gated escalation companion (non-normative)

How verification gates escalation: what verifiers check, what their failures
mean, and which surveyed patterns are prohibited. Binding rules: the plan
(§7) and spec-v2.md §§11–12. Upstream behaviors summarized from pinned
revisions; nothing vendored or copied.

## 1. The gate: acceptance before work, verification before escalation

Acceptance is defined *before* work begins (exact diff/invariants, relevant
tests, fetched authoritative claims, or capable review proportionate to
consequence — plan §7). Escalation — same-profile repair or new-profile
ownership — is gated on the verifier's verdict over the current attempt:

- **Accepted** → adopt the artifact; record evidence; done.
- **Rejected with observed violation** → `failed` attempt retained; escalation
  only through the repair/escalation allowance (one same-profile correction
  per original task, plan §7/R01; new-profile escalation needs authorization
  and full qualification, R02).
- **Missing or indeterminate required evidence** → `unverified`; retry is not
  thereby authorized (plan §7, fixtures V01/S10). A worker's assertion that
  checks passed is not an observation.
- **Verifier exception (the verifier itself errored)** → `unverified`, never
  accepted. This is the bright line the survey draws against NadirClaw's
  `cascade.py` (@ `fa6ca99`), which returns the current tier's response with
  `accepted=True` on verifier error ("accept on verifier error") plus
  `meta.verifier_error`. Under Holdshort that path is fail-closed: the
  response is retained as evidence, the attempt is unverified, and dispatch
  continues only via an authorized repair/escalation or stops as
  `needs-human` / `blocked`.

## 2. Verifier design: contract-specific, proportionate, observable

- **Contract-specific checks.** HTTP 200 or nonempty output is insufficient;
  valid tool calls may be intermediate (S20a); structured/media outcomes need
  their own checks; refusals count only when the rubric expects them (S20b);
  an error payload against a success rubric is `failed` despite the 200
  (S20c). newapi-smart-router's outcome golden vectors
  (`parts/conformance/golden-vectors/outcome-v1.json` @ `034daab`) are the
  pattern to imitate: valid tool calls, pseudo-200 errors, committed streams
  and capacity-429 each classified before any recovery decision.
- **Proportionate strength.** kani's capability-routing tests (@ `d823cc4`)
  model the discipline: check exactly what the contract requires (forced
  choice, tools, vision, JSON, multiple capabilities) on a copy, without
  stripping required tools. Numeric self-scores and routing confidence are not
  acceptance (plan §7); transplanted calibration constants (NadirClaw's .80)
  do not qualify a verifier for this workload.
- **Narrow repair loops, not open reruns.** KeiRouter's Kiro integrity check
  (@ `3d8b702`, `kiro.go`: ellipsis-only answers, future-action announcements,
  malformed tool calls) permits exactly *one* repair-instruction retry,
  preferring another eligible candidate. That shape — one bounded correction,
  same-profile, evidence-retained — is the template for the R01 allowance. A
  verifier that can be retried until it passes is not a verifier.
- **Fallback results need identical acceptance** (plan §7). A cheaper tier's
  "good enough" is not an escalation policy; below-floor fallback and
  unverified fusion assumptions (xrouter-llm, survey §5) stay rejected.

## 3. Prohibited escalation patterns (survey §9, binding via §12)

- Verifier-error acceptance (NadirClaw `cascade.py`).
- Cheap-only kill-switch success after repeated failures — repeated verifier
  errors stop dispatch or escalate to human, never degrade to unverified
  success (see execution-mechanics.md §2).
- `force_cheap` paths that skip verification, and rule-engine failures that
  silently continue on the normal path. Rule actions that change tier or skip
  verification are exactly what the v2.1 proposal's `rule-activation`
  HumanGate would require approval for — see
  `docs/proposals/v2_1-delta.md` (proposal, not yet normative).
- Terminal-tier auto-accept: NadirClaw's N-tier cascade returns a terminal
  tier's answer unverified while a hop-cap stop returns `accepted=False`. Here
  there is no tier that waives verification: every adopted artifact carries
  its required evidence, and a hop-cap stop with an outstanding rejection is
  reported `failed`/`unverified` with its reason, never relabeled.

## 4. Verifier economics

Verifier dispatches are physical calls: they consume the task call budget and
sit inside the reserved work-plus-mandatory-check bound (plan §8, fixture
S08/V03). A verifier fee already included in a reservation is not added twice;
an uncertain verifier charge stays reserved and blocks economic promotion
until reconciled (S21b/V09).

Pinned sources: docs/ROUTER_SURVEY.md §§2, 4, 7, 13; plan §7 and fixtures
S10/S20a–c, V01–V04, R01–R04; deep-dive reports for NadirClaw (`fa6ca99`),
KeiRouter (`3d8b702`), router-core (`a5452c5`).
