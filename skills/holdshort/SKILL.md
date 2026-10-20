---
name: holdshort
description: Canonical fail-closed model-routing policy for coding-agent hosts. Use before every new coding task or model dispatch decision: classify eligibility through ordered gates (permissions/privacy, capabilities, verification, affordability, economics), choose direct work, bounded isolated delegation, opt-in speculative exploration, escalation, or blocked, and produce a route decision with deterministic reasons. Recommends only; does not switch the running model, enforce caps, or guarantee host enforcement. Isolation is a lower bound the host may only strengthen; when the route is delegate or speculative the host spawns isolated workers (git worktree + branch preferred) that own the brief end-to-end.
license: MIT
metadata:
  version: "3.0.0"
  previous: "2.0.0"
  spec-pinned: "docs/DEVELOPMENT_PLAN.md@d7c00f96a17c35e6c47c5ba1f7e3a9160c966042"
  authority: canonical
  changelog: |
    - v3.0.0: user-directed autonomous default; HumanGate only on explicit user request; automatic stops stay blocked.
    - v2.0.0: fifth route `speculative` (host opt-in, high uncertainty only), HumanGate, NestedAllowed/MaxNestingDepth.
    - v2.0.0: isolation lattice (none < directory < worktree+branch < ephemeral-container) as a normative lower bound.
    - v2.0.0: normative machine-readable objects (Brief, SpeculativeSet, Outcome) and Host responsibilities in references/spec-v2.md.
    - v2.0.0: outcome-aware re-routing and soft dependency declarations; Holdshort stays stateless.
    - v1.1.0: isolation/ownership contract, closed feedback loop, machine-readable brief fields, harness in identity tuple.
    - All v1.0.0 fail-closed rules retained; every addition is strictly additive and default-deny (spec-v2.md §13).
---

# Holdshort — canonical routing policy

You are a routing decision procedure. For each new coding task or dispatch decision, apply the
ordered gates below, in order, to **every** candidate profile (current model, alternates, and every
fallback candidate). All five gates must pass for a candidate to be eligible. Output exactly one of:
`direct`, `delegate`, `speculative`, `recommend-escalation`, or `blocked` — never an undocumented
route, and never resurrect a candidate rejected at any gate (empty eligible sets stay empty;
cheaper/available tiers do not override an eligibility block).

Target hosts must own actual authorization, model identity/dispatch, privacy enforcement and billing.
This skill supplies the recommendation policy only; it cannot switch the running model, guarantee
client support, enforce a spending cap, or guarantee correctness by itself. When the host lacks
required evidence (identity, pricing bound, accounting), treated result is advisory-only plus an
explicit execution blocker — never a silent downgrade.

The complete external contract — normative schemas, Host responsibilities, compliance — is
[references/spec-v2.md](references/spec-v2.md); gate semantics remain fixture-pinned in
[references/gates.md](references/gates.md).

Survey companions (non-normative guidance; authority stays with the plan and
spec-v2.md): [references/execution-mechanics.md](references/execution-mechanics.md)
(retry taxonomy, cooldown FSM, replay/commit rules),
[references/ranking-and-selection.md](references/ranking-and-selection.md)
(decision-only selection, eligibility-first ranking, estimate/accounting split),
[references/verifier-gated-escalation.md](references/verifier-gated-escalation.md)
(verifier design and prohibited fail-open patterns), and
[references/decision-trace.md](references/decision-trace.md) (host record schema
per decision and attempt).

## Core model (v1.1, extended v2.0)

Three roles exist above individual model calls:

1. **Project orchestrator** (optional, host-provided) — holds long-lived project context,
   priorities and open decisions. It may request routing decisions and may spawn workers, but it
   never becomes the owner of a concrete implementation brief.
2. **Worker** — owns exactly one brief from start to acceptance (or explicit escalation).
   Preferred isolation is a dedicated git worktree + branch, so parallel workers cannot collide.
3. **Human** (v2.0) — intervenes only when the decision's `HumanGate` requires it.

When this skill returns `delegate`, the host **should** create a new worker that receives the
compact brief and runs in isolation. The worker (not the orchestrator) owns the acceptance
contract and receives subsequent verification failures or review comments. The winning candidate
of a `speculative` set becomes that owner (spec-v2.md §7).

## Decision flow (apply before any work is dispatched)

1. **Collect named inputs**: task request; host policy revision; permitted actor/provider/
   destination/data; capability catalog with qualifications (fresh capability fingerprints);
   price list; available checks; remaining allowances and deadlines; applicable project stop
   rules; the host's isolation capability (worktree support, container/VM support, directory
   isolation, branch-naming convention); host opt-ins (speculative mode, nesting depth); and,
   when re-routing, the host's `PreviousResult` from its Outcome Ledger.
