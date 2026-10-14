# Repeated model-policy stress comparison — 14 October 2026

This follow-up compares three requested GPT profiles on a frozen synthetic packet.
It also records real repository bug probes and the fixes made after the runs.
It is a descriptive experiment, not a production qualification or a savings claim.

## Protocol and evidence

The packet and answer key were frozen at `2026-10-14T08:11:38.666582Z` against
revision `9e1411ad6acd39f7d90f02b0f130a0535f402596`, before contestants ran.
Each requested model received two fresh contexts at Medium reasoning effort:
`gpt-6-luna`, `gpt-6.1-sol`, and `gpt-6-astra`. There were six runs in total,
without feedback, repairs, or selective retries. Round two used a fixed shuffled
case order. Order effects and ordinary run variation cannot be separated here.

Each packet contained 18 policy tasks and six small Python traces. The policy
tasks cover earliest failing gates, explicit ownership of reservations, disjoint
cost components, proposal validation for delegation/escalation/speculation,
and explicit versus absent human checkpoints. Positive proposals validate supplied
conditions; they do not establish a uniquely optimal routing recommendation.
The code traces describe the frozen baseline, including unsafe behavior. Their
expected answers remain unchanged after code fixes.

The [evidence directory](evidence/2026-10-14/model-policy-stress/) contains the
protocol, packets, separate answer key, six original responses, deterministic
scorer, and before/after repository probes. Replay from the repository root:

```bash
python docs/evidence/2026-10-14/model-policy-stress/score.py
```

The scorer verifies packet/key hashes after LF normalization and includes a
negative control. Its expected-field metric checks decision fields, calculations,
trace answers, and the absence of claimed dispatch. Object schema conformance is
reported separately using the current repository checker. The scorer was written
after responses were collected; the packet, answer key, and expected scalar values
were frozen beforehand. Free-text reasons and effect descriptions are not part of
the expected-field score. Schema conformance alone does not prove safe execution.

## Results

| Requested model | Expected fields, round 1 | Expected fields, round 2 | Policy decisions, both runs | Numeric calculation fields, both runs | Code traces, both runs |
| --- | --- | --- | --- | --- | --- |
| GPT-6 Luna | 22/24 cases | 23/24 cases | 36/36 | 19/24 | 12/12 |
| GPT-6.1 Sol | 24/24 cases | 24/24 cases | 36/36 | 24/24 | 12/12 |
| GPT-6 Astra | 24/24 cases | 24/24 cases | 36/36 | 24/24 | 12/12 |

All twelve emitted Brief/SpeculativeSet objects passed the checker. This is a
schema observation; the table's case scores exclude free-text object semantics.

Luna's first run omitted another task's cash and call reservations in N05/N06.
It reported free cash of 0.04 instead of 0.02 and prospective calls of 2/4
instead of 4/5. Its N06 route was still blocked, but its calculation did not
support the stated call-limit explanation. In the second run these cases were
correct, while N07's disjoint all-in costs were summed to 0.095 instead of 0.09.
The route was still correctly blocked. Sol and Astra matched all frozen scalar
expectations in both runs. Two runs per profile are too few for a reliability rank.

The useful engineering implication is to calculate reservations and limits in
host code and verify them independently. A correct route label can accompany
incorrect arithmetic. Model prose should not be the budget authority.

## Repository probes and fixes

These are local synthetic transports, not provider calls. The before/after JSON
files preserve the actual observed dispositions.

| Probe | Baseline observation | Observation after this change |
| --- | --- | --- |
| NaN work bound | Dispatched | `blocked-gate4`; no transport call |
| NaN Brief cash allowance | Accepted | Rejected |
| One-candidate SpeculativeSet with zero parallelism | Accepted | Rejected |
| Remaining task budget checked after transport | Second transport ran before refusal | Later fix for [#47](https://github.com/StepenkoAnatoli/SmartRouter/issues/47): durable work and verification reservations precede transport; failures and overruns preserve attempts and known or uncertain cost. The frozen probe predates the adapter's reservation contract and remains unchanged. New tests use declared token ceilings and explicit bounds; see [dispatch accounting](DISPATCH_ACCOUNTING.md). |
| Independent dispatchers sharing a pilot ledger | Both accepted against separate process totals | Later fix for [#48](https://github.com/StepenkoAnatoli/SmartRouter/issues/48): shared persistent reservations coordinate local processes. A two-process test checks the actual send boundary, and a process-crash test proves uncertain allowance survives restart. |
| Wall clock moves backward | Negative elapsed time allowed dispatch | `blocked-deadline`; an observed rollback remains terminal across persisted restarts |

The dispatcher now rejects non-finite, negative, boolean, or otherwise invalid
work/review bounds, rates, caps, and expected token counts before transport.
The schema checker requires finite monetary values, integer call allowances,
distinct speculative candidates, and bounded integer parallelism. It also checks
Brief ownership and list types. Oversized persisted numeric fields now produce
the existing corruption refusal instead of an unhandled conversion overflow;
the original state file is preserved and no provider call occurs.

The dispatcher also retains the last observed wall timestamp and stops automatically
after an observed rollback. With task persistence enabled, that terminal stop survives
restarts and later forward clock movement. Existing state without a high-water mark
uses its start timestamp; it cannot recover observations that were never persisted.

Focused regression checks cover actual pre-transport refusal, unchanged attempt
counters, malformed schema inputs, CLI refusal, and persisted-state preservation.
The fixes made during this frozen comparison did not include durable pilot-wide
reservations or unknown-usage retention. A later
[accounting follow-up](DISPATCH_ACCOUNTING.md) adds those behaviors without
changing this trial's packets, answers or scores. Wall-clock deadlines remain
non-monotonic between observations, and live-provider qualification and final
billing accuracy still require their own evidence.

## Usage and timing limits

Requested aliases are known; resolved immutable model revisions were not exposed.
Per-run input/output/cached/reasoning tokens, billed dollars, and precise completion
times were not exposed either. These remain **unknown**, not zero. Root observation
bounds include tool and inspection delays and cannot support model latency claims.
No speed, price, savings, or broad capability winner is asserted.

Follow-up tasks are [#56–#61](https://github.com/StepenkoAnatoli/SmartRouter/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22llm%20evaluation%22).
They cover unseen fixtures, more repeats, Claude, offline Gemini preparation,
local/open-weight models, and usage/latency capture. Live trials require their
own protocol and authorized spend allowance; an issue is not permission to spend.
