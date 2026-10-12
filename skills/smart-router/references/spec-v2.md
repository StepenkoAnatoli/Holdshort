# SmartRouter + Isolated Workers — Complete Working Specification v2.0

**Status:** single source of truth for the SmartRouter **v2.0 surface** — routes, isolation,
ownership, HumanGate, nesting, speculative sets, machine-readable objects, Host
responsibilities, compliance. Strictly additive over the pinned five-gate contract
([gates.md](gates.md), fixture-pinned to `docs/DEVELOPMENT_PLAN.md@d7c00f9`): where the two
overlap they agree; gate semantics remain fixture-pinned, surface semantics live here.
The skill ([SKILL.md](../SKILL.md)) is the decision procedure; this document is its complete
external contract. Per §13, later versions are strictly additive, and a Host implementing
only up to version *N* must ignore unknown fields and refuse any route it cannot enforce.

## 1. Purpose

SmartRouter is a fail-closed, deterministic routing policy for coding-agent systems.
For every coding task it decides:

- which profile (model + tools + configuration) is eligible
- whether work should be done directly, delegated to an isolated worker, explored in parallel, escalated, or blocked
- the minimum isolation strength required
- who owns the acceptance contract
- when a human must intervene

SmartRouter itself never executes code, creates worktrees, spends money, or switches models.
All enforcement, isolation, budgeting, and side-effects belong to a Host.

This document is the complete, self-contained specification of both the policy and the required Host contract.

## 2. Core Principles

1. **Fail-closed** — any unknown or missing evidence results in `blocked`. Never silent downgrade.
2. **Deterministic** — identical inputs always produce identical decisions.
3. **Advisory-only** — SmartRouter only recommends; the Host alone may act.
4. **Ownership is sticky** — all feedback returns to the current owner.
5. **Isolation is a lower bound** — Host may only strengthen isolation, never weaken it.
6. **Observed evidence only** — claims without runner logs or recorded checks are unverified.
7. **No resurrection** — a candidate rejected by any gate stays rejected for that decision.
8. **Counters never reset** — rename, restart, or profile change does not renew cash, call, or attempt budgets.

## 3. Roles

| Role                  | Responsibility |
|-----------------------|----------------|
| **SmartRouter**       | Pure decision procedure. Emits route, constraints, and machine-readable objects. |
| **Host**              | Collects inputs, enforces every decision, creates isolation, runs agents, accounts for spend, routes feedback, maintains the Outcome Ledger. |
| **Project Orchestrator** (optional) | Long-lived planning context. May request routes and spawn workers. Never owns an implementation brief. |
| **Worker**            | Owns exactly one brief from start to acceptance (or explicit escalation). Runs inside the isolation requested by SmartRouter. |
| **Human**             | Intervenes only when `HumanGate` requires it. |

## 4. Decision Model — Ordered Gates

Before any dispatch the Host collects the named inputs and asks SmartRouter to evaluate **every** candidate profile against the five gates **in strict order**. A candidate failing any gate is rejected.

**Gate 1 — Permissions / Privacy / Workflow**
- Identify authorized actor, provider, destination, data classes and effects.
- Default deny for unknown identity, path or destination.
- Read-only is **not** automatically non-disclosing.
- Project stop-rules block new work.

**Gate 2 — Capabilities**
- Task qualification, required active tools, input modalities, output contract, tested context headroom.
- Labels, price tier or self-confidence are **not** capability proof.
- Capability fingerprints must be present and fresh; missing or stale fingerprints fail this gate.

**Gate 3 — Verification**
- Acceptance contract must be defined **before** work starts.
- Required checks must be available and affordable.
- Missing prerequisite before start → `blocked`.
- Ambiguous evidence after start → unverified.
- Observed violation → failed.

**Gate 4 — Affordability**
- Conservative bound for all mandatory work **plus required verification** must fit remaining allowance.
- Equality is allowed for cash and call slots.
- Deadline requires current time **strictly before** expiry.
- Unknown or unbounded fees block any strict cap.

