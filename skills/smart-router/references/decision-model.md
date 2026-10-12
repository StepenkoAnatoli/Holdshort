# SmartRouter Decision Model — The Five Ordered Gates

**Status:** explanatory companion. The normative contract is [gates.md](gates.md)
(fixture-pinned to the plan) and [spec-v2.md](spec-v2.md) (the v2.0 surface); where this
narrative and the normative files ever disagree, **the normative files win**. This document
explains *why* the gates are ordered the way they are — it adds no rules.

Default preferences and settings: [defaults.md](defaults.md). Worked examples:
[example-direct.md](example-direct.md) (`direct`),
[example-delegate.md](example-delegate.md) (`delegate`),
[example-isolation.md](example-isolation.md) (when isolation is required).
Background: [worktree-mechanics.md](worktree-mechanics.md) (why `worktree+branch` isolates
agents — and what it does not isolate); host-side flow:
[host-worktree-flow.md](host-worktree-flow.md) (who actually creates the worktree, injects
the Brief, verifies, and cleans up); agent-focused variant:
[host-worktree-agents.md](host-worktree-agents.md); merge lifecycle:
[host-worktree-merge.md](host-worktree-merge.md); host bookkeeping (task→worktree registry,
PR-URL visibility): [host-worktree-registry.md](host-worktree-registry.md); human-in-the-loop
host policy sketch: [host-hil-policy.md](host-hil-policy.md).

SmartRouter evaluates **every** candidate profile (current model, alternates, fallbacks)
against five gates **in strict sequential order**. A candidate must pass **all five** gates to
be eligible. The first gate that fails rejects that candidate permanently for the current
decision (no resurrection).

Here is what each gate does and why the order is fixed:

## Gate 1 — Permissions / Privacy / Workflow

**Purpose:** Safety and authorization first.

- Identifies the authorized actor, provider, destination, data classes, and permitted effects.
- Default posture is **deny** for anything unknown (unknown identity, path, or destination).
- Explicitly treats read-only operations as potentially disclosing (prompt bytes still leave
  the machine).
- Also enforces project-level stop rules.

**Why first?**
No amount of capability, cheap price, or clever economics can justify acting without
permission. This gate stops unsafe or unauthorized work before any other consideration.

## Gate 2 — Capabilities

**Purpose:** Can this profile actually do the required work?

- Checks task qualification, required **active** tools (not decorative ones), input modalities
  (vision, etc.), output contract, and tested context headroom.
- Labels, price tiers, or the model's own confidence statements are **not** accepted as proof.
- Requires fresh capability fingerprints; missing or stale fingerprints fail the gate.

**Why second?**
Once we know the action is allowed, we must confirm the profile is technically able to
perform it. Capability is checked before cost so we never select a cheap but incapable model.

## Gate 3 — Verification

**Purpose:** Can we prove the work is correct?

- The acceptance contract (exact checks/commands) must be defined **before** work starts.
- Required verification must be available and affordable.
- Missing prerequisite before start → blocked.
- Ambiguous evidence after start → unverified.
- Observed failure → failed.

**Why third?**
Even a capable and authorized profile is useless if we cannot verify its output. This gate
forces the system to plan for evidence, not just generation.

Detailed explanation: [gate3-verification.md](gate3-verification.md).

## Gate 4 — Affordability

**Purpose:** Does it fit the remaining budget?

- Calculates a conservative bound that includes **all mandatory work plus required
  verification**.
- The bound must fit inside remaining cash and call allowances.
- Equality is allowed for cash/slots; deadlines require the current time to be **strictly
  before** expiry.
- Unknown or unbounded fees cause an automatic block under any strict cap.

**Why fourth?**
Only after we know the work is allowed, possible, and verifiable do we ask whether we can
afford it. Cost is never allowed to override safety or correctness.

Detailed explanation: [gate4-affordability.md](gate4-affordability.md).

## Gate 5 — Economics

**Purpose:** Among the remaining eligible candidates, which choice is best?

- Compares only the candidates that passed Gates 1–4.
- Prefers `direct` when it is suitable.
- Allows `delegate` only for one isolated, bounded unit that shows an all-overhead benefit.
- Allows `speculative` only under high uncertainty **and** when the Host has explicitly
  opted in.
- Recommends escalation when direct work is unsuitable.
- Empty eligible set → `blocked`.

**Why last?**
Economics is the final optimization step. It never overrides any earlier hard constraint.
This is also where the system decides between direct execution, isolated delegation, parallel
speculation, or escalation.

Detailed explanation: [gate5-economics.md](gate5-economics.md).

## Summary of the Logic Flow

```
For each candidate profile:
  Gate 1 (Permissions)  → fail? reject
  Gate 2 (Capabilities) → fail? reject
  Gate 3 (Verification) → fail? reject
  Gate 4 (Affordability)→ fail? reject
  Gate 5 (Economics)    → compare survivors
```

If no candidate survives all five gates → route = `blocked`.

This strict ordering is the core of SmartRouter's fail-closed design: safety and correctness
are never traded for speed or cost.
