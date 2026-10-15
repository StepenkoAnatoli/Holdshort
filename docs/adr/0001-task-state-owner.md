# ADR-0001 — Task state gets a single in-repo owner module; on-disk formats stay frozen because agent hosts read and write them

- **Date:** 2026-10-15
- **Status:** accepted
- **Area:** `tools/task_persistence.py`, `tools/dispatch_budget.py`, `tools/host_watchdog.py`, `tools/task_crosscheck.py`, `tools/live_dispatcher.py`, `tools/pilot_report.py`, and the (not-yet-created) task-state owner module

## Context

The architecture review of `main @ 23d79da` (2026-10-15) found "task state" scattered
across six modules: the SQLite budget authority (`dispatch_budget.py:64-99`, fields
`attempts`, `repairs`), the JSON mirror (`task_persistence.py:40`, fields `spent`,
`repairs`), the watchdog's private state (`host_watchdog.py:57-83,130-179`, field
`repairs_used`), a reconciling reader inside `live_dispatcher.py:164-182`, a raw
reader in `task_crosscheck.py:35-46` that swallows corruption and contradicts the
store's documented fail-closed G5 rule (`task_persistence.py:20-24`), and derived
views in `pilot_report.py`. The external issue tracker already bills for this
area: issues #75-#83 (all found "while reviewing #72") cluster in dispatch/budget
semantics, including #81 (task_crosscheck ignores the budget authority) and #76
(send outcome lost when settlement cannot reach the authority).