**Gate 5 — Economics**
- Only candidates that passed Gates 1–4 are compared.
- Prefer `direct` when suitable.
- `delegate` only for one isolated, bounded unit that shows all-overhead benefit.
- `speculative` only under high uncertainty **and** when the Host has explicitly opted in.
- Recommend escalation when direct is unsuitable.
- Empty eligible set → `blocked`.

## 5. Route Types

| Route                    | Meaning |
|--------------------------|---------|
| `direct`                 | Chosen profile performs the work itself. |
| `delegate`               | Spawn one isolated Worker that becomes the sole owner of the brief. |
| `speculative`            | Spawn a bounded parallel set of candidates; first success wins; losers are cancelled. |
| `recommend-escalation`   | No current candidate is suitable; recommend a stronger eligible profile. |
| `blocked`                | No eligible candidate exists. Report the first failing gate and reason. |

## 6. Isolation Contract

SmartRouter recommends the **minimum** isolation strength required:

| Value                   | Description |
|-------------------------|-------------|
| `none`                  | Shared working tree (only for trivial, low-blast-radius work). |
| `directory`             | Isolated directory with no shared mutable state. |
| `worktree+branch`       | Dedicated git worktree + unique branch (preferred default). |
| `ephemeral-container`   | Clean container or VM (highest isolation). |

**Host rule (normative):** the Host may only choose equal or stronger isolation. Choosing weaker isolation is a protocol violation.

Recommended branch naming: `sr/<task-id>/<short-slug>`.

## 7. Ownership & Feedback Loop

- Every `delegate` route (or the winning candidate of a `speculative` set) becomes the **Owner**.
- Verification failures, CI failures, and review comments **always** return to the current Owner.
- At most one same-profile corrective dispatch is permitted under the original allowance.
- Ownership never transfers silently. If the Owner becomes ineligible, a full new SmartRouter decision is required.
- The Project Orchestrator may observe status and request new routes; it does not become Owner of an existing brief.

## 8. Adaptive Features

**8.1 Adaptive Isolation**
Isolation strength is derived from the combination of Gate 1 (permissions/privacy), Gate 3 (consequence class) and Gate 5 (economics). See table in §6.

**8.2 HumanGate**

| Value                      | Meaning |
|----------------------------|---------|
| `none`                     | Fully autonomous. |
| `review-before-dispatch`   | Human must approve the brief before the Worker is spawned. |
| `review-before-merge`      | Human must approve before acceptance or merge. |
| `approval-required`        | Explicit human authorization is required for this route. |

**8.3 Nested Delegation**
- Permitted only when SmartRouter sets `NestedAllowed: yes`.
- Parent Worker remains the Owner.
- Sub-worker receives a NestedBrief with tighter bounds and a reduced allowance.
- All cash, call and attempt counters roll up to the original task.
- Default maximum depth = 1 (Host policy may raise it to 2).

**8.4 Speculative Parallel Candidates**

```
Route: speculative
SpeculativeSet:
  candidates: [ {profile, weight?}, ... ]
  max-parallel: N
  shared-budget: { cash, calls }
  cancel-policy: first-success | budget-exhausted | all-fail
  winner-owns: true
```

Rules:
- The shared budget is a hard ceiling across the entire set.
- The first candidate that satisfies the acceptance contract becomes the sole Owner.
- Losers are cancelled; their partial results are retained only as evidence.
- Speculative mode is opt-in under any strict cash cap.
- Nested speculative sets are not allowed.

**8.5 Outcome-Aware Re-routing**
The Host may supply a `PreviousResult`. SmartRouter may then recommend continuation with a refined brief, escalation of ownership, change of isolation, or `blocked`.
SmartRouter remains stateless; the Host owns the Outcome Ledger.

**8.6 Dependency Declarations**
Workers may emit soft `blocks` / `unblocks` lists in their Result. The Host or Project Orchestrator may use them for scheduling. SmartRouter itself does not perform scheduling.

## 9. Required Output Format

