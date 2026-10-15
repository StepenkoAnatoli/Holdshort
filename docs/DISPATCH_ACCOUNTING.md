# Dispatch accounting and recovery

The dispatcher now reserves work, mandatory verification cash and verification
call slots before transport. Task and pilot totals are shared across instances
and restarts. This addresses the remaining-budget and independent-instance bugs
tracked in [#47](https://github.com/StepenkoAnatoli/SmartRouter/issues/47) and
[#48](https://github.com/StepenkoAnatoli/SmartRouter/issues/48).

The implementation has been tested with synthetic transports and real local
processes. It does not establish provider qualification, final billing accuracy
or savings. Input counts still use the provider's estimate plus a 5% margin;
an unexpected overrun is recorded at known cost and stops further dispatch.
A reliable strict live billing bound remains unqualified: recording an overrun
does not prevent the first charge from exceeding its estimate.

## What is reserved

For work, the conservative call bound is the larger of the declared `work_bound`
and the priced input estimate plus the adapter's output ceiling. The dispatcher
then checks:

```text
task known spend + work reservation + task review reservation <= task cap
pilot known spend + all existing reservations + new reservations <= pilot cap
task calls used + this work call + mandatory review slots <= task call limit
```

Equality passes. Deadlines still require time strictly before expiry. A work
call cannot consume another task's reserved cash or any call slot held for
verification. Later work cannot reduce the current task's review reservation by
supplying a smaller review bound. All physical sends, including verification,
consume an attempt before transport. Same-profile repair credits apply to work,
not to a separate verification call.
Each transport invocation must represent one model send. Adapters must expose
retries as separate attempts; hidden transport retries are unsupported.

`review_calls` defaults to one when the work call has a positive `review_bound`,
otherwise zero. Set it explicitly for multiple model checks, zero-priced model
checks, or local checks that require no model call. A local check can use the
host's acceptance process without a model dispatch. The host must declare the
complete required verification plan and run its checks.

## Default HTTP adapter

The default adapter uses its own HTTP opener and refuses redirects before a
credential-bearing request can be forwarded. It does not follow a redirect even
when the original endpoint was approved. The configured `timeout_s` must be a
finite, positive number and is passed to both the token-count and model-send
transports. This is an HTTP timeout, not proof of an end-to-end task deadline or
that a timed-out provider request incurred no charge. Custom transports remain
responsible for their own destination and timeout behavior.

## Persistent authority

With a ledger at `.local/pilot/ledger.jsonl`, the authority is stored at
`.local/pilot/ledger.jsonl.budget.sqlite3`. It persists even without `--task-store`.
Use the same ledger path for the entire pilot. An optional task store holds JSON
mirrors and binds that directory to one pilot authority; switching its ledger or
changing the authority's caps refuses execution rather than resetting counters.

SQLite `BEGIN IMMEDIATE` transactions coordinate local processes. The lock is
released before transport, so different tasks can run concurrently when their
combined reservations fit. The authority commits the attempt and reservation
before transport. The append-only JSONL ledger is a mirror of its durable event
journal, with matching reservation IDs on reservation and settlement records.
Prompts, provider keys and exception contents are not included in these events.

Keep the database, ledger and optional task-state directory together. The
database files are ignored by Git. This is coordination on one local filesystem;
it is not a distributed budget service for multiple machines or network shares.

## Execute verification and finish a task

Work and verification use the same dispatcher and pilot identity. For a model
verification call, set `purpose="verification"`, supply its conservative
`work_bound`, and set `review_bound=0`. It consumes this task's owned review
cash and one reserved review slot; it does not reserve that same cash again.

```python
work = dispatcher.attempt(
    "task-001", "cloud-C", work_request,
    work_bound=0.05, review_bound=0.02, review_calls=1,
)
if work.decision == "dispatched":
    review = dispatcher.attempt(
        "task-001", "cloud-C", verification_request,
        work_bound=0.02, review_bound=0, purpose="verification",
    )
    # The host examines the result and runs the task's acceptance checks.
    if review.decision == "dispatched" and host_acceptance_passed:
        dispatcher.complete_verification(
            "task-001", evidence_ref="path/to/acceptance-receipt.json",
        )
```

This is an integration sketch, not a runnable live-provider example. The host
supplies the dispatcher, requests and verified acceptance result. Completion
requires an evidence reference, releases unused review reservations, and marks
the task terminal. It preserves spent cash and attempts and refuses further
execution under that task ID. A returned model response alone does not complete
verification. These actions run autonomously; no human approval is introduced.

The CLI also accepts `--purpose verification` and `--review-calls`. Completion
and receipt reconciliation are host APIs, so a standalone CLI send does not
automatically release required verification budget.

## Failed sends and uncertain usage

| Observation | Durable result |
| --- | --- |
| A count request fails before reservation | No model send or attempt is consumed. The error propagates. |
| Transport returns valid complete usage | Settle the work reservation to known modeled cost; retain remaining review budget. |
| Transport raises with complete usage in `DispatchFailure` | Record a failed physical attempt and settle its known cost. |
| Usage is absent, malformed or partial | Record `dispatch-error` with `cost_usd: null`, retain the unaccounted reservation, and stop further pilot sends. |
| Partial usage has independently known cost | Preserve a conservative known-cost subtotal in `known_cost_usd`; keep the remaining reservation. Reconciliation adds only the difference. |
| A process exits during transport | Its pre-send attempt and reservation remain pending with unknown usage. No restart treats them as free. |
| Known cost exceeds the reservation | Record actual modeled cost and stop the pilot; do not replace it with a zero-cost rejection. |

The real adapter refuses missing or invalid usage fields instead of converting
them to zero. A timeout does not prove that the provider did no work. The host
can reconcile a retained reservation only after it verifies a complete provider
receipt and knows that the transport has finished:

```python
dispatcher.reconcile_dispatch(
    "task-001", reservation_id,
    input_tokens=verified_input_tokens,
    output_tokens=verified_output_tokens,
    evidence_ref="path/to/provider-receipt.json",
    transport_finished=True,
)
```

The reservation ID must match. A duplicate settlement or a receipt below the
already known cost is refused. Reconciliation preserves the original attempt
count and uses the profile rates captured at reservation time. It can clear an
unknown-usage stop after all uncertain sends are settled. A recorded overrun
remains a pilot stop. Evidence verification belongs to the host; this API does
not authenticate a provider receipt from its path alone.

## Corruption, old ledgers and reporting

A committed journal suffix missing from the JSONL mirror is replayed before
further execution. A partial tail, divergent ledger, corrupt authority, changed
caps, or corrupt task mirror is preserved and blocks sends. Do not delete these
files, rename the pilot or clear counters to make a blocked send run.

An older nonempty ledger or task store without this authority is **unreconciled**.
The dispatcher refuses it instead of guessing that historical sends and
verification obligations are complete. Preserve its evidence and reconcile the
pilot through a host migration that accounts for prior spend, attempts, required
verification and uncertain requests. This change does not automatically migrate
or rewrite historical ledgers. A newly authorized pilot may use a separate
identity and allowance; that does not continue or erase an old task's budget.

`pilot_report.py` counts a reservation and its final settlement once. Unknown
usage produces `GAPS_FOUND`, `total_spend_complete: false`, and explicit reserved
cash. `total_spend_usd` is the known subtotal when that flag is false, not a
complete charge. `pilot_close.py` subtracts retained reservations from headroom
and waits for verification completion on new journaled tasks. The live-fill
importer reports unknown usage without filling a completed measurement slot.
Malformed token counts, nonfinite or negative costs, inconsistent reservation
histories, and invalid required fields refuse an `intact` verdict. Fractional
token counts are not rounded into valid evidence. A physical send with null
usage stays unknown even in a historical ledger; it does not become a zero-cost
observation. Historical source records remain unchanged.

## Evaluation sheets and source consistency

The version 2 live-fill sheet contains 20 category cells and **80 observation
slots: 20 per arm**. Each of the five category columns has positions for two
distinct assigned tasks, with two repeats per task. The importer checks the
repeat limit, assignment to a cell, fixed-profile arm, configured token cost,
and source ledger identity before counting an observation as measured. Missing
required values do not satisfy the completion rule.

Recorded observations carry a source fingerprint tied to their ledger line.
Repeated imports and pilot close reconcile those identities and add newly
appended observations once. Changed, missing, or superseded source evidence is
reported for reconciliation. These fingerprints detect consistency changes;
they do not authenticate provider receipts, model outputs, or acceptance.

Invalid prior recorded sheets are retained for reconciliation. They are not
silently upgraded, cleared, or recounted as valid version 2 evidence. Preserve
the original sheet and ledger before preparing a replacement.

Sheet capacity is separate from evaluation readiness. The ratified Phase 3 pool
has five tasks and two repeats per task, giving only **10 observations per arm**
against its minimum of 20. Before a live trial, a qualified prospective task pool
must supply the missing distinct tasks while preserving representative coverage
and the tuning/holdout split. Extra slots do not amend or complete the protocol.
See the [sampling caveat](PHASE4_PILOT_REPORT.md#8-live-sampling-plan--how-each-matrix-cell-fills-with-measured-observations-row-4-start)
and [audit follow-ups](GAP_AUDIT_FOLLOWUPS_2026-10-15.md).

## Reproduce the evidence

Run from the repository root:

```bash
python tools/test_dispatch_budget.py
python tools/test_live_dispatcher.py
python tools/test_task_persistence.py
python tools/run_regression.py
```

The budget suite covers full-cap equality, protected verification cash and call
slots, independent instances, two competing processes at the send boundary,
a process exiting during transport, unknown and partial usage, known failed
sends, overruns, receipt reconciliation, journal/mirror crash recovery, corrupt
or missing authorities, and reporting. All inputs and transports are synthetic;
these checks make no provider requests. The original review findings and frozen
model comparison evidence remain historical records.
