# Dispatch accounting and recovery

The dispatcher now reserves work, mandatory verification cash and verification
call slots before transport. Task and pilot totals are shared across instances
and restarts. This addresses the remaining-budget and independent-instance bugs
tracked in [#47](https://github.com/StepenkoAnatoli/Holdshort/issues/47) and
[#48](https://github.com/StepenkoAnatoli/Holdshort/issues/48).

The implementation has been tested with synthetic transports and real local
processes. It does not establish provider qualification, final billing accuracy
or savings. The real adapter now requires an explicit qualification record and
uses a provider-enforced input ceiling for modeled token reservations. Injected
estimate-only transports retain their documented 5% margin and carry their own
qualification responsibility. An unexpected overrun is recorded and stops
dispatch. No unconditional final provider-bill guarantee is established.

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

### Billing qualification

`tools/live_billing_qualification.json` is deliberately unqualified. The default
real adapter refuses before key lookup or network access until the host supplies
a valid record using `--billing-qualification`. A record binds the approved
endpoint, exact model/profile mapping, standard global plaintext request mode,
price revision and file hash, validity interval, and provider-enforced input and
output token ceilings. Local captured evidence must cover provider limits,
rates, and request scope; its paths and hashes are checked on every count/send.
Updating the record requires rebuilding the adapter. A stale dispatcher price
snapshot also refuses execution.

The request pins standard service, global inference, and nonstreaming output.
Unexpected response model, cache/tool usage, billing modifiers, or malformed
usage cannot settle as ordinary two-counter spend. They remain unknown. A count
is checked against the qualified ceiling; it does not prove that ceiling.
Captured evidence hashes establish consistency, while the trusted host remains
responsible for the evidence's truth and applicability. The scope is explicitly
`modeled-request-tokens`, with `final_bill_guaranteed: false`.

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

Keep the database, ledger, its `.budget.sqlite3.recovery` directory, and optional
task-state directory together at their pinned absolute paths. Relative CLI paths
resolve against the repository root, so changing the working directory cannot
create a fresh allowance. Moving a pilot requires deliberate reconciliation;
path/cap/binding changes refuse execution rather than resetting counters. The
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

A failed verification still consumes its physical attempt. Once its usage is
settled, an available attempt and retained review cash can support retrying the
required check without buying another work call. A refusal keeps
`purpose: verification` in its journal record.

The host can close an unsuccessful or expired task with
`dispatcher.abandon_task(task_id, evidence_ref="path/to/failure-evidence")`.
This requires no unresolved reservation, preserves spent cash and attempts,
releases unused review cash/call slots, and records terminal `task-abandoned`.
Reports label it `abandoned`, never completed. A different task halting the pilot
does not prevent recording this task's already verified completion.

## Failed sends and uncertain usage

The SQLite commit and its derived JSONL append are distinct outcomes. If the
authority commits but the mirror append fails, the returned result retains the
committed decision, reservation ID, usage, and cost, with `mirror_status: pending`.
A completed send is never relabeled as a pre-send refusal because its mirror is
behind.

After transport, a reservation-bound recovery receipt is flushed before
settlement. It contains accounting metadata, not the prompt or key. If settlement
cannot reach the authority, `dispatch-unsettled` retains the observed usage and
reservation ID. This is a **return-only observation**, not an authoritative
journal event. Preserve it as recovery evidence; never append a returned result
to the canonical JSONL yourself. Recover the matching reservation instead of
starting another attempt. The next successful authority transaction replays each receipt
once before admitting another send. A kernel-owned lease identifies a running
transport; process death or a finished transport with no settled receipt leaves
an uncertain reservation and stops admission. This preserves concurrent running
transports while refusing to treat an orphan as free allowance. If receipt
storage fails too, known in-memory evidence is still returned and the retained
reservation requires reconciliation. An explicit new `attempt` is not a request
idempotency key; hosts must use the returned reservation identity when recovering.

### Host compatibility amendment — 2026-10-16

The correctness fixes for issues #75–#83 intentionally extend the accounting
contract. They are separate from ADR-0001's read-owner migration; deploy the
matching dispatcher, report, crosscheck, tally, and host instructions together.
Existing paths, field names, and decision meanings remain unchanged.

| Addition | Meaning and compatibility rule |
| --- | --- |
| `task-abandoned` | Canonical terminal event: release unused verification allowance, retain attempts and charges, and never claim acceptance. |
| `blocked-abandoned` | Canonical refusal: an abandoned task cannot resume. |
| Task `abandoned` flag | Optional boolean; absence in an older authority means `false`. Never remove or reset a true value to resume work. |
| Event profile `<not-dispatched>` | Used only for abandonment before any physical send; zero usage and zero cost. It is a sentinel, never a dispatchable model profile. |
| `settlement_status` | Optional returned/event metadata: `committed` or `unsettled`; null/absence makes no additional durability claim. |
| `mirror_status` | Optional return metadata: `synchronized` or `pending`; null/absence is unspecified. A pending mirror does not mean the send failed to happen. |
| `transport_started_at`, `transport_finished_at` | Optional observed timestamps. Null/absence means latency was not measured; timestamp spacing between events is not transport latency. |
| `dispatch-unsettled` | Return-only observation with the original reservation identity and any known usage. Not part of `KNOWN_DECISIONS` for canonical journals; recover, do not append or blindly resend. |

Older readers that do not understand a canonical terminal event must stop with
an unknown-contract finding. They must not coerce it into completion, zero
spending, or permission to retry. Preserve optional metadata when copying
records. A host updating this checkout must load these instructions before
resuming a persisted pilot. No new human approval checkpoint is introduced.

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

The historical five-task pool could supply only 10 observations per arm. The
prospective amendment in Phase 3 §13 now supplies ten locally checked fixtures
and a pinned 80-trial schedule. `python tools/eval_pool.py plan` produces the
complete assignments map. Imports of that map bind the sheet to the pool and
schedule hashes, distinguish fixture identity from each execution's budget task
ID, preserve its split/repeat assignment, and check execution order. A repair or
verification call cannot masquerade as another independent repeat. Legacy maps
remain readable but are explicitly not bound to this prospective plan.

Actual transport start/finish timestamps determine `latency_s` when available.
Missing timing remains `not_measured_transport_latency`; the separate
`inter_observation_interval_s` is never presented as transport latency.
Reconciliation retains original execution timing instead of measuring the host's
wait for accounting evidence. Local fixture checks establish task contracts;
they do not qualify live models or provide model-performance measurements.
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