Every SmartRouter decision must contain:

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
Uncertainty:       <list of exact unknowns; never hide unpriced or unbounded fees>
```

When `Route` is `delegate` or `speculative`, the corresponding machine-readable object(s) defined in §10 **must** also be emitted.

When the Host cannot act on the recommendation, add:

```
Advisory: recommendation only — no dispatch performed or claimed
```

## 10. Machine-Readable Objects (Normative Schemas)

**10.1 Brief** (required for every `delegate`)

```json
{
  "objective": "string",
  "acceptance": {
    "checks": [
      { "command": "string", "expect": "string" }
    ]
  },
  "sources": ["string"],
  "permitted-effects": ["string"],
  "non-goals": ["string"],
  "isolation": "none | directory | worktree+branch | ephemeral-container",
  "branch-hint": "string",
  "allowance": {
    "cash": 0.0,
    "calls": 0,
    "deadline": "ISO-8601 datetime"
  },
  "attempts": 1,
  "stop-triggers": ["string"],
  "ownership": "worker",
  "nested-allowed": false,
  "max-nesting-depth": 1
}
```

**10.2 SpeculativeSet** (required for every `speculative` route)

```json
{
  "candidates": [
    { "profile": "string", "weight": 1.0 }
  ],
  "max-parallel": 2,
  "shared-budget": {
    "cash": 0.0,
    "calls": 0
  },
  "cancel-policy": "first-success | budget-exhausted | all-fail",
  "winner-owns": true
}
```

**10.3 Outcome / PreviousResult** (supplied by Host for re-routing)

```json
{
  "task-id": "string",
  "outcome": "accepted | verification-failed | partial | cost-overrun | cancelled | blocked | escalated",
  "evidence": {
    "checks": [
      {
        "command": "string",
        "exit-code": 0,
        "output-ref": "string"
      }
    ],
    "actual-spend": 0.0,
    "files-touched": ["string"],
    "notes": "string"
  },
  "original-brief-fingerprint": "string",
  "owner-profile": "string"
}
```

## 11. Host Responsibilities (Normative)

A compliant Host **must**:

1. Collect all required inputs before invoking SmartRouter.
2. Enforce every gate decision; never override a `blocked` result.
3. Create isolation at least as strong as the recommended value.
4. Inject the exact Brief (or SpeculativeSet) into each Worker's environment.
5. Account for every physical dispatch, including cancelled speculative candidates.
6. Route all verification, CI and review feedback to the current Owner.
7. Honour `HumanGate` before the corresponding action.
8. Maintain an auditable Outcome Ledger.
9. Never reset cash, call or attempt counters by rename, restart or profile change.
10. Treat missing or stale capability fingerprints as a Gate 2 failure.

A Host **may**:

- Choose stronger isolation than recommended.
- Refuse speculative mode under strict cash caps.
- Implement additional scheduling on top of dependency declarations.
- Provide a Project Orchestrator.

## 12. Hard Prohibitions

- No dispatch on unknown permissions, identity, destination, capability, price or accounting under a strict cap.
- No empty-set resurrection.
- No required-tool stripping or silent substitution of tools or models.
- No automatic replay or provider switch after side-effects with unknown acceptance.
- No shared mutable working tree when any form of isolation was requested.
- No savings or completion claim without observed, recorded evidence.
- No ownership transfer without a fresh SmartRouter decision.

## 13. Versioning

| Version | Key additions |
|---------|---------------|
| 1.0     | Five ordered gates + basic `direct` / `delegate` / `blocked` |
| 1.1     | Isolation contract, ownership model, machine-readable Brief |
| 1.2     | Adaptive isolation + HumanGate |
| 1.3     | Nested delegation + Outcome-aware re-routing |
| 1.4     | Speculative parallel candidates |
| 2.0     | Complete surface defined by this document |

Later versions are strictly additive. A Host implementing only up to version *N* must ignore unknown fields and must refuse any route it cannot enforce.

## 14. Compliance

A system is **SmartRouter-compliant** when and only when:

- it treats this specification as the sole routing authority,
- it implements all Host responsibilities in §11,
- it never violates the hard prohibitions in §12,
- and it can correctly produce and consume the objects defined in §10.

**End of Specification**
