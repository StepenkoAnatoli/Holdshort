# Compact brief and result workflow (canonical)

Complements the main SKILL.md; normative source is plan sections 5-8 at merge `d7c00f9`.

## When to route
Run the decision flow **before any implementation or model dispatch begins**:

1. Collect named inputs: current-task request; host policy revision; permitted actor/provider/
   destination/data; capability catalog; price list; available checks; remaining allowances and
   deadlines.
2. For every candidate profile (current model first, then alternates), apply Gate 1 → Gate 5 in
   order (see [references/gates.md](gates.md)).
3. Choose the unique surviving candidate with the best all overhead-inclusive economics.
   - Direct is preferred when it passes all gates and no eligible delegation beats it all-in.
   - Delegate only one isolated, bounded unit, and only with plausible net benefit.
   - Recommend an eligible capability escalation when direct is unsuitable.
   - **No eligible candidate → route is blocked.** Report the first failing gate and blocking reason.
4. Reassess on scope/risk change; revalidate the whole route, not just the changed field. A
   recommendation cache keyed only on content is invalid (plan S15a/S15b/S15c/S16).

## Brief (single compact document, given to any delegation target)
One brief per delegated unit. It pins:

- Objective and exact acceptance contract (what artifact, which checks which run which commands).
- Pinned source references; exact code structure and line refs; contradictions and unresolved
  requirements preserved verbatim (summaries are **not** authoritative evidence).
- Scope of permitted effects; privacy constraints; unchanged-file guarantees.
- Approved capabilities; explicit non-goals (no recursive delegation, no spend, no scope expansion,
  no governance bypass).
- Reserved allowance(s) and the finite attempt/deadline budget (all dispatches count; see below).
- Stop and escalation triggers, including verification-failure → repair rules.

### Machine-readable brief fields (v2.0)

Emit the normative Brief object (spec-v2.md §10.1) verbatim alongside the prose brief so a host
can create the isolated worker session directly, without reinterpretation:

```
Brief:
  objective:          <one-sentence outcome>
  acceptance:         <exact checks + commands that must pass>
  sources:            <pinned refs / paths / line ranges; contradictions preserved verbatim>
  permitted-effects:  <files / systems that may change>
  non-goals:          <explicit list: no recursive delegation unless nested-allowed, no spend
                       expansion, no governance bypass, …>
  isolation:          <none | directory | worktree+branch | ephemeral-container>
  branch-hint:        <suggested branch name or pattern, e.g. sr/<task-id>/<slug>>
  allowance:          <cash + call slots + deadline>
  attempts:           <max same-profile corrective dispatches>
  stop-triggers:      <verification failure → repair | escalate | block>
  ownership:          <this worker owns acceptance and receives all subsequent feedback>
  nested-allowed:     <false | true>   (default false — "no recursive delegation" holds)
  max-nesting-depth:  <1 | 2>
```

For a `speculative` route, emit the SpeculativeSet object (spec-v2.md §10.2) for the candidate
set; when re-routing, the host supplies the Outcome object (spec-v2.md §10.3) from its Outcome
Ledger.

## Result contract (what a delegated worker returns)
- Artifact or exact diff; files touched; which non-goals were honored.
- All checks actually executed with exit statuses and captured output references. "Passed" claims
  without an observed run are **unverified evidence** (plan S10).
- Ledger deltas: dispatches used, time used, any new uncertain charges (never release reservation on
  cancellation alone — plan S19/B02c).
- Explicit unknowns; nothing may be reported as verified that lacks observed evidence.
- Optional soft dependency declarations (`blocks` / `unblocks`) for host scheduling only —
  SmartRouter itself does not schedule (spec-v2.md §8.6).

## Attempt, repair and ledger rules that override any local preference
- Immutable same-profile tuple `(host-profile-id, harness, provider, model-id/revision,
  tool/output-config revision)` defines a repair as same-profile (harness = the agent runtime,
  e.g. a Claude Code / Codex / Cursor-class CLI); equal prices/labels/predicted quality do not.
- At most **one** same-profile corrective dispatch per original task; the allowance is not renewed by
  restarting, renaming, changing profiles or escalating (plan R01/R02/R03). A CI-phase
  correction spends that same single allowance — there is no second repair cycle. (The
  background host-policy sketch [host-hil-policy.md](host-hil-policy.md) used to budget a
  separate CI-repair cycle; it has been tightened to this one-repair total — former flag 1,
  resolved.)
- All physical dispatches — initial, planner, verifier, transport retry, repair, escalation, and any
  host-internal hidden retry — consume the single approved task call budget; cancelled/timeout calls
  still count (plan R03).
- Before sending, persist the task/attempt id and reserve the call slot; `send_started` with unknown
  acceptance counts as consumed until the host proves otherwise.
- Side-effecting dispatch with unknown acceptance, unresolved tools or committed stream output
  forbids automatic replay/provider switch: reconcile the original operation first (plan S11/S12).
- Stats and completion claims above attempt level belong to the separately authorized evaluation
  flow (see skill `smart-router-eval-prep`), never to per-task routing.

## Isolation and ownership (v1.1, extended v2.0)

- SmartRouter recommends the **minimum** isolation (`none` < `directory` < `worktree+branch` <
  `ephemeral-container`); the host may only choose equal or stronger — weaker is a protocol
  violation (spec-v2.md §6). Preferred for coding work: a dedicated **git worktree + branch**
  owned by exactly one worker. Parallel workers must never share a mutable working tree when
  any form of isolation was requested.
- Ownership is explicit and sticky: the worker that received the brief owns the acceptance
  contract from start to acceptance (or explicit escalation); for a `speculative` set, the first
  candidate to satisfy the acceptance contract becomes the sole owner; nested sub-briefs stay
  owned by the parent worker. The project orchestrator plans, prioritizes and delegates; it
  never becomes the owner of a concrete brief.
- Ownership never transfers silently, and never without a fresh decision: if the owner is no
  longer eligible, the whole route is re-evaluated from Gate 1.

## Closed feedback loop (v1.1)

- Verification failures, CI failures and review comments return to the **same owning profile**
  as a new brief for that owner — not to a fresh worker, and not to the orchestrator.
- At most one same-profile corrective dispatch per original task — CI failures and review
  comments included (the attempt rules above are unchanged and still override any local
  preference).
- Status is **derived from observable facts** — checks actually run with exit statuses, PR/CI
  state, acceptance results — never from an agent's self-report. A self-reported "done" or
  "tests passed" is unverified until observed evidence exists (plan S10).
- A failed verification re-enters routing as an Outcome object (spec-v2.md §10.3) supplied by
  the host's Outcome Ledger; SmartRouter stays stateless and may recommend continuation with a
  refined brief, ownership escalation, an isolation change, or `blocked`.