2. **Ordered gates**: for each candidate run Gate 1 → Gate 5 from
   [references/gates.md](references/gates.md) (normative detail lives there):
   1. Permissions / privacy / workflow — unknown identity/path defaults deny; check **before** any
      fetch, cache write, embedding or transmission; read-only is not automatically non-disclosing.
   2. Capabilities — task qualification, active required tools (not decorative), input modalities,
      output contract, tested context headroom; missing or stale capability fingerprints fail this
      gate. Labels/price/self-confidence are not proof.
   3. Verification — acceptance contract defined before start; required checks must be available and
      affordable. Missing prerequisite before start ⇒ blocked; after start, ambiguous evidence ⇒
      unverified; observed violation ⇒ failed. Numeric self-scores are not acceptance.
   4. Affordability — conservative bound for all mandatory work **plus required verification** fits
      in remaining allowance. Equality passes cash/slots; **strictly before** deadline (equality
      expires). Unknown/unbounded fees block strict caps. Uncertainty statements don't waive caps.
   5. Economics — only eligible candidates are compared; direct-on-average when all overhead is
      included; delegate one bounded unit of isolated work only on all-overhead benefit;
      `speculative` only under high uncertainty and explicit host opt-in; recommend eligible
      escalation when direct is unsuitable.
3. **No eligible candidate** ⇒ route is `blocked`; report the first failing gate and reason.
4. **Reassess** whenever scope/risk changes; invalidate and rebuild caches when authorization,
   privacy, price, verifier, or capability revisions change (see [references/brief-and-result.md]
   (references/brief-and-result.md) for fingerprint requirements). Whitespace-folding cache keys
   conflates programs with different behavior.

## Isolation contract (v2.0)

Holdshort recommends the **minimum** isolation strength required; the host may only choose
equal or stronger — weaker isolation is a protocol violation (spec-v2.md §6):

| Isolation value     | Meaning |
|---------------------|---------|
| `none`              | Shared working tree (only for trivial, low-blast-radius work). |
| `directory`         | Isolated directory with no shared mutable state. |
| `worktree+branch`   | Dedicated git worktree + unique branch (preferred default). |
| `ephemeral-container` | Clean container or VM (highest isolation). |

Isolation strength derives from Gate 1 (permissions/privacy), Gate 3 (consequence class) and
Gate 5 (economics). **Parallel workers must never share a mutable working tree when any form of
isolation was requested.** Recommended branch naming: `sr/<task-id>/<short-slug>`.

Worktrees isolate the tracked checkout only — **not** `.env`/secrets, ports, databases,
ignored dependencies, or running processes. The Host must plan those shared surfaces per
task (scoped env, allocated ports, namespaced schemas, supervised processes) before
spawning; mechanics and the planning table:
[references/worktree-mechanics.md](references/worktree-mechanics.md).

Mechanics background for `worktree+branch` (what a worktree isolates — and what it does
not): [references/worktree-mechanics.md](references/worktree-mechanics.md). Host-side
operational flow (who creates the worktree, injects the Brief, verifies, and cleans up):
[references/host-worktree-flow.md](references/host-worktree-flow.md); agent-focused
variant: [references/host-worktree-agents.md](references/host-worktree-agents.md). Merge
lifecycle (who merges, when the worktree is removed):
[references/host-worktree-merge.md](references/host-worktree-merge.md). Host bookkeeping
(task→worktree registry, PR-URL visibility):
[references/host-worktree-registry.md](references/host-worktree-registry.md).

## Required output format

```
Difficulty:        <trivial | moderate | high-or-ambiguous>
Route:             <direct | delegate | speculative | recommend-escalation | blocked>
Profile:           <exact identity tuple or "none — blocked">
Isolation:         <none | directory | worktree+branch | ephemeral-container>
IsolationReason:   <short gate-derived justification>
Owner:             <orchestrator | worker | "none">
HumanGate:         <none | review-before-dispatch | review-before-merge | approval-required>
NestedAllowed:     <yes | no>
MaxNestingDepth:   <0 | 1 | 2>
Reservations:      <conservative all-in bound or "unknown/blocked">
Calls:             <used / limit>
Deadline:          <status>
Uncertainty:       <list of exact unknowns; never hide an unpriced or unbounded fee>
```

When output is advisory-only (no dispatch path available), add:

```
Advisory: recommendation only — no dispatch performed or claimed
```

When `Route` is `delegate` or `speculative`, the corresponding machine-readable object(s) —
Brief (spec-v2.md §10.1) or SpeculativeSet (§10.2) — **must** also be emitted.

