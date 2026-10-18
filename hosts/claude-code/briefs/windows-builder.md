# Unit sr-windows: usage windows in Gate 4 (a subscription host's real limit)

Worktree `/home/user/task5-handoff/wt/sr-windows`, branch `build/sr-windows`, base `958fce3` (the adapter as
built: `docs/orchestration/smartrouter/route.mjs`, `route.test.mjs`, `host-policy.json`, `README.md`; read
`briefs/router-builder.md` for the conventions the adapter follows, and the README in full). Work only in
`docs/orchestration/smartrouter/`. Node 24 is at `/versions/node/v24.21.0/bin`; the suite is
`node --test docs/orchestration/smartrouter/route.test.mjs` (26 pass at base). Commit identity
`git -c user.name=StepenkoAnatoli -c user.email=318295322+StepenkoAnatoli@users.noreply.github.com commit`;
every commit ends with the two attribution lines in `briefs/router-builder.md`; never `--no-verify`; no push.

## Why

The owner (2026-10-17): "adapt for daily and weekly limit for now". This host is a Claude subscription. Its
finite resource is not cash but two usage windows the platform reports on every turn as a `rate_limit_event`:

```
rate_limit_info.unifiedWindows = {
  "five_hour": { "resetsAt": 1792278000, "utilization": 0.2 },     // epoch seconds; 0..1
  "seven_day": { "resetsAt": 1792864800, "utilization": 0.05 }
}
```

