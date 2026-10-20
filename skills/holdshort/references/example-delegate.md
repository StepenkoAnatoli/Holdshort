# Example: When Holdshort Chooses `delegate`

**Status:** worked example — non-normative. The normative contract is [gates.md](gates.md)
(fixture-pinned) and [spec-v2.md](spec-v2.md); where this example and the normative files
ever disagree, **the normative files win**. The decision block below is shown **complete**
per spec-v2.md §9 (all eleven keys plus the full identity-tuple `Profile`) so this example
teaches the fail-closed format by demonstration — completed 2026-10-12 from the previously
flagged abbreviated form (git history records the shorthand).

## Scenario

You ask the system:

> "Refactor the authentication module to support both JWT and session-based auth, update all
> related tests, and make sure nothing in the billing or user-profile modules breaks."

## Why `direct` is rejected

The current profile (for example a fast, cheaper model) might be able to edit code, but:

- The change touches multiple modules and has high blast radius.
- Good verification requires running a fairly large test suite plus some integration checks.
- The all-in cost (implementation + proper verification + likely one repair cycle) becomes
  high.
- Keeping everything in the current session risks context pollution and accidental edits to
  unrelated files.

So even if the profile passes Gates 1–4, Gate 5 decides that doing it directly is not the
best economic or safety choice.

## Why `delegate` is chosen

Holdshort determines that an isolated worker is better because:

1. **Clear isolation benefit** — The worker gets its own git worktree + branch, so it cannot
   accidentally break other parts of the codebase.
2. **Clean ownership** — One worker owns the entire acceptance contract (all tests must
   pass).
3. **All-overhead calculation still wins** — Even after adding the cost of writing a good
   brief, running the worker, and possible verification, the isolated approach is judged
   safer and ultimately cheaper than risking a messy direct attempt.
4. **Bounded scope** — The brief can strictly limit the worker to the auth module and its
   tests.

## What the decision looks like

```
Difficulty:        high-or-ambiguous
Route:             delegate
Profile:           (main-host, anthropic, claude-sonnet-5-5@2026-10-01, cfg-tools-v1)
Isolation:         worktree+branch
IsolationReason:   multi-module change with high blast radius
Owner:             worker
HumanGate:         review-before-merge
NestedAllowed:     no
MaxNestingDepth:   1
Reservations:      work $0.42 + review $0.08 all-in, within $1.00 task cap
Calls:             0 used / 4 approved
Deadline:          2026-10-12T14:00:00Z (starts on dispatch; equality expires)
Uncertainty:       [integration-suite runtime upper bound unmeasured on this host]
```

Plus a machine-readable Brief that contains:

- Exact objective
- Precise acceptance checks (`pytest tests/auth/`, etc.)
- Allowed files
- Explicit non-goals (do not touch billing, do not change database schema, etc.)
- Budget and attempt limits

## Summary

Holdshort chooses `delegate` when the work is large enough, risky enough, or messy enough
that giving it to an isolated worker with a clean brief and strong ownership is better than
trying to do it directly in the current session.
