# Unit sr-policy-3: host policy revision 3 from calibration run 2 and the usage-window measurement

Worktree and branch: created by the lead from the integration head (named in the launch prompt). Work only
under `docs/orchestration/smartrouter/`. Node 24 at `/versions/node/v24.21.0/bin`; suite
`node --test docs/orchestration/smartrouter/route.test.mjs` (80 tests green at the start); lint
`npx eslint docs/orchestration/smartrouter/route.mjs docs/orchestration/smartrouter/route.test.mjs`; typecheck is
`node --check docs/orchestration/smartrouter/route.mjs`. Commit identity and trailer lines as in
`briefs/router-builder.md`; never --no-verify; no push; never edit `trace/ledger.jsonl`, `trace/usage.jsonl` or
`trace/decisions/hand-*.json` by hand. Commit with the five-part report (what changed, why, what it touched, what
you verified with verified/untested/expected, what you got wrong). The repository's commit gate requires
`docs/ARCHITECTURE.md` staged with any change under a declared code path; `docs/orchestration/smartrouter/` is not
one, so a commit touching only the adapter needs no map change (the previous policy unit committed that way).

## Why

Calibration run 2 (`trace/calibration-2/`, run `wf_fe91e1d6-d78`; protocol preregistered upstream in SmartRouter
`docs/evidence/2026-10-17/claude-code-calibration-2/`) measured 12 profiles on pin and fix (U2-R13 at d0bb208) and 15
on review (U2-R11 + U2-R13 at d3aaf21). With run 1 that gives two independent calibration passes for several
high-risk cells, which the lead's qualification rules (README, host-policy-2) turn into qualifications. The same
run gave the first clean measurement of the usage-window coefficients, which the policy declares and must now carry
with its basis. Qualification is declared by the host from evidence, never inferred (SmartRouter rule); the lead has
applied the rules below and this unit writes the result into the policy, its tests and the README.

## The results the lead applied (from `trace/calibration-2/results-table.md`; run 1 from `trace/calibration-1/`)

| profile | run 1 pin/fix/review | run 2 pin/fix/review | consequence (rules 1-4, README) |
|---|---|---|---|
| cc-haiku-low | PASS/PASS/FAIL | PASS/PASS/FAIL | `fix` qualified (two passes); review: two fails recorded |
| cc-haiku-medium | PASS/PASS/FAIL | PASS/PASS/FAIL | `fix` qualified; review: two fails |
| cc-haiku-high | PASS/PASS/FAIL | PASS/PASS/FAIL | `fix` qualified; review: two fails |
| cc-sonnet-low | PASS/PASS/PASS | PASS/PASS/PARTIAL | `fix` qualified; review one pass + one partial (not a pass): not qualified |
| cc-sonnet-medium | PASS/PASS/PASS | PASS/PASS/FAIL | `fix` qualified; review: one pass then a fail: blocked until two later passes (rule 3) |
| cc-sonnet-high | PASS/PASS/FAIL | PASS/PASS/PASS | `fix` qualified; review: a fail then one pass: one more pass needed (rule 3) |
| cc-opus-medium | PASS/PASS/PASS | PASS/PASS/FAIL | `fix` qualified; review: blocked until two later passes (rule 3). The run-2 FAIL rests on one grader classification (G-1, lead-notes.md) that the cross-candidate adjudication contests; the preregistered rule stands and the adjudication is recorded, not applied |
| cc-opus-high | PASS/PASS/PASS | PASS/PASS/PASS | unchanged (already qualified from production); gains the entries |
| cc-opus-xhigh (NEW profile) | PASS/PASS/PASS | PASS/PASS/PASS | add the profile: `pin-tests`, `fix`, `review` qualified (two passes each) |
| cc-fable-medium | PASS/PASS/PASS | PASS/PASS/PASS | `fix` and `review` qualified (two passes each) |
| cc-fable-high | PASS/PASS/PASS | PASS/PASS/PASS | unchanged; gains the entries |
| cc-fable-xhigh | PASS/PASS/PASS | PASS/PASS/PASS | unchanged (lead-direct); gains the entries |
| cc-sonnet-xhigh (NEW, review only) | - | -/-/PASS | add the profile with `qualified-for: []` and the review PASS (n=1) entry: one pass of a high-risk category |
| cc-opus-max (NEW, review only) | - | -/-/PASS | same |
| cc-fable-max (NEW, review only) | - | -/-/PASS | same |

Every pin PASS is a second `pin-tests` pass (already qualified from run 1). Evidence entries use the existing form,
one per run and task: `calibration-2: fix PASS (n=1)`, `calibration-2: review PARTIAL (n=1)` - extend the accepted
form so `PARTIAL` is a valid grade word (the adapter refuses other forms); run 2's review grade is three-valued by
its preregistered protocol. Each profile also gets the run-id entry `wf_fe91e1d6-d78 (calibration-2): pin, fix and
review graded in trace/calibration-2/ (results-table.md, observations.json)`.

`headroom-tested` is the largest completed calibration run, rounded up to the next thousand, never lowered:
haiku-low 175000, haiku-medium 183000, haiku-high 261000 (unchanged), sonnet-low 114000, sonnet-medium 128000,
sonnet-high 183000, opus-medium 154000, opus-high 514000 (unchanged), opus-xhigh 246000, fable-medium 172000,
fable-high 352000 (unchanged), fable-xhigh 460000 (unchanged), sonnet-xhigh 328000, opus-max 307000, fable-max
230000. New profiles copy the config/tools/vision/context-tested/role shape of their siblings; `qualified-at`
2026-10-18, `expires` 2027-01-15, reviewer `host-declared (lead) from calibration-1 and calibration-2 grades` for
every entry this revision adds or changes.

