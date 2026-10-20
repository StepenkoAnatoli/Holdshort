# Gate 5 — Economics

**Status:** explanatory companion to Gate 5 in [gates.md](gates.md) — non-normative. The
normative contract is [gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md);
where this narrative and the normative files ever disagree, **the normative files win**.

Gate 5 is the final decision gate. By the time a candidate reaches Gate 5, it has already
passed:

- Gate 1 (Permissions)
- Gate 2 (Capabilities)
- Gate 3 (Verification)
- Gate 4 (Affordability)

Gate 5's only job is to choose the **best economic option** among the remaining eligible
candidates (or decide that none of them is worth doing).

## What Gate 5 Decides

Gate 5 selects one of these outcomes:

| Decision | Meaning |
|---------|---------|
| `direct` | The current (or chosen) profile should do the work itself. |
| `delegate` | Spawn one isolated Worker that will own the brief. |
| `speculative` | Launch a small parallel set of candidates and keep the first one that succeeds. |
| `recommend-escalation` | None of the current eligible profiles is suitable; recommend a stronger one. |
| `blocked` | No eligible candidate remains (this should be rare at Gate 5, but is still possible). |

## Core Decision Rules

1. **Prefer `direct` when it is suitable**
   If a profile can do the work well and the all-in cost is reasonable, Holdshort prefers to
   keep the work on the current profile instead of paying the overhead of delegation.

2. **Allow `delegate` only with clear all-overhead benefit**
   Delegation is permitted only when the total cost of:
   - writing the brief
   - running the isolated worker
   - possible review / repair
   - re-priming context

   is still better than doing the work directly. Token cost of the worker alone is **not**
   enough justification.

3. **Allow `speculative` only under high uncertainty**
   Parallel exploration is allowed only when:
   - uncertainty is genuinely high, **and**
   - the Host has explicitly opted in to speculative mode, **and**
   - a hard shared budget is defined.

   See [speculative-mode.md](speculative-mode.md) for the full option.

4. **Recommend escalation when direct is unsuitable**
   If the best remaining candidate is still a poor fit, Holdshort can output
   `recommend-escalation` instead of forcing a bad direct or delegate choice.

5. **Empty set → blocked**
   If no candidate survived the earlier gates, Gate 5 simply confirms `blocked`. It never
   resurrects previously rejected candidates.

## Why Gate 5 Comes Last

Gates 1–4 are hard constraints (safety, capability, correctness, budget).
Gate 5 is an **optimization** step. It is never allowed to override any earlier rejection.

This ordering guarantees that cost and speed can never override safety or correctness.

## Simple Decision Logic (Conceptual)

```
eligible = candidates that passed Gates 1–4

if eligible is empty:
    return blocked

if a good direct option exists:
    return direct

if one isolated delegate shows clear all-overhead benefit:
    return delegate

if uncertainty is high and Host allows speculation:
    return speculative

if a stronger profile is available and eligible:
    return recommend-escalation

return blocked
```

## Summary

**Gate 5 answers the final question:**

> "Among the profiles that are allowed, capable, verifiable, and affordable — what is the
> smartest way to execute this task?"

It is the only gate that performs real economic comparison. All previous gates only decide
whether a candidate is eligible at all.
