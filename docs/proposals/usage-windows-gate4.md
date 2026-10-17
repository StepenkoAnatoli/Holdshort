# Proposal: Gate 4 affordability for subscription hosts — rolling usage windows

Status: **draft proposal, not normative.** Nothing in `skills/` is amended by
this document. If accepted after independent review (plan §15), the items
below would become an optional host-policy block, one additional Gate 4 rule
and additive §10 fields under the §13 "strictly additive" rule; until then
hosts MUST NOT emit or require them.

## Context

- Gate 4 ([gates.md](../../skills/smart-router/references/gates.md)) requires
  work plus required verification to "fit inside approved cash and resource
  caps", but the only budget the schemas type is cash, calls and a deadline:
  spec-v2.md §10.1 `allowance {cash, calls, deadline}`, §10.5 `counters`
  (calls and cash) and §10.3 `evidence.actual-spend`. No field carries a
  resource cap that is not cash.
- A subscription host has no per-call price. Its finite resource is a set of
  rolling usage windows that the platform reports as a utilization in
  `0..1` with a reset time. On 2026-10-17 a Claude Code host observed two
  (`rate_limit_event`, `rate_limit_info.unifiedWindows`, 19:00:22Z):
  `five_hour` utilization 0.20 resetting 2026-10-17T23:00:00Z, and
  `seven_day` utilization 0.05 resetting 2026-10-24T18:00:00Z. The operator's
  standing rule stops work at 0.90 of the weekly window.
- The 2026-10-13 usage review already recorded the gap: "Subscription usage
  percentages and best-effort tokens do not provide a conservative
  per-dispatch cash/call reservation contract", and "window resets make naive
  before/after subtraction invalid"
  ([usage review](../SMARTROUTER_USAGE_REVIEW_2026-10-13.md), lines 50 and 73).
- Without a typed window, a subscription host either reports Gate 4 as
  advisory-only for every task or invents a cash figure. This proposal gives
  it a third option that stays inside the repository's units rule: "Cash,
  subscription quota, local resources, research credits and effort have
  separate units, with no invented conversions"
  ([plan](../DEVELOPMENT_PLAN.md), line 11).

## Item 1 — `usage-windows` host policy block and the reading record

An optional host-policy block. When absent the feature is off and the
decision's `Uncertainty` says `usage windows: not configured`; when present
every field is required.

```json
"usage-windows": {
  "source": "string (where readings come from, e.g. the platform event name)",
  "reading-max-age-minutes": 30,
  "windows": {
    "five_hour": { "length-seconds": 18000,  "stop-at": 0.90, "lead-reserve": 0.05, "utilization-per-mtok": 0.24 },
    "seven_day": { "length-seconds": 604800, "stop-at": 0.90, "lead-reserve": 0.05, "utilization-per-mtok": 0.06 }
  },
  "coefficient-basis": "string (dated observations the coefficients rest on)"
}
```

