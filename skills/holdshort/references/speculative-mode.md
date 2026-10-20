# Speculative Option in Holdshort

**Status:** explanatory companion to spec-v2.md §8.4 and Gate 5 in [gates.md](gates.md) —
non-normative. The normative contract is [gates.md](gates.md) (fixture-pinned) and
[spec-v2.md](spec-v2.md); where this narrative and the normative files ever disagree,
**the normative files win**.

The `speculative` route is a controlled way to try multiple profiles in parallel when the
system is uncertain which one will succeed.

## When It Is Used

Holdshort may choose `speculative` only when **all** of these conditions are true:

1. Uncertainty is high (the skill cannot confidently pick a single best profile).
2. At least two eligible candidates exist (they have already passed Gates 1–4).
3. The Host has explicitly opted in to speculative mode (especially important under strict
   budget caps).
4. A hard shared budget can be defined.

If any of these are missing, Holdshort will not emit a speculative route.

## How It Works

Instead of picking one profile, Holdshort outputs a `SpeculativeSet`:

```json
{
  "candidates": [
    { "profile": "claude-sonnet", "weight": 1.0 },
    { "profile": "gpt-4.1", "weight": 0.8 }
  ],
  "max-parallel": 2,
  "shared-budget": {
    "cash": 0.60,
    "calls": 8
  },
  "cancel-policy": "first-success",
  "winner-owns": true
}
```

**Key rules:**

| Rule | Meaning |
|------|---------|
| Shared budget | All candidates together must stay inside one hard cash + call limit. |
| Max parallel | Host must not run more candidates at once than this number. |
| Cancel policy | Usually `first-success` — as soon as one candidate satisfies the acceptance contract, the others are cancelled. |
| Winner owns | The successful candidate becomes the sole Owner of the brief. Losers lose ownership. |
| Losers are evidence only | Partial results from cancelled candidates may be kept for learning, but they never become the official artifact. |

## Why This Exists

Sometimes the cheapest model might work, but you're not sure.
Sometimes the stronger model is safer, but more expensive.

Speculative mode lets the system try both under a strict combined budget. The first one that
actually passes the acceptance checks wins, and the rest are stopped.

This gives the benefits of exploration while still obeying fail-closed accounting.

## Important Limitations

- Speculative mode is **never** the default. It is opt-in.
- The shared budget is a hard ceiling — the Host must enforce it.
- Ownership is not shared. Only the winner becomes Owner.
- Nested speculative sets are not allowed (keeps complexity under control).
- If the shared budget is exhausted before any candidate succeeds, the whole set fails and the
  route becomes `blocked` or is re-evaluated.

## Summary

`speculative` = "I'm not sure which eligible profile will succeed, so try a few in parallel
under one hard budget. Keep the first one that actually works and cancel the rest."

It is the controlled, budget-aware version of parallel exploration.