(observed 2026-10-17T19:00:22Z; `five_hour` resets 2026-10-17T23:00:00Z, `seven_day` 2026-10-24T18:00:00Z).
The lead reads it with the `claude-code-remote` tool `list_events(kinds=["rate_limit_event"])` and pastes it
to the adapter; the adapter cannot call that tool. The standing rule (user, 2026-10-14) stops work at 0.90
of the weekly window; the same threshold applies to the five-hour window here. Two observations of how
utilization moves per recorded sub-agent token, both coarse: 2026-10-14 17:01 to 18:18 the weekly window
went 0.82 to 0.88 while about 1.06M recorded sub-agent tokens ran (the lead's own tokens unrecorded), and
2026-10-17 18:00 to 19:00 (both windows fresh at 18:00) `five_hour` reached 0.20 while `seven_day` reached
0.05: the five-hour window moves about four times as fast as the seven-day one.

## Deliverables

**A. Policy.** An optional `usage-windows` block in `host-policy.json`; when absent the feature is off and
every decision carries the Uncertainty line `usage windows: not configured`. When present `validatePolicy`
requires all of it:

```
"usage-windows": {
  "source": "claude-code-remote list_events kinds=[\"rate_limit_event\"] -> rate_limit_info.unifiedWindows; the lead pastes it with route.mjs usage <reading.json>",
  "reading-max-age-minutes": 30,
  "windows": {
    "five_hour": { "length-seconds": 18000,  "stop-at": 0.90, "lead-reserve": 0.05, "utilization-per-mtok": 0.24 },
    "seven_day": { "length-seconds": 604800, "stop-at": 0.90, "lead-reserve": 0.05, "utilization-per-mtok": 0.06 }
  },
  "coefficient-basis": "host-declared 2026-10-17 from two coarse observations (README 'Usage windows'); rate proposes revisions from paired readings"
}
```

Rules: `stop-at` in (0,1]; `lead-reserve` in [0, stop-at); `utilization-per-mtok` a finite number > 0
(unknown is not allowed: a window with no coefficient cannot be projected, and the lead declares one with
its basis rather than leaving the gate blind); `length-seconds` a positive integer. Add exactly this block
to the committed `host-policy.json` (values above).

**B. Readings.** `route.mjs usage <reading.json> [--now <iso>]` appends one record to `trace/usage.jsonl`
(append-only, never rewritten, separate from `ledger.jsonl`):
`{ "ts": <iso>, "windows": { "<name>": { "utilization": <0..1>, "resets-at": <iso> } ... }, "source": "rate_limit_event", "note": <string|null> }`.
It accepts the raw `rate_limit_info` object, a bare `unifiedWindows` object, or the normalised form; `ts`
is `--now` (default: the clock). Exit 2 on: a window named in the policy missing from the reading, a
utilization outside [0,1], a `resets-at` not strictly after `ts`, a `ts` not after the previous reading's
`ts` (readings are monotonic, like the ledger clock). `route.mjs usage` with no file prints the latest
reading with its age and, per window, the headroom in Mtok at the policy coefficient:
`(stop-at - lead-reserve - utilization) / utilization-per-mtok`.

**C. Gate 4 in `decide`.** When configured, every candidate's Gate 4 additionally requires, in this order:
1. a reading exists and `now - ts <= reading-max-age-minutes`, else fail
   `usage reading missing` / `usage reading stale: age N min > M; refresh with route.mjs usage`;
2. no configured window has reset since the reading (`now < resets-at` for each), else fail
   `usage window <w> reset at <iso> after the reading; refresh with route.mjs usage` (fail-closed: a
   reading from before a reset says nothing about the new window);
3. for each window, `projected = utilization + (tokens / 1e6) * utilization-per-mtok <= stop-at - lead-reserve`,
   where `tokens` is the same count the cash bound uses: the work tokens for direct; work + the reviewer's
   tokens (when the category needs a review) + `delegate-overhead-tokens` for delegate. Fail with
   `usage window <w>: projected P > S (stop-at X - lead-reserve Y); resets <iso>` and, when `resets-at` is
   before the task deadline, append `; defer until the reset`.
The decision JSON gains `usage`: `{ "reading-ts", "reading-age-minutes", "windows": { "<w>": { "utilization", "resets-at", "projected" (for the chosen; null if blocked), "headroom-mtok" } } }`
and the walkthrough's Gate 4 note names the binding window. Candidates failing step 3 are simply
ineligible: economics then orders what is left, so a cheaper profile that fits the window wins over a
pricier one that does not, and `recommend-escalation`/`blocked` fall out of the existing flow unchanged.
Uncertainty line: `usage windows: coefficients host-declared (<coefficient-basis>)`.

**D. `dispatch`** re-checks 1-3 for the dispatched profile at its `--now` (a decision taken 25 minutes
earlier can be stale by dispatch time) and refuses with exit 3 and the same reason text.

**E. `outcome`** accepts an additive `evidence.actual-tokens` (integer >= 0, or null = unknown; absent =
null) and records it on the outcome ledger record as the additive field `tokens` (spec-v2 §13 allows
additive fields; §10.5's `counters` stay as they are).

**F. `rate`** adds observed coefficients: for every pair of consecutive readings with no reset of the window
between them, `observed = (u2 - u1) / (T / 1e6)` where `T` is the sum of outcome `tokens` recorded with
`ts` in `(ts1, ts2]`; pairs with `T = 0` or unknown tokens are skipped and counted. The stats document gets
`usage: { "<w>": { "observed": [{ "from", "to", "delta", "tokens", "coefficient" }], "max-observed", "current" } }`.
A `PROPOSAL usage-windows.windows.<w>.utilization-per-mtok: <current> -> <max-observed>` is printed when the
max observed exceeds the current by more than 10 % (upward at once: the conservative direction); a lower
value is proposed only when three consecutive observations are all below 90 % of the current (downward
slowly). The lead ratifies by editing the policy, as for every other proposal.

**G. README.** A "Usage windows" section (the reading command, the rule, the two observations above with
their dates as the coefficient basis, the headroom arithmetic, what refreshes a reading), a row in the
enforced-vs-advisory table (`Usage windows | enforced when configured: fresh reading required; projection
against stop-at - lead-reserve in decide and dispatch`), and friction item 13 for upstream: the spec
types Gate 4's budget as cash + calls + deadline; a subscription host's finite resource is a set of rolling
usage windows with a host-learned tokens-to-utilization coefficient, and nothing in §10.1/§10.5 carries a
window. Keep the README's existing claims true: re-run every command you cite.

**H. Tests**, red-first in `route.test.mjs` (each new test shown red before its code, each with at least
one guard-removal proof you ran and name in the report): policy validation (a missing or non-positive
coefficient, a reserve >= stop-at: exit 2); `usage` append, rejection cases, monotonic ts, the no-file
summary; Gate 4 steps 1-3 (missing, stale, reset-after-reading, projection over with the reason text and
the defer suffix, projection under with the `usage` block and the correct `tokens` for direct vs delegate);
a cheaper profile within the window chosen over a pricier one that exceeds it; `dispatch` refusal on a
stale reading and on an over-projection; `outcome` with `actual-tokens` (valid, null, invalid); `rate`
observed coefficients and the upward proposal, the skipped-pair count, the slow downward rule; the feature
off when the block is absent (the base's 26 tests stay green; the Uncertainty line says not configured).
Commits: (1) policy + usage command + Gate 4 + dispatch with tests; (2) outcome tokens + rate learning with
tests; (3) README. Five-part reports in every message (what changed, why, what it touched, what you
verified with verified/untested/expected, what you got wrong and fixed in the six fields, or "nothing to
report").

## Non-goals and stop triggers

No change to the five gates' order or to any existing reason text; no cash cap; no new transport; no
reading fabricated (the tests use synthetic readings and say so); no edit to `ledger.jsonl` or
`decisions/` by hand. Stop and report (do not guess) if the Outcome or LedgerRecord shape would need a
non-additive change, or if a base test cannot stay green without changing its expectations.

## Lead's rulings after the first attempt (2026-10-17, review W-1..W-5)

The first builder stopped correctly on the stop trigger: the brief contradicted itself. Rulings, which amend
A, C and H above:

- **W-2 → R1(b), ratified.** The three golden tests compare `uncertainty` after dropping every line that
  starts with `usage windows:`. The hand-walked decisions predate the feature and are never hand-edited;
  the filter is the one expectation change, and it is the lead's. Everything else in the goldens
  (route, profile, bounds, candidates, walkthrough) stays an exact comparison.
- **W-3 → R1(a), ratified.** The base tests run against a feature-off fixture: the committed policy with
  `usage-windows` deleted, written to a tmp file by the test harness; `cli()` passes `--policy <fixture>`
  unless the call already passes one; no base assertion changes. Two compensating tests on the committed
  policy (block present): (i) a fresh tmp trace with no reading → `decide` on the stored request
  `hand-gsi-u6-build.json` is `blocked`, every candidate's first failing gate 4 with reason
  `usage reading missing` (the fail-closed default on the real policy); (ii) the same request after
  `route.mjs usage` with a synthetic fresh reading (five_hour 0.20 resetting in 4 h, seven_day 0.05
  resetting in 6 d, both relative to `--now`) → `delegate` on `cc-opus-high` with the decision's `usage`
  block filled and `projected` below `stop-at - lead-reserve` for both windows.
- **W-4 → the brief's lines stand.** The two trailer lines are the session's attribution and are used on
  every commit of this build whichever model ran the sub-agent; the dispatching model is recorded in the
  ledger and RUN.md, not in the trailer.
- **W-5 → base = the adapter's head after its review**, named in the relaunch prompt (the branch
  `build/sr-windows` is recreated from that head and this brief commit is carried over). Read the adapter's
  review-round commits (`git log 958fce3..HEAD`) before building: reason texts or helpers may have moved.
- **Design notes ratified:** (1) the decision LedgerRecord carries the additive field `usage-tokens` (the
  token count Gate 4 projected for the chosen profile) and the decision file carries the `usage` block, so
  `dispatch` re-checks against the decided count; (2) the outcome record's additive `tokens` as in E;
  (3) `rate` pairs readings by `ts`, outcomes by their record `ts` in `(ts1, ts2]`.

With these rulings the stop trigger "a base test cannot stay green without changing its expectations" is
satisfied by the ratified filter alone; any other expectation change still stops the unit.
## Lead's rulings after review 1 of the second attempt (2026-10-17 20:35 UTC)

- **SW-5 (coefficient proposals oscillate) → option (a), ratified.** Each window carries `ratified-at`
  (ISO) in the policy next to `utilization-per-mtok`; `rate` compares only observations whose `to`
  reading is after `ratified-at` (the upward rule's max and the downward rule's three-in-a-row alike).
  Ratifying a proposal means editing the coefficient and `ratified-at` together; a missing `ratified-at`
  means "consider everything" (the first revision). Red-first test: the reviewer's flip-flop probe
  sequence, with `ratified-at` set after each ratification, produces no second proposal.
- **SW-6 / W-4 re-ruled.** Per-commit attribution of the model that wrote the commit is the accepted
  practice of this build (the integration branch carries 460 `Claude Opus 5.5` and 37 `Claude Fable 5.1`
  trailers); the brief's "two lines" wording in router-builder.md and common.md is stale and the lead
  docs unit rewords it to "the session's attribution lines for the model that writes the commit, plus
  the Claude-Session line". No commit is rewritten.