Rules (proposed): `stop-at` in `(0, 1]`; `lead-reserve` in `[0, stop-at)`
(the share kept for the coordinating session, which spends from the same
windows but is not routed); `length-seconds` a positive integer;
`utilization-per-mtok` a finite number `> 0`. The coefficient is
**host-declared, never defaulted**: a window without one cannot be projected,
and an unknown coefficient is a policy error, not a pass. The values above are
one host's declaration, not proposed constants. Its basis: 2026-10-14 the
weekly window moved 0.82 to 0.88 over about 1.06M recorded sub-agent tokens
(about 0.057 per Mtok, the coordinator's own tokens unrecorded), and on
2026-10-17 both windows started fresh at 18:00 and by 19:00 stood at 0.20 and
0.05, so the five-hour window moved four times as fast. Attributing all
movement to recorded tokens over-states the coefficient, which is the
conservative direction for a cap.

A reading is one append-only host record, separate from the Outcome Ledger:

```json
{ "ts": "ISO-8601", "windows": { "<name>": { "utilization": 0.2, "resets-at": "ISO-8601" } },
  "source": "string", "note": "string or null" }
```

A reading is rejected when a configured window is missing, a utilization is
outside `[0, 1]`, a `resets-at` is not strictly after `ts`, or `ts` is not
after the previous reading's `ts` (readings are monotonic, like the ledger).

## Item 2 — the Gate 4 window rule

When configured, each candidate's Gate 4 additionally requires, in order:

1. **Fresh reading.** A reading exists and `now - ts <= reading-max-age-minutes`;
   otherwise the candidate fails (`usage reading missing` / `stale`).
2. **No reset since the reading.** `now < resets-at` for every window;
   otherwise fail closed. A reading from before a reset says nothing about the
   new window, so it is not reused as optimistic evidence.
3. **Projection fits.** For every window,
   `utilization + (tokens / 1e6) × utilization-per-mtok <= stop-at − lead-reserve`.
   `tokens` is the same count the cash bound uses for that candidate: the work
   tokens for `direct`; work plus required review plus delegation overhead for
   `delegate`. Equality passes, as for cash.

A candidate failing step 3 is ineligible like any Gate 4 failure; Gate 5 then
orders the rest, so a cheaper profile that fits the window can win over one
that does not. This never makes an unqualified profile eligible: the cheaper
profile must pass Gates 1-3 on its own evidence, and the rule against falling
back to a cheaper tier to avoid blocking is unchanged. When no candidate
fits, the route is `blocked`; if the binding window's `resets-at` is before
the task deadline, the reason ends `defer until the reset` (a reason text, not
a new route). The decision records the reading `ts`, its age, and per window
the utilization, `resets-at`, the projected value for the chosen profile and
the headroom `(stop-at − lead-reserve − utilization) / utilization-per-mtok`
in Mtok; `Uncertainty` names the `coefficient-basis`.

**Re-check at dispatch.** Steps 1-3 are re-run for the dispatched profile at
dispatch time against the decided token count (gates.md "Qualification,
freshness and pre-dispatch binding", item 3): a decision taken within the
freshness limit can be stale when dispatched, and a stale or reset reading
refuses the dispatch with the same reason.

## Item 3 — additive fields and the coefficient learning rule

| Object | Field (additive, optional) | Meaning |
|---|---|---|
| §10.5 LedgerRecord, `kind: decision` | `usage-tokens` | The token count Gate 4 projected for the chosen profile. |
| §10.5 LedgerRecord, `kind: outcome` | `tokens` | Tokens the host observed for the task; `null` when unknown. |
| §10.3 Outcome `evidence` | `actual-tokens` | Integer `>= 0`, or `null` (unknown; absent means `null`). |

`counters` and `actual-spend` are unchanged; unknown tokens stay `null`,
never zero.

Learning rule (proposed): for each pair of consecutive readings with no reset
of the window between them, `observed = (u2 − u1) / (T / 1e6)`, where `T` is
the sum of outcome `tokens` whose record `ts` falls in `(ts1, ts2]`. Pairs with
`T = 0` or any unknown token count are skipped and counted, never imputed.
Revisions are proposals that the operator ratifies by editing the policy;
nothing is applied automatically.

- **Upward at once:** propose `max(observed)` when it exceeds the current
  coefficient by more than 10 %.
- **Downward slowly:** propose a lower value only after three consecutive
  observations all below 90 % of the current coefficient.

Usage outside the router (the coordinator, other sessions on the same account)
moves the windows without appearing in `T`; it biases observations upward,
which the asymmetric rule accepts rather than corrects.

## Item 4 — `null` cash on an estimate-only host

**Observed.** A subscription host has no per-call cash. Its honest value for `counters.cash-spent`,
`counters.cash-cap` (§10.5) and `evidence.actual-spend` (§10.3) is *unknown*. `tools/conform_spec.py`
refuses that today: every one of the 25 LedgerRecords the Claude Code adapter wrote fails with
`LedgerRecord counters.cash-cap must be a finite non-negative number` or
`... cash-spent must be a finite non-negative number` (`check_record`, line 271), and its Outcomes fail with
`Outcome breaks §10.3 (evidence actual-spend must be a finite non-negative number)` (`check_outcome`, line 191);
the same adapter's Briefs are `CONFORMANT`. Run on 2026-10-17 against `fbe7bca`.

**The contradiction.** `docs/USAGE_TELEMETRY.md` line 56 says a missing counter "stays `null`. It never
becomes zero", and `docs/DEVELOPMENT_PLAN.md` line 11 says the units are never converted. A host that
obeys those two sentences cannot write a §10.5 record, and a host that writes `0.0` to pass the checker
invents a bill of nothing — the exact thing the telemetry rule forbids.

**Proposal.** The three cash fields admit `null` when, and only when, the record declares why: the
LedgerRecord `counters` carry `"cash-basis": "estimate-only"` and the Outcome `evidence` carries
`"actual-spend-basis": "estimate-only"` (both additive, §13). `conform_spec.py` then accepts `null` for
those fields on such records and keeps refusing it everywhere else, so an unmarked `null` is still a
violation. `gate4-affordability.md` already says a strict cap needs reliable accounting; this makes the
absence of accounting representable instead of forcing a lie. The checked-in `host_dry_run.py` keeps
writing `0.0` only because its dry run spends nothing; a live subscription host would set the marker.

**Evidence.** The adapter's ledger and decision files are under
`hosts/claude-code/trace/` in this branch once the adapter lands; until then the checker output above is
reproducible on any record whose cash fields are `null`.

## Non-goals

- **No cash conversion.** Utilization is never converted to dollars, and a
  window projection never satisfies or replaces a cash cap; a host with both
  checks both.
- **No invented provider bill.** Readings and token counts are platform and
  harness observations; the usage review's stance holds: "no
  subscription-token-to-dollar conversion and no router savings claim".
- **No savings claim** from deferring or re-ordering around windows.
- No change to the gate order, routes, HumanGate values or existing reason
  texts; no default coefficient; no fabricated readings (a host that cannot
  read its windows leaves the block absent and reports Gate 4 as before).

## Review record (pending)

- Author: SmartRouter working thread, 2026-10-17, revision at PR time. A
  Claude Code host adapter outside this repository is specified to implement
  Items 1-3; no result from it is claimed here.
- Independent reviewer: *unassigned* — plan §15 requires a non-author
  verdict at the full reviewed revision plus owner acknowledgement before
  this proposal (or any part of it) amends normative files.
- Disposition: *pending*. Substantive edits re-date the proposal; approval of
  an earlier revision does not carry forward (P02).