The lead's note on `fix`: the two calibration fix cells were single-finding fixes with the accepted finding text
given (110000-170000 tokens); a production fix round (`fix` median 193000) carries several findings. Rule 1 judges
the cell representative in kind, and the size difference is held by the `headroom-tested` guard (`tokens <
headroom-tested` at Gate 2), the category's required fresh re-review, and the learning loop's demotion after two
consecutive verification-failed outcomes. Say this in the README's qualification section, and state the routing
consequence from the policy's own economics (compute it with `decide` and quote it): a default `fix` request now
routes to the cheapest qualified profile whose headroom admits 193000 + review tokens.

## Usage windows: ratify the measured coefficients and raise the lead reserve

Measured over run 2 with the lead idle but for one check-in (readings in `trace/usage.jsonl`, 23:22:51 to 01:23:32,
nothing in flight at either end; 7,872,276 reported sub-agent tokens): five_hour 0.12 -> 0.39 (0.0343 per Mtok),
seven_day 0.28 -> 0.36 (0.0102 per Mtok). The declared 0.24 and 0.06 overstate by about 7x and 6x. Separately,
lead-only work (no sub-agent running) moved five_hour from 0.02 to 0.12 between 23:07 and 23:22, about 0.40 per hour
of active lead work: the lead's own turns, not sub-agent tokens, are this host's dominant cost, and the 0.05
`lead-reserve` covers about eight minutes of them. Ratify in `usage-windows`: `utilization-per-mtok` five_hour
**0.05**, seven_day **0.015** (about 1.5x the measured values, rounded up: the conservative direction); `lead-reserve`
five_hour **0.25** (about 40 minutes of active lead work at the measured rate), seven_day **0.10**; `ratified-at`
2026-10-18T01:23:32Z on both windows; `coefficient-basis` rewritten to name the measurement (run id, the two readings,
the token count, the lead-only interval) and to say that `rate` could not learn it because the run was not dispatched
through the adapter and every pair of readings during it had no recorded outcome tokens (friction item for upstream,
below). Do not change the gate's arithmetic; `route.mjs usage` with no file must print the new headroom.

## Deliverables

A. `host-policy.json` becomes `policy-revision: host-policy-3` with the table above applied, the four new profiles,
   the `PARTIAL` grade word accepted, headroom values, and the usage-windows block ratified.
B. The goldens stay on the host-policy-1 fixture. Copy the pre-revision policy to `trace/policies/host-policy-2.json`
   (a fixture, never edited) and pin the host-policy-2 routing assertions (pin-tests -> cc-haiku-low; review ->
   cc-opus-high; fix -> cc-opus-high) to it with `--policy`. Add the host-policy-3 assertions against the live policy:
   a `pin-tests` request routes to cc-haiku-low; a `review` request to cc-opus-high (opus-xhigh ties on price and
   loses on effort; fable-medium's headroom is below the review median plus overhead); a `fix` request to the profile
   the economics choose (compute it, assert it, and name it in the README); a `review` request with `candidates`
   limited to the three new review-only profiles routes `blocked` (one pass is not a qualification).
C. `rate`: the CALIBRATION lines read every `trace/calibration-*/observations.json`; run 2's review grade is the
   three-valued `review-grade.result` (PASS/PARTIAL/FAIL), run 1's is the boolean `review-grade.score`; print
   `pass, partial, fail` counts per profile and category across runs; proposals stay outcome-based and ignore
   calibration (unchanged).
D. README: the qualification table regenerated from the policy (15 rows); the rules section says how run 2 was
   applied (the table above in prose or as is) and carries the lead's note on `fix`; the usage-windows section
   gains a 'Measured coefficients (run 2)' paragraph with the numbers above and the lead-turn finding, and the
   friction log gains two items: (17) `rate` cannot learn from a run that is not dispatched through the adapter, and
   on a host where units overlap continuously every pair of readings is `spanning` or `T=0`, so the learning loop
   never gets a clean pair - propose a `usage-observation` record (a reading pair with a token count the lead
   attests) or letting calibration runs be recorded as outcomes without a decision; (18) the spec's budget model
   (cash, tokens) does not see the lead's own consumption, which on a subscription host dominates: propose a
   per-turn lead cost in the host model.
E. Tests red-first with guard-removal proofs: policy validation of `PARTIAL` and of the new profiles; the
   host-policy-2 fixture goldens; the host-policy-3 routing assertions; `rate` reading both observation formats
   and printing partial counts; `usage` printing the new headroom from the ratified coefficients.

F. `rate` proposes a `headroom-tested` raise for a profile whose accepted outcome completed more tokens than its
   current value (`PROPOSAL profiles.<id>.headroom-tested: <current> -> <tokens rounded up to the next thousand>`),
   because the sr-policy-3 decision seq 1 was blocked on a stale headroom: cc-opus-high had completed 770527 tokens
   on the accepted sr-policy-2 unit while its headroom-tested still said 514000, and nothing proposed the raise (the
   lead applied it by hand, commit 'policy maintenance'). The lead ratifies by editing the policy, as for every
   proposal; tests red-first for the proposal and for its absence when the outcome's tokens are unknown or below.

## Non-goals and stop triggers

No change to gate order or reason texts; no qualification beyond the table (a cheaper profile does not become
eligible because it looks capable); no edit to the ledgers or to any `trace/calibration-*` file; no new command or
flag. Stop and report if a golden under the host-policy-1 fixture changes, if the suite's 80 tests do not stay
green, or if applying the table would require a rule not written above.
