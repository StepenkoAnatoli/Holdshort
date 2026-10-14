# Reservation accounting comparison fixtures

These ten synthetic cases form five pairs for checking whether a model reasons
correctly about reservations. Every pair changes exactly one input fact. They
are new examples prepared after the exploratory
[model policy pilot](MODEL_POLICY_PILOT_2026-10-14.md); no model has been evaluated
on this set as part of this contribution. Once published, they are public
regression examples. A future claim about unseen performance requires new,
withheld cases and a frozen trial protocol.

The [input packet](../tests/fixtures/reservation-comparison/cases.json) contains
all assumptions and the requested response schema. The
[answer key](../tests/fixtures/reservation-comparison/answer-key.json) is a
separate static file. Give contestants only the input packet in an environment
that cannot access the key, audit test or this guide. File separation alone
does not hide an oracle from a model with repository access.

## Arithmetic contract

All prices are synthetic USD decimal strings. All reservations have an explicit
owner. Reservations are disjoint and unspent; a current-task reservation covers
the exact plan in the case. There are no hidden checks, overheads or reservations.
The fixture defaults supply permission, capability, verification, deadline,
pricing and accounting facts so the intended decision turns on Gate 4.

Calculate the following with decimal arithmetic:

```text
free_cash = cash_cap - settled_cash - all cash reservations
all_in_bound = work_bound + mandatory_verification_bound
additional_cash = max(0, all_in_bound - current task's cash reservations)
additional_calls = max(0, planned_calls - current task's reserved slots)
prospective_calls = used_calls + all reserved slots + additional_calls
```

`free_cash` always means globally unreserved cash. An existing reservation does
not increase it when its owner changes. Ownership changes whether the current
plan needs another reservation. `planned_calls` includes mandatory verification.
The prospective count includes other tasks' reservations as well as this task's.

Gate 4 requires sufficient new cash and call headroom. Equality passes, following
the [canonical gate](../skills/smart-router/references/gates.md). The proposal's
declared bound must cover the mandatory work and verification sum; a proposal
that omits verification fails even if the corrected sum would fit. Accepted
cases route `direct`; rejected cases route `blocked` at Gate 4. These cases
exercise arithmetic and proposal validation, not all five routing gates.

## Paired decisions and reasons

| Pair | Single changed fact | Expected decision and reason |
| --- | --- | --- |
| `cash-owner` | Cash reservation owner changes from `task-b` to `task-a`. | Other owner: **blocked, Gate 4**, because $0.04 of new cash is needed and free cash is $0.00. Current owner: **direct**, because the existing $0.04 reservation fully covers the bound; new cash needed is $0.00. Free cash stays $0.00 in both cases. |
| `call-owner` | Two reserved call slots change owner from `task-b` to `task-a`. | Other owner: **blocked, Gate 4**, because 1 used + 2 reserved + 2 new = 5 exceeds the limit of 3. Current owner: **direct**, because no additional slots are needed and the prospective count is exactly 3. |
| `cash-boundary` | Cash cap decreases by one cent, from $0.10 to $0.09. | Exact: **direct**, because $0.05 work + $0.01 verification equals $0.06 free cash. Overrun: **blocked, Gate 4**, because the same $0.06 bound exceeds the remaining $0.05 by one cent. |
| `call-boundary` | Planned calls increase from 2 to 3. | Exact: **direct**, because 1 used + 2 new = the limit of 3. Overrun: **blocked, Gate 4**, because 1 + 3 = 4 exceeds it by one call. |
| `verification-omission` | The proposed bound drops from $0.06 to $0.05. | Included: **direct**, because $0.05 work + $0.01 required verification fits $0.06 headroom. Omitted: **blocked, Gate 4**, because the proposal leaves out required verification. The true all-in bound stays $0.06 in both cases. |

## Replay and validate

From the repository root, run the independent fixture audit:

```bash
python tools/test_reservation_fixtures.py
```

The audit recalculates every expected field from input facts using `Decimal`,
checks that each pair differs in exactly one leaf, and validates owner records.
It also changes each numeric answer while keeping the route correct and proves
the scorer detects the mismatch. Missing, duplicate and unknown IDs, invalid
numbers and malformed evidence are refused.

Save a contestant's JSON response under `.local/`, then score it:

```bash
python tools/score_reservation_fixtures.py --responses .local/reservation-trial/response.json
```

The response envelope is `{"schema_version": 1, "answers": [...]}`. Each answer
contains `id`, `route`, `first_failing_gate`, the three cash fields above as
decimal strings, and the two call fields as integers. Answer order is irrelevant.
Cash representations such as `"0.06"` and `"0.0600"` compare equally.

The scorer reports matching cases and each mismatched field. Exit `0` means all
seven scored fields match for all ten cases; `1` means a valid response contains
wrong answers; `2` means malformed or unreadable evidence. Replaying the key
itself is a scorer smoke check, not a model trial:

```bash
python tools/score_reservation_fixtures.py --responses tests/fixtures/reservation-comparison/answer-key.json
```

The audit joins the complete `tools/run_regression.py` gate. These local checks
make no model or provider calls, change no ratified historical ledgers, and do
not establish model qualification, savings or production budget enforcement.
The dispatcher gaps in the [engineering review](SMARTROUTER_USAGE_REVIEW_2026-10-13.md)
need separate runtime fixes.
