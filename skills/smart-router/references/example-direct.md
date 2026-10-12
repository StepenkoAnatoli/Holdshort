# Example: When SmartRouter Chooses `direct`

**Status:** worked example — non-normative. The normative contract is [gates.md](gates.md)
(fixture-pinned) and [spec-v2.md](spec-v2.md); where this example and the normative files
ever disagree, **the normative files win**. Flagged, not fixed: the decision block below is
abbreviated (a real decision must also contain `MaxNestingDepth`, `Reservations`, `Calls`,
`Deadline` and `Uncertainty` — the last one is never omitted, since an unpriced fee must
never be hidden), `Profile` is shown as a model label where §9 requires the full identity
tuple, and the Summary arrived truncated mid-sentence and is preserved exactly as received.

## Scenario

You ask the system:

> "Add a simple docstring to the function `calculate_total()` in `utils/pricing.py` that
> explains the parameters and return value."

## Why `direct` is chosen

This task is a classic case for the default preference:

- **Low difficulty** — It is a small, localized change (one function, one file).
- **Low blast radius** — Almost no risk of breaking other parts of the system.
- **Cheap verification** — A quick syntax check or existing unit test is enough.
- **Low overhead** — Creating a new worker, writing a formal brief, and managing a worktree
  would cost more time and tokens than just doing the edit.
- **Current profile is sufficient** — The model already has the file in context and is fully
  capable of writing a correct docstring.

Because a good direct option exists and passes all five gates, Gate 5 selects `direct`
instead of paying the extra cost of isolation and delegation.

## What the decision looks like

```
Difficulty:        trivial
Route:             direct
Profile:           claude-sonnet-4          # (or whatever the current eligible profile is)
Isolation:         none
IsolationReason:   single-file, low-risk documentation change
Owner:             orchestrator             # or current session
HumanGate:         none
NestedAllowed:     no
```

## Summary

SmartRouter chooses `direct` when the task is small, low-risk, easy to verify, and the
current profile can handle it cleanly. In these cases, the overhead of creating an i

*(Editor's note: the sentence above is preserved exactly as received — the source arrived
truncated mid-sentence.)*