Two facts constrain any fix. First, the dual truth (authority + mirror, PR #72) is
evolutionary, not deliberate — the owner confirmed consolidation is welcome.
Second, and decisively: the "host" is GPT and Claude agent tooling that **reads and
writes the task-state JSON files directly**, following the prose in
`host-hil-policy.md` and the runbooks. `spec-v2.md:175` keeps the skill stateless
and `host-hil-policy.md:32` calls state files a host convention — so the file
bytes plus the prose that tells agents how to write them are a published contract
with consumers the repo cannot see or change atomically.

## Decision

1. **One owner module, read side first.** A new in-repo module becomes the sole
   read path for all three task-state stores, owning validation (G5 fail-closed
   exactly where it exists today), reconciliation (authority wins; mirror repaired,
   never lowered; watchdog state compared), and one vocabulary mapping
   (`repairs` &#8596; `repairs_used`, `spent` &#8596; `charged`). Constructed with
   explicit paths; no globals.
2. **On-disk formats are frozen.** No path, field name, or decision string
   (`blocked:*`, `KNOWN_DECISIONS`) changes — agent hosts keep writing and reading
   exactly what they write and read today, and every read tolerates foreign
   (agent-written) state.
3. **One deliberate behavior change:** `task_crosscheck` stops swallowing corrupt
   state (`task_crosscheck.py:39-43`) and fails loud, matching the store's own G5
   rule. It lands as its own commit with its own tests.
4. **Staged migration, one safe commit at a time:** wait for open PRs #73/#74 to
   land; ① owner + hermetic tests, imported by nothing; ② `live_dispatcher`
   delegates behind the existing `_task` shim; ③ crosscheck swaps (the behavior
   fix); ④ `pilot_report` derives via the owner. Every commit passes the gate
   alone. Write-side routing (v2) is a separate later decision after soak.

## Rejected alternatives

- **Merge the watchdog state into the authority/mirror and delete `repairs_used`.**
  Rejected: agent hosts read and write those files by name; renaming fields or
  removing a store is an external-contract change the repo cannot make atomically
  with two prose-following hosts. The vocabulary divergence is instead absorbed by
  the owner's mapping.
- **Delete the JSON mirror entirely (single store).** Rejected for the same
  contract reason: the mirror has host-facing readers/writers outside the repo's
  control. With formats frozen, deleting it was not on the table; the owner makes
  the dual truth cheap instead of visible.
- **v2 immediately: route the repo's own writes through the owner in the same
  change.** Rejected as sequencing, not in principle: PRs #73/#74 were editing the
  same six files the day this decision was taken, and write-routing touches the
  hot dispatch path. v1 ships first, soaks, and v2 earns its own decision.
- **Keep `task_crosscheck`'s swallow-corruption behavior (pure, byte-identical
  refactor).** Rejected: the swallow contradicts the store's documented rule and
  is the mechanism behind #81-class false alarms; keeping a known contradiction to
  save one commit would re-scatter the very invariant the owner exists to
  concentrate.

## Trigger to revisit

- PRs #73/#74 (or their successors) rewrite the state layer so the owner
  duplicates new logic — re-shape before step ②.
- Real agent-written state files from actual GPT/Claude runs fail the owner's
  validation in a way that would false-reject a live task — the owner must never
  brick a host's task; fail-open to today's behavior where the store is not
  already fail-closed.
- Any external host tool needs a format change — this ADR's freeze is then
  explicitly reopened, host prose updated in the same change, and the two agent
  hosts re-instructed before the bytes change.
- v2 (write-side routing) is proposed after v1 soaks — a new decision, not an
  amendment here.

## Appendix A — Step ② plan (as executed; realized in PR #86)

The migration order in the Decision (① owner, ② dispatcher delegates, ③
crosscheck swaps, ④ `pilot_report` derives) was planned in detail before any
dispatcher code changed. This appendix records that plan and its outcome, so a
future reader can re-run or undo it.

### Gate (re-verified 2026-10-15, before proceeding)

- PR #73 (draft): tests only (`test_dispatch_adapter.py`, `test_live_dispatcher.py`).
  Does not touch `live_dispatcher.py`.
- PR #74: `host_watchdog.py` (+92/-13), `run_regression.py` (+1), plus docs and
  other tools. Does not touch `live_dispatcher.py`.
- The **in-flight local work** staged on `codex/close-gap-audit-findings` **does
  rewrite the state layer**: `live_dispatcher.py` +173, `dispatch_budget.py`
  +198, `task_crosscheck.py` +88. This is the "Trigger to revisit" condition, so
  step ② was written as a **draft stacked on step ①** and must be rebased (and
  re-shaped if that work has already consolidated reads) before merge.

### Shipped shape (PR #86, base `feat/task-state-owner-step1`)

Two commits, each gate-green alone:

1. **owner — one mapping.** `tools/task_state_owner.py`: hoist the authority
   `charged` → shared `spent` conversion into `authority_view(task)`; `read()`
   returns it. `deepcopy` is kept (matching `_remember`'s original semantics —
   the cached/persisted view must share no mutable structure with the authority
   document); the value stays byte-for-byte the float the mirror already persists.
2. **dispatcher — delegate.** `tools/live_dispatcher.py`: construct a read-only
   `TaskStateOwner` in `__init__` (mirror wired; **no watchdog path** — the
   dispatcher never read watchdog state and v1 does not change that).
   `_remember()` calls `authority_view()`. `_task()` delegates the read to
   `owner.read()` and keeps only **creation** (a write) locally, preserving the
   corrupt-mirror G5 refusal and the legacy-counters `BudgetStateError` guard.
   No call sites change (`_reject`/`_record`/`_reserved_attempt`/
   `reconcile_dispatch`/`complete_verification`/`abandon_task` still call
   `_task`/`_remember`).

Tests: `tools/test_task_state_owner.py` grew 6 wiring tests (single mapping,
absent-task creation, G5 through `_task`, counters-without-authority refusal,
mirror kept current). Verified 20/20; neighbours `test_live_dispatcher`,
`test_task_persistence`, `test_task_crosscheck`, `test_dispatch_budget`,
`test_pilot_report` all exit 0; full regression gate PASS on both commits.

### Kill re-check after ②

- Dispatcher suite flakiness.
- Real agent-written mirror files false-rejecting (the mapping is byte-identical,
  so any difference is a real regression, not a rounding artefact).
- Out of scope: write/init routing (owner stays read-only) and step ③.