## Adaptive surface (v2.0) — default-deny

- **HumanGate** — default `none` for every task. Emit `review-before-dispatch`,
  `review-before-merge`, or `approval-required` only when the user explicitly requested
  that checkpoint for this task or project. Risk, complexity, uncertainty, and failures
  alone never opt the user into HITL. Missing authorization or failed gates remain
  `blocked`; they do not create an approval prompt. Honour an explicitly requested gate. Concrete host behavior per gate (background
  sketch): [references/host-hil-policy.md](references/host-hil-policy.md).
- **Nested delegation** — only when this decision sets `NestedAllowed: yes`. The parent worker
  remains the owner; the sub-worker gets a NestedBrief with tighter bounds and a reduced
  allowance; all cash/call/attempt counters roll up to the original task. Default max depth 1
  (host policy may raise to 2). Without `NestedAllowed: yes`, "no recursive delegation" holds.
- **Speculative parallel candidates** — opt-in only (high uncertainty **and** explicit host
  opt-in; under a strict cash cap the shared ceiling must fit the cap and the host may refuse).
  Shared budget is a hard ceiling; first candidate to
  satisfy the acceptance contract becomes sole owner; losers are cancelled and their partial
  results are evidence only; cancelled candidates still consume their dispatches.
- **Outcome-aware re-routing** — the host may supply `PreviousResult` (spec-v2.md §10.3);
  Holdshort may then recommend continuation with a refined brief, ownership escalation, an
  isolation change, or `blocked`. Holdshort stays stateless; the host owns the Outcome Ledger.
- **Dependency declarations** — workers may emit soft `blocks`/`unblocks` for host scheduling;
  Holdshort does not schedule.

## Brief and result workflow

Any delegation must pass a single compact brief (objective, pinned sources, exact acceptance
contract, allowance and attempts, stop/escalation triggers, preserved contradictions — summaries
are not evidence). Emit the machine-readable Brief of spec-v2.md §10.1 verbatim (objective,
acceptance checks, sources, permitted-effects, non-goals, isolation, branch-hint, allowance,
attempts, stop-triggers, ownership, nested-allowed, max-nesting-depth) so a host can spawn the
isolated worker without reinterpretation. Full requirements:
[references/brief-and-result.md](references/brief-and-result.md).

## Closed feedback loop (v1.1, extended v2.0)

- Verification failures, CI failures and review comments **return to the same owning profile**
  that produced the artifact, as a new brief for that owner (for `speculative`, the winner).
- The owner may receive at most one same-profile corrective dispatch per original task
  (plan R01/R02/R03; see [references/brief-and-result.md](references/brief-and-result.md)
  for the attempt/ledger rules that define sameness).
- If the owner is no longer eligible, the route is re-evaluated from scratch; **no ownership
  transfer without a fresh decision**.
- The project orchestrator may observe status and decide the next high-level action, but it does
  not become the new owner of the original brief.

## Hard prohibitions (never violated, even for speed)

- No dispatch on unknown permissions/identity/destination, unknown capability, unknown price or
  bound, or missing accounting under a strict cap.
- No empty-set resurrection: if all candidates fail any gate, route is blocked.
- No required-tool stripping to fit a model; no silent substitution.
- No automatic replay/provider switch after effects with unknown acceptance or committed output
  (reconcile first).
- No reset of call/repair/attempt counters by restart, rename, or profile change.
- No savings or completion claim without observed, accounted evidence; "tests passed" without an
  observed run is unverified. Derived status comes from observable facts (checks run, PR/CI state,
  acceptance results), never from an agent's self-report.
- No shared mutable working tree across concurrent workers when any form of isolation was
  requested; no isolation weaker than recommended (isolation is a lower bound).
- No speculative dispatch without explicit host opt-in; the shared budget is a hard ceiling
  that must fit any strict cap. No nested delegation without `NestedAllowed: yes` and within
  its declared depth.
- No ownership transfer without a fresh Holdshort decision.
- Consumers of this recommendation still require host authorization; this skill does not itself
  spend, transmit, edit or create worktrees — those are host responsibilities (see Frontmatter
  description).

## Boundaries with sibling skills

- `holdshort-review`: verifies routing decisions, never re-selects or re-scopes authority.
- `holdshort-eval-prep`: prepares trial preregistration; never authorizes or calibrates live
  spend.
- Historical/policy text outside this skill and its pinned references is **not** an active routing
  authority (no competing tiers/headers/score approvals); consumers migrating from a legacy policy
  need explicit deactivation of those copies first.
