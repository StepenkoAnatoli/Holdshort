# ADR-0002 — The task-state owner's reconcile() and watchdog reads stay a library API; production reconciliation stays in task_crosscheck

- **Date:** 2026-10-17
- **Status:** accepted
- **Area:** `tools/task_state_owner.py`, `tools/task_crosscheck.py`, `tools/live_dispatcher.py`, `tools/pilot_report.py` (the ADR-0001 migration outcome)

## Context

ADR-0001 Decision 1 gave the task-state owner "sole read path for all three
task-state stores, owning validation, reconciliation (authority wins; mirror
repaired, never lowered; watchdog state compared), and one vocabulary mapping",
staged as ① owner, ② dispatcher delegates, ③ crosscheck swaps, ④ `pilot_report`
derives.

The migration shipped ② (the dispatcher reads the authority and validates the
mirror through `owner.read()`, PR #86) and ④ (`pilot_report` maps authority
charges through `owner.authority_view()`, PR #92). Step ③'s fail-loud fix landed,
but the crosscheck swap — `task_crosscheck` delegating its per-task comparison to
`Owner.reconcile()` — was set aside for blast radius (ADR-0001 Appendix B.2) and
③ was closed as delivered (PR #91/#93).

The outcome is that `reconcile()`, `read_mirror()` and `read_watchdog()` have no
production caller: they are exercised only by `tools/test_task_state_owner.py`.
Production reconciliation is `task_crosscheck`, which computes its own
`optional-mirror-stale` comparison (`tools/task_crosscheck.py:122-128`) with the
same meaning as the owner's — the vocabulary is shared (B.2), the code is not. The
owner's watchdog comparison (`watchdog-without-authority`,
`watchdog-{attempts,repairs}-ahead`) has no counterpart in the crosscheck and no
caller at all.

That left one question open after the migration: is `reconcile()` unwired by
neglect, or by choice?

## Decision

`reconcile()`, `read_mirror()` and `read_watchdog()` are the owner's supported
library API, not a production path. They are kept, tested and available; they are
not force-wired into a caller that does not need them, and they are not deleted.
The owner's production surface stays deliberately narrow: `read()` (the
dispatcher's authority + mirror read path, ADR-0001 ②) and `authority_view()` (the
single `charged` → `spent` mapping, ADR-0001 ④). Production reconciliation stays in
`task_crosscheck`.

Two consumers are identified but out of scope here, so the surface is not dead:

- the **crosscheck swap** ADR-0001 Appendix B.2 set aside; and
- an **authoritative state-recovery procedure**, the gap ADR-0001's own
  `docs/REMAINING_BRANCH_INTEGRATION.md` names ("recovery of invalid task state
  requires an authoritative reconciliation procedure").

## Rejected alternatives

- **Wire the crosscheck to `Owner.reconcile()` now (the declined swap).** Rejected
  for the same blast radius B.2 recorded: the crosscheck works on a state
  *directory* and needs inputs the owner does not take (the ledger journal,
  accounting arithmetic, the attempt/authority cross-check), so delegating only
  the per-task comparison would split its finding set across two modules while the
  owner still could not produce the rest.
- **Delete the unwired surface (`reconcile()`/`read_mirror()`/`read_watchdog()`).**
  Rejected: ADR-0001 Decision 1 makes the owner own reconciliation, the surface is
  tested, and the state-recovery gap above is its natural consumer. Deleting it
  would re-scatter the invariant the owner exists to concentrate.
- **Force a new diagnostic/recovery CLI now, so `reconcile()` has a caller.**
  Rejected as sequencing: no such tool is scoped or requested, and inventing a
  caller to justify an API is backwards.

## Trigger to revisit

- `task_crosscheck`'s authority↔mirror comparison drifts from the owner's again,
  or a third module starts naming an authority↔mirror divergence (ADR-0001
  Appendix B.2's trigger) — then reconsider the swap.
- A state-recovery / "authoritative reconciliation" procedure (the
  `REMAINING_BRANCH_INTEGRATION.md` gap) is scheduled — then `reconcile()` becomes
  its read base and this ADR is superseded.

Formats stay frozen (ADR-0001 Decision 2): no path, field name or decision string
changes.
