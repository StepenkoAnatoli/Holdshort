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

## Appendix B — Re-shape trigger fired before step ③ (2026-10-15)

Decision #3 (crosscheck stops swallowing corrupt state; step ③) was **not built
on `main`**. It was already implemented — differently — by the in-flight
state-layer work staged on `codex/close-gap-audit-findings` (unpushed at the
time). Building step ③ on `main` would have duplicated and competed with it, so
the "Trigger to revisit" ("rewrite the state layer so the owner duplicates new
logic — re-shape") fired and step ③ was **held**.

### What the in-flight work already does

- `task_crosscheck.check_authority()` inspects the budget authority through a new
  **`dispatch_budget.read_authority()`** and emits reconciliation findings:
  `journal-divergence`, `mirror-lag`, `accounting-gaps`, `unsettled-reservation`,
  `optional-mirror-stale`, `authority-attempt-mismatch`. That is the #81 fix
  (crosscheck consults the authority, not only the ledger).
- `task_crosscheck.state_view()` now records an `invalid-task-mirror` finding
  instead of silently skipping a corrupt file, and drops the second unvalidated
  fallback. That is decision #3's fail-loud intent, delivered as a finding rather
  than a raised exception.
- `dispatch_budget.py` gains a side-effect-free `read_authority()` plus a
  locking/lease/receipts layer (`_lock`/`_unlock`, `lease`, `write_receipt`,
  `_recover`).

### Re-shape plan (after that work lands)

1. **`owner.read()` builds on `read_authority()`.** Today the owner reads via
   `BudgetStore.transaction()`, which rewrites the authority row on every read;
   `read_authority()` is side-effect-free. The owner should use it — a strictly
   better v1 than the one shipped in step ①/②.
2. **One finding vocabulary.** `task_crosscheck` consumes `Owner.reconcile()` (or
   the owner adopts the crosscheck's finding kinds) so authority↔mirror
   disagreement is named once, not in two modules.
3. **Delete the dead code** the in-flight change left in `task_crosscheck.py`:
   `state_view_file_guess` and the now-unused `_sanitize` import.

### Status

- Step ② (PR #86) remains a **draft**, pending a rebase on the in-flight
  `live_dispatcher.py`.
- Step ③ is **held** until the in-flight state-layer work lands, then re-shaped
  per the plan above (most likely folded into the owner rather than a second
  crosscheck implementation).
- On-disk formats stay frozen; appendices A and B change no format.

## Compatibility amendment — accounting correctness fixes, 2026-10-16

The separately authorized known-finding fixes for #75–#83 require an additive
accounting extension. Decision 2's freeze remains the rule for the read-owner
migration, with this explicit exception for those runtime correctness fixes:
canonical `task-abandoned` and `blocked-abandoned` events, optional task
`abandoned` (legacy absence means false), optional settlement/mirror status and
transport timestamps, and a `<not-dispatched>` event profile for zero-send
abandonment. Existing paths, field names and decision meanings are preserved.
`dispatch-unsettled` is a returned recovery observation only; it is not a
canonical journal decision and does not extend `KNOWN_DECISIONS`.

The exact defaults and old-reader stop behavior are published in
[Dispatch accounting — host compatibility amendment](../DISPATCH_ACCOUNTING.md#host-compatibility-amendment--2026-10-16)
and linked from the host policy. Matching tools and instructions must be deployed
together; hosts must reload the instructions before resuming. This amendment
introduces no automatic migration, new approval checkpoint, or reset of prior
charges. Appendix B's #86 reshape remains held until the accounting fixes land
and adopts their read-only snapshot path. It does not own these runtime changes.

## Appendix B.2 amendment — re-shape landed; finding vocabulary chosen (2026-10-16)

The accounting fixes above have landed (`main @ b924cdb`, PR #88), releasing the
Appendix B hold, so `#86` was **rebuilt on merged `main`** rather than rebased.
All three re-shape items are done, plus two correctness fixes found on the way:
the `_task` create path now re-checks existence **inside** the creation
transaction (a check-then-create race could otherwise erase a concurrent
creator's counters), and a task-id collision — the lossy `a/b` vs `a_b`, or
`Task-A` vs `task-a` on a case-insensitive filesystem — is detected by the
**stored** `task_id` and refused (`TaskIdCollision(CorruptState)`), leaving the
outward `blocked:state-corrupt` string byte-identical.

1. `owner.read()` uses `dispatch_budget.read_authority()` (the side-effect-free
   snapshot); the absent-authority path reuses the read-only initial view and
   returns `None` **without writing**. No read mutates the authority.
2. The finding vocabulary is unified — decision below.
3. `task_crosscheck.state_view_file_guess` and its now-unused `_sanitize` import
   are deleted, with a regression test that a corrupt mirror carrying no ledger
   task still yields an `invalid-task-mirror` finding.

### Decision (Appendix B item 2)

The owner **adopts the crosscheck's finding kinds**; `task_crosscheck` is **not**
restructured to delegate to `Owner.reconcile()`.

- Owner findings carry the crosscheck's shape `{"task_id", "kind", "detail"}`.
- The authority↔mirror divergence is named **`optional-mirror-stale`** in both
  modules, with the crosscheck's condition (any difference, `!=` — a *lagging*
  mirror is reported, not only one that is ahead). The owner-local
  `mirror-ahead-of-authority` is retired.
- Kinds the crosscheck has no counterpart for stay owner-local: the watchdog
  comparisons (`watchdog-without-authority`, `watchdog-{attempts,repairs}-ahead`)
  and `mirror-without-authority`.

### Rejected alternative

**`task_crosscheck` consumes `Owner.reconcile()`** — the direction Appendix B
called "most likely". Set aside for now, not because it is wrong but because of
its blast radius: the crosscheck's remaining findings need inputs the owner does
not take — the ledger journal (`journal-divergence`, `mirror-lag`), accounting
arithmetic (`accounting-gaps`, `unsettled-reservation`) and the attempt/authority
cross-check (`authority-attempt-mismatch`). Delegating only the per-task
comparison would split the crosscheck's finding set across two modules while the
owner still could not produce the rest. Sharing the *names* achieves "one
vocabulary" at a fraction of the churn, and leaves the held step ③ (crosscheck
swaps) available as its own change.

**Trigger to reopen:** a third place names an authority↔mirror divergence, the
owner's comparison drifts from the crosscheck's again, or step ③ is scheduled —
then revisit whether the crosscheck delegates its per-task check to the owner.

> **Status note:** the "held step ③ (crosscheck swaps) available as its own
> change" left open above was later closed as delivered — see "Step ③ status"
> below. Its "step ③ is scheduled" reopen trigger can no longer fire; the other
> two triggers stand.

Formats stay frozen: findings are in-memory reports, never written to task state;
no path, field name or decision string changes.

### Step ③ status — closed as delivered (2026-10-16)

Decision #3's fail-loud behaviour fix is delivered: `task_crosscheck.state_view()`
emits an `invalid-task-mirror` finding (never a silent skip), the second
unvalidated fallback and `state_view_file_guess` are gone, and delegating the
crosscheck to `Owner.reconcile()` stays declined (above). With the vocabulary
unified in B.2, the staged-migration item ③ ("crosscheck swaps") is closed as
delivered, superseding B.2's "held step ③ (crosscheck swaps) available as its own
change" and retiring its "step ③ is scheduled" reopen trigger.

Migration item ④ (PR #92) also landed, but it wires `pilot_report` to the owner's
`authority_view` — the single `charged` → `spent` mapping — **not** to
`reconcile()`. `reconcile()` therefore still has no production consumer: it is
called only from `test_task_state_owner.py`, so the owner's reconciliation half
remains unwired in production. That is recorded here as an open item, not claimed
as delivered. `task_state_owner.py`'s stale "step 3 retires `task_crosscheck`'s raw
reader" note is corrected to match.


