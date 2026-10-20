# Example: When to Use Isolation

**Status:** worked example — non-normative. The normative contract is [gates.md](gates.md)
(fixture-pinned) and [spec-v2.md](spec-v2.md); where this example and the normative files
ever disagree, **the normative files win**. Flagged, not fixed: the decision block below is
abbreviated (a real decision must also contain `NestedAllowed`, `MaxNestingDepth`,
`Reservations`, `Calls`, `Deadline` and `Uncertainty` — the last one is never omitted, since
an unpriced fee must never be hidden), and `Profile` is shown as a model label where §9
requires the full identity tuple.

## Scenario

You give the system this task:

> "Implement a new caching layer for the product catalog. It should support Redis and
> in-memory backends, update the configuration system, and add comprehensive tests. Do not
> touch the payment or order modules."

## Why isolation is required

This task has several risk factors that trigger stronger isolation:

- **Multi-file / multi-module change** — touches caching, configuration, and tests.
- **Non-trivial blast radius** — a mistake could affect performance or correctness across
  the catalog.
- **Needs clean verification** — tests must run against only this change, not mixed with
  other work.
- **Likely to run in parallel** — other workers or the main session may be editing different
  parts of the codebase at the same time.

Because of these factors, Holdshort recommends isolation instead of letting the work
happen in the shared working tree.

## Typical decision output

```
Difficulty:        high-or-ambiguous
Route:             delegate
Profile:           claude-sonnet-4
Isolation:         worktree+branch
IsolationReason:   multi-module change with shared-state risk and need for clean test runs
Owner:             worker
HumanGate:         review-before-merge
```

## What the Host does

1. Creates a dedicated git worktree + branch (e.g. `sr/a3f9/caching-layer`).
2. Injects the exact Brief into that worktree.
3. Starts the chosen profile inside the isolated environment.
4. Runs all verification only inside that worktree.
5. Returns feedback (test failures, review comments) to the same worker.

Full host-side flow, with example commands and pseudo-code:
[host-worktree-flow.md](host-worktree-flow.md) (agent-focused variant:
[host-worktree-agents.md](host-worktree-agents.md)).

## When isolation is *not* needed

- Single-line docstring or comment change
- Purely read-only analysis
- Tiny, low-risk edit in one file with no parallel work happening

In those cases Holdshort will normally choose `Isolation: none` and keep the work in the
current session.

**Summary:**
Use isolation whenever the change is large enough, risky enough, or concurrent enough that a
shared working tree could cause collisions, dirty test results, or accidental side-effects.
The most common and recommended form is `worktree+branch`.
