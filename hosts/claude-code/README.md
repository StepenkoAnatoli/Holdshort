# SmartRouter host adapter (MoonAliza build process)

`route.mjs` is the host side of [SmartRouter](https://github.com/StepenkoAnatoli/SmartRouter) (pinned at `fbe7bca`,
skill 3.0.0) for this repository's build runs. SmartRouter itself is a routing policy: advisory and stateless. It
says which route (direct, delegate, speculative, recommend-escalation, blocked), which profile (model and effort)
and which isolation apply to a unit of work, and why. The **host** is this adapter plus the lead session. The host
collects the inputs, enforces the decision, and keeps the Outcome Ledger. The adapter never dispatches anything
itself. Every output it prints carries `Advisory: recommendation only — no dispatch performed or claimed`.

| File | What it is |
|---|---|
| `host-policy.json` | The host's declared inputs: harness, authorization, accounting mode, prices, categories, profiles with qualification evidence, economics constants, opt-ins. Edited only by the lead. Current revision: `host-policy-3`. |
| `route.mjs` | The adapter: CLI plus named exports. Node built-ins only. |
| `route.test.mjs` | `node --test` suite, one test per SmartRouter fixture it mirrors, plus the three golden hand-walked decisions. The base tests and the goldens run on `host-policy-1`, the usage-window and host-policy-2 tests on `host-policy-2` (the fixtures below), the live policy on its own tests. |
| `trace/ledger.jsonl` | The Outcome Ledger: spec-v2 §10.5 records, append-only, never rewritten. |
| `trace/decisions/<task>-<seq>.json` | One file per decision: the request, input and policy digests, the per-candidate gate walkthrough with reasons, the chosen profile, estimates vs accounting, the Brief. `hand-*.json` are the lead's hand-walked decisions from before the adapter existed. |
| `trace/policies/host-policy-1.json` | The policy before revision 2, byte-identical to the one the hand-walked decisions and `sr-policy-2-1` were decided under. A test fixture, never edited: the goldens decide against it with `--policy`. It lives apart from `trace/decisions/`, whose `<task>-<seq>.json` names belong to decisions (a fixture there would block a task named `host-policy` at seq 1). `sr-policy-2-1`'s Brief names the fixture's first path, `trace/decisions/host-policy-1.json`; the decision file is a record and is not rewritten. |
| `trace/policies/host-policy-2.json` | The policy before revision 3, byte-identical to the one the `sr-policy-3` decisions were bound to (sha256 `71e47f17...`). A test fixture, never edited: the host-policy-2 assertions and the usage-window tests run on it. |
| `trace/outcomes/<task>-<seq>.json` | The §10.3 Outcome objects that outcome records point at. |
| `trace/calibration-<n>/` | A graded calibration run: `observations.json` (per profile: the pin, fix and review grades and the tokens used), `results-table.md`, the lead's notes. Evidence for the qualification rules, read by `rate`, never written to the ledger. |
| `trace/usage.jsonl` | The usage readings (the subscription's five-hour and seven-day windows) pasted by the lead with `route.mjs usage`. Append-only, never rewritten, separate from the ledger. |
| `trace/qualification-stats.json` | Derived by `rate`. Regenerated on every run, never hand-edited. |

## The lead's per-dispatch procedure

Run every command from the repository root. Node 24 must be on `PATH`.

0. **Refresh the usage reading** when the latest one is older than 30 minutes, or a window has reset since it
   (`route.mjs usage` with no file says which): paste the platform's latest `rate_limit_event` with
   `node docs/orchestration/smartrouter/route.mjs usage <reading.json> --now <the event's own timestamp>`
   (section 'Usage windows'). `--now` is when the platform observed the windows, and staleness is measured from it;
   without it the paste time is recorded and an old event passes as fresh. Without a fresh reading every candidate
   that reaches Gate 4 fails it, and `decide` returns `blocked`.
1. **Decide.** Write the request JSON (fields below) and run
   `node docs/orchestration/smartrouter/route.mjs decide <request.json>`.
   It prints the Required output format block, the Advisory line, a gate walk per candidate and, for `delegate`,
   the Brief. It also writes `trace/decisions/<task>-<seq>.json` and appends a `decision` record. Exit 0 means a
   route was decided, and that includes `blocked`. Exit 2 means the request is invalid. **A `blocked` route is
   final**: change the inputs (scope, checks, data classes) and decide again; never dispatch around it. When no
   candidate is eligible the route is `blocked`, even if a profile outside `candidates` would pass: the
   Uncertainty line names it as a hint (`not among candidates: ...`), and only a fresh decision that lists it can
   route to it. The adapter never emits `recommend-escalation` (friction item 13).
2. **Put the Brief in the builder's prompt** verbatim. The JSON after `Brief:` is the contract. Use the profile's
   model and effort exactly as the `Profile:` tuple says.
3. **Record the dispatch before launching:**
   `node docs/orchestration/smartrouter/route.mjs dispatch <task-id> <profile-id> --project-stop '{"redSuite":false,"gateOff":false,"researchGateFailing":false}'`.
   `--project-stop` is required and states the project stop rules as they are **now** (the suite compared with
   its baseline, GATE_OFF or `--no-verify` in use, the research gate). Missing or malformed is exit 2. A stop that
   is true refuses the dispatch at Gate 1 and names the rule. This reserves the call slot. Exit 3 means refused, so do not launch. **Reconcile first**: while any earlier
   dispatch of the task, of any profile, has no outcome record naming its dispatch seq, `dispatch` refuses; record
   that outcome (step 5, `cancelled` if the worker was stopped) and decide again. The only exception is the other
   members of the same speculative decision (spec-v2 §7 and §12). Before it records anything, `dispatch`
   re-walks the decision's stored request (`trace/decisions/<task>-<seq>.json`) against the current policy, ledger
   and `--now`: a fingerprint that expired, a data class or destination that was revoked, a route that moved to
   another profile, or a Brief that changed since the decision refuses the dispatch, and the lead decides again.
   The Brief changes when the call limit, the repair allowance, the deadline cap or a price moves: the recomputed
   brief fingerprint then differs from the decided one ('the Brief changed since decision seq N; decide again',
   naming the changed fields). The other members of the same speculative decision are the decision's own use of its
   slots, so they do not change its Brief. Dispatching any other
   profile than the decided one is a host deviation: it needs `--deviation "<reason>"`, the ledger marks it, and it
   is allowed only to a profile that passes Gates 1-4 on the same request. An unqualified profile, or one with no
   capability fingerprint, is refused even as a deviation (spec-v2 §11.2, §11.10, §12), and so is the
   lead-direct profile (`economics.lead-direct-profile`), which works direct only. A `speculative` decision
   admits no deviation at all: only the members of its set are dispatched, and at most its `shared-budget.calls`
   of them (a hard ceiling, spec-v2 §8.4).
4. **Launch** the sub-agent in its own worktree and branch (`build/<unit-slug>`, the host convention; the Brief's
   `branch-hint`).
5. **Record the outcome** when the unit ends, from observed evidence, never from the agent's self-report:
   `node docs/orchestration/smartrouter/route.mjs outcome <outcome.json>`. This takes a §10.3 Outcome. Its
   `original-brief-fingerprint` must be the decision's, `actual-spend` is `null` in this host, and `owner-profile`
   is the profile id or its exact identity tuple. Put the unit's total tokens in the additive
   `evidence.actual-tokens` (an integer, or `null` when unknown). The outcome record carries it as `tokens`, and
   `rate` uses it to check the usage coefficients.
6. **Re-route on failure.** Decide again with `previousResult` set to that Outcome. One same-profile repair is
   allowed per task. After that, the same profile is refused at Gate 4 and the decision falls to another
   qualified profile, which is a fresh decision.
7. `status <task-id>` prints the task's counters. `rate` runs the learning step (below).

Request fields: `taskId`, `objective`, `category`, `unit`, `permittedEffects`, `sources`, `nonGoals`,
`acceptanceChecks` ([{command, expect}]), `estimatedTokens` (default: the category median), `requiredTools`
(default: the category's), `needsVision`, `dataClasses` (at least one), `projectStop` ({redSuite, gateOff, researchGateFailing}),
`previousResult`, `deadline`, `now` (both ISO-8601; `now` is injected for determinism), `candidates` (default: every
profile; it also bounds who may review), `allowDirect` (default true), `hostOptIns`. Three optional additions are accepted: `uncertainty: "high"`
(the only way to reach `speculative`, and only with the host opt-in) and `requiredIsolation` (a lower bound on the
§6 lattice). Every command takes `--trace <dir>` and `--policy <file>`. `dispatch`, `outcome`, `rate` and `usage`
also take `--now <iso>`. `dispatch` requires `--project-stop <json>` and takes `--deviation <reason>`.

Exit codes: 0 done; 2 invalid input, including a `now` earlier than the task's latest ledger event (the task clock
is monotonic) and a usage reading `usage` refuses; 3 refused; 4 ledger integrity (an unparseable or non-§10.5 line,
a seq gap, or a last line with no trailing newline; the same for an unparseable or unterminated `usage.jsonl`).
The adapter refuses to append to a ledger it cannot read; it never skips a line. When writing a
ledger line by hand, end it with a newline: the adapter refuses an unterminated last line rather than append onto
it, and the fix is to add the missing newline, which changes no record.

## Enforced vs advisory in this host

| Concern | Status | Where |
|---|---|---|
| Permissions, data classes, project stops | **enforced**: Gate 1 denies before anything else; a forbidden data class never reaches Gate 2. A request that declares no data class is invalid (exit 2): every dispatch transmits at least the objective and sources. `dispatch` re-walks Gate 1 with the project-stop state the lead passes as `--project-stop` (required), never with the snapshot taken at decide time | `decide`, `dispatch` |
| Capability qualification and fingerprint freshness | **enforced**: declared `qualified-for`, `qualified-at`, `expires`, `headroom-tested`; equality with `expires` is expiry | `decide` |
| Verification prerequisites | **enforced**: every category check must be named in `acceptanceChecks`; a required review needs a reviewer drawn from the request's `candidates` (never the lead-direct profile) that passes Gate 1 and Gate 2 for the `review` category, with headroom checked against the review median, and has a price. The decision file lists each would-be reviewer's first failing gate under `review-candidates` | `decide` |
| Call slots (6 per task) | **enforced**: `used + 1 <= limit` in `decide` and again in `dispatch` | `decide`, `dispatch` |
| Same-profile repairs (1 per task) | **enforced**: counted from the ledger by identity (harness, provider, model, effort, config); renaming a profile in the policy does not reset them | `decide`, `dispatch` |
| Reconcile first | **enforced**: `dispatch` refuses while an earlier dispatch of the task has no later outcome naming its dispatch seq, whatever profile either names, so two workers never own one task and no provider switch follows effects of unknown acceptance (SKILL.md 'Hard prohibitions', spec-v2 §7, §12). The other members of the same speculative decision are the only exception | `dispatch` |
| Deadline | **enforced**: `now` strictly before; capped at 12 h from the task's first ledger event | `decide`, `dispatch` |
| Pre-dispatch recheck | **enforced**: `dispatch` re-runs Gates 1-5 on the stored request with the current policy, `now` and project-stop state; the decided profile must still be eligible and still the route's choice, and the recomputed Brief must have the decided brief fingerprint, so the worker is never handed an allowance (calls, attempts, deadline, cash) that no longer matches the task (gates.md 'Qualification, freshness and pre-dispatch binding' items 3-4). A host deviation is bound the same way: it is handed the decided Brief, so its record carries that fingerprint, the same comparison refuses it when the Brief changed, and its same-profile repair status must match the decided profile's, since the Brief's `attempts` assume it (re-review finding R3-1). A decision record with no decision file behind it is unknown evidence and is refused | `dispatch` |
| Lead-direct profile | **enforced**: the lead profile is walked only as `direct`, eligible up to `direct-max-tokens` (Gate 5); `dispatch` refuses it as a delegated worker, `--deviation` or not | `decide`, `dispatch` |
| Isolation | **enforced as a lower bound**: `worktree+branch` for delegated work; a stronger requirement than the host's capability is denied at Gate 1 | `decide` |
| Cash | **advisory**: the conservative bound (tokens x output rate) is computed, recorded and printed, never a cap. The Uncertainty line always says `cash: estimate only, no host accounting (subscription); not a strict cap` | `decide` |
| Usage windows | **enforced when configured**: fresh reading required; projection against stop-at - lead-reserve in decide and dispatch. Gate 4 fails a candidate with no reading at or before `now`, a reading older than `reading-max-age-minutes`, a window reset since the reading, or a projection over any window's limit, counting the `usage-tokens` of every dispatch the reading does not hold (recorded after it, or in flight from before it). `dispatch` re-checks at its `--now` against the decision's `usage-tokens` and those dispatches (section 'Usage windows') | `decide`, `dispatch` |
| Unknown price | **enforced, by host choice**: a profile whose model has no price fails Gate 4 (`unknown price for <model>: the bound cannot be computed (no silent zero)`), though cash is not a cap here (friction item 15) | `decide` |
| Speculative and nested delegation | **off**: speculative needs the opt-in plus `uncertainty: "high"`; a nested opt-in is refused with a note, because this host cannot produce or enforce a NestedBrief (§14) | `decide` |
| Speculative shared budget | **enforced** when opted in: the decision record stores the set's `shared-budget.calls` as `speculative-calls`; `dispatch` refuses once the decision has that many dispatches, and refuses any profile outside the set, `--deviation` or not (spec-v2 §8.4) | `decide`, `dispatch` |
| Counters across task-id renames | **the lead's duty**: the adapter keys every counter by `taskId`, so a renamed task would start from zero. Never rename a task to get slots back (spec-v2 §11.9) | lead |

## Qualification table

Status of every row: **host-declared, reviewer: lead, expires 2027-01-15**. Rows whose qualifications host-policy-3
adds or changes, and the four profiles it adds, carry the reviewer `host-declared (lead) from calibration-1 and
calibration-2 grades` and `qualified-at` 2026-10-18; `cc-opus-high`, `cc-fable-high` and `cc-fable-xhigh` keep their
production qualifications, `qualified-at` and reviewer (`host-declared (lead), not independent`) and gain the entries. None of this is an independent review. Qualification is declared by the host, never inferred from price
or label (gates.md, 'Qualification, freshness and pre-dispatch binding').

### Qualification rules (the lead's, from host-policy-2)

1. A profile is qualified for a category only on evidence from a task representative of that category: a calibration
   cell whose task matches the category, or a recorded production outcome in it.
2. High-risk categories (`build-core`, `review`, `fix`) need two independent passes (two calibration runs, or one plus
   an accepted production outcome). Normal-risk categories need one.
3. A calibration fail in a category is recorded as such and blocks qualification for that category until two later
   passes. The learning loop's demotion rule stays as it is.
4. The pin task (a bounded red-first pin, no source change) represents the normal-risk category `pin-tests` (median
   120000 tokens; verification: lint, the new tests green, guard-removal proof, the lead reads the diff), not
   `build-tests`: units of that size are 250000-token engine journeys the pin does not represent.

So calibration run 1 (`trace/calibration-1/`, workflow run `wf_052c5f34-973`: twelve profiles, three graded tasks)
qualifies every pin PASS for `pin-tests`, and nothing else: one `fix` or `review` PASS is one pass of a high-risk
category, recorded and not qualifying. Each calibrated profile carries the run id and one grade entry per task in its
`evidence`, in the form `calibration-<n>: <category> PASS|FAIL (n=<k>)` (the adapter refuses another form, or a
category the policy does not have). The four review FAILs (`cc-haiku-low`, `cc-haiku-medium`, `cc-haiku-high`,
`cc-sonnet-high`) are recorded as fails, and under rule 3 they need two later review passes before any review
qualification. `cc-opus-high` and `cc-fable-high` keep their production qualifications and gain the calibration
entries. `headroom-tested` of a profile qualified from calibration-1 is its largest completed calibration run, rounded
up to the next thousand (the host-policy-1 basis: a 91k run gave 92000), and is never lowered. The rules are applied by
the lead when editing the policy. The adapter checks only the form of the entries; it does not count passes.

### How calibration run 2 was applied (host-policy-3)

Calibration run 2 (`trace/calibration-2/`, workflow run `wf_fe91e1d6-d78`, protocol preregistered upstream in
SmartRouter `docs/evidence/2026-10-17/claude-code-calibration-2/`) graded twelve profiles on pin and fix and fifteen
on review. Its review grade is three-valued by that protocol: PASS (both ground-truth findings), PARTIAL (one, and no
false blocking finding), FAIL. A PARTIAL is not a pass. With run 1 that gives two independent calibration passes for
several high-risk cells, and the lead applied rules 1-4:

- **Every pin PASS** (12 of 12) is a second `pin-tests` pass; those profiles were already qualified from run 1.
- **`fix`** (12 of 12 PASS, every one a second pass): qualified for `cc-haiku-low`, `cc-haiku-medium`,
  `cc-haiku-high`, `cc-sonnet-low`, `cc-sonnet-medium`, `cc-sonnet-high`, `cc-opus-medium` and `cc-fable-medium`.
- **`review`**: two passes qualify `cc-fable-medium`. Not qualified: the three `cc-haiku-*` profiles (two fails);
  `cc-sonnet-low` (a pass, then a PARTIAL); `cc-sonnet-medium` and `cc-opus-medium` (a pass, then a fail: under rule 3
  they need two later passes); `cc-sonnet-high` (a fail, then a pass: one more pass needed). The `cc-opus-medium`
  FAIL rests on one grader classification that the cross-candidate adjudication contests (G-1,
  `trace/calibration-2/lead-notes.md`); the preregistered rule stands for the score, and the adjudication is
  recorded in the profile's evidence, not applied.
- **New profiles.** `cc-opus-xhigh` (PASS on every task in both runs) is added with `pin-tests`, `fix` and `review`.
  `cc-sonnet-xhigh`, `cc-opus-max` and `cc-fable-max` ran the review only (one PASS each): they are added with
  `qualified-for: []` and that one entry, because one pass of a high-risk category is not a qualification.
- `cc-opus-high`, `cc-fable-high` and `cc-fable-xhigh` are unchanged and gain the entries.

Each calibrated profile carries the run-id entry `wf_fe91e1d6-d78 (calibration-2): ...` and one grade entry per task
it ran, in the form `calibration-<n>: <category> PASS|PARTIAL|FAIL (n=<k>)`. `PARTIAL` is a grade word the adapter
accepts from host-policy-3 on; any other word is refused. `headroom-tested` is the largest completed run, rounded up
to the next thousand, never lowered: a calibration run or an accepted production outcome (`cc-opus-high` stays at
771000 from the accepted sr-policy-2 outcome).

**The lead's note on `fix`.** The two calibration fix cells were single-finding fixes with the accepted finding text
given (110000-170000 tokens); a production fix round (`fix` median 193000) carries several findings. Rule 1 judges
the cell representative in kind. The size difference is held by three things: the `headroom-tested` guard
(`tokens < headroom-tested` at Gate 2), the category's required fresh re-review, and the learning loop's demotion
after two consecutive `verification-failed` outcomes.

**The routing consequence.** A default `fix` request (193000 tokens) fits only the fix-qualified profiles whose
headroom admits it: `cc-haiku-high` (261k), `cc-opus-xhigh` (246k), `cc-opus-high` (848k), `cc-fable-high` (352k)
(and the lead, whose direct path stops at 15k). Every other fix-qualified profile fails Gate 2 on its headroom. Each
delegate carries the same required review at `cc-opus-high` ($4.18 for the 209000-token review median) and $1.00 of
brief overhead, so the cheapest worker wins: **a default `fix` request now routes to `cc-haiku-high`**. `decide` on
that request with the live policy (feature-off derivative, as the tests use) prints:

```
Route:             delegate
Profile:           (cc-haiku-high, claude-code-workflow-subagent, anthropic, <model>, high, workflow-subagent/structured-output@1)
Reservations:      $5.28 conservative all-in bound, estimate only (work $0.10 + review $4.18 + brief overhead $1.00)
Gate walk (per candidate):
  cc-fable-xhigh   direct    gate 5: direct unsuitable: 193000 tokens > direct-max-tokens 15000
  cc-fable-max     delegate  gate 2: cc-fable-max not qualified for fix
  cc-fable-high    delegate  eligible, all-in $14.83
  cc-fable-medium  delegate  gate 2: context: 193000 tokens not below headroom-tested 172000 on cc-fable-medium
  cc-opus-max      delegate  gate 2: cc-opus-max not qualified for fix
  cc-opus-xhigh    delegate  eligible, all-in $9.04
  cc-opus-high     delegate  eligible, all-in $9.04
  cc-opus-medium   delegate  gate 2: context: 193000 tokens not below headroom-tested 154000 on cc-opus-medium
  cc-sonnet-xhigh  delegate  gate 2: cc-sonnet-xhigh not qualified for fix
  cc-sonnet-high   delegate  gate 2: context: 193000 tokens not below headroom-tested 183000 on cc-sonnet-high
  cc-sonnet-medium delegate  gate 2: context: 193000 tokens not below headroom-tested 128000 on cc-sonnet-medium
  cc-sonnet-low    delegate  gate 2: context: 193000 tokens not below headroom-tested 114000 on cc-sonnet-low
  cc-haiku-high    delegate  eligible, all-in $5.28
  cc-haiku-medium  delegate  gate 2: context: 193000 tokens not below headroom-tested 183000 on cc-haiku-medium
  cc-haiku-low     delegate  gate 2: context: 193000 tokens not below headroom-tested 175000 on cc-haiku-low
```

Gate 5's reason: `cc-haiku-high` has the lowest all-in bound among the four eligible delegates, $5.2765 (work
193000 x the output rate / 1e6 = $0.0965, review $4.18, overhead $1.00), against $9.04 for `cc-opus-high` and
`cc-opus-xhigh` and $14.83 for `cc-fable-high`. A fix estimated at 261000 tokens or more no longer fits
`cc-haiku-high` (or `cc-opus-xhigh`, 246k) and goes to `cc-opus-high` ($10.40 at 261000).

### The table (host-policy-3, generated from `host-policy.json`)

| Profile | Effort | Qualified for | Headroom tested | calibration-1 pin / fix / review | calibration-2 pin / fix / review | Basis |
|---|---|---|---|---|---|---|
| `cc-fable-xhigh` | xhigh, **direct only** (the lead), up to 15k tokens | build-core, build-ui, build-tests, review, fix, docs-mechanical, research-collect, pin-tests | 460k | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1 + calibration-2 |
| `cc-fable-max` | max | none | 230k | - / - / - | - / - / PASS | calibration-2 review only: one pass, not a qualification |
| `cc-fable-high` | high | review, fix, pin-tests | 352k | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1 + calibration-2 |
| `cc-fable-medium` | medium | review, fix, pin-tests | 172k | PASS / PASS / PASS | PASS / PASS / PASS | calibration-1 + calibration-2 |
| `cc-opus-max` | max | none | 307k | - / - / - | - / - / PASS | calibration-2 review only: one pass, not a qualification |
| `cc-opus-xhigh` | xhigh | review, fix, pin-tests | 246k | PASS / PASS / PASS | PASS / PASS / PASS | calibration-1 + calibration-2 (new in host-policy-3) |
| `cc-opus-high` | high | build-core, build-ui, build-tests, review, fix, research-collect, pin-tests | 848k | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1 + calibration-2; headroom from the accepted sr-policy-2 outcome (770527 tokens) |
| `cc-opus-medium` | medium | fix, pin-tests | 154k | PASS / PASS / PASS | PASS / PASS / FAIL | calibration-1 + calibration-2; review: a pass, then a FAIL (G-1 recorded, not applied) |
| `cc-sonnet-xhigh` | xhigh | none | 328k | - / - / - | - / - / PASS | calibration-2 review only: one pass, not a qualification |
| `cc-sonnet-high` | high | fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1 + calibration-2; review: a FAIL, then a pass |
| `cc-sonnet-medium` | medium | fix, pin-tests | 128k | PASS / PASS / PASS | PASS / PASS / FAIL | calibration-1 + calibration-2; review: a pass, then a FAIL |
| `cc-sonnet-low` | low | fix, pin-tests | 114k | PASS / PASS / PASS | PASS / PASS / PARTIAL | calibration-1 + calibration-2; review: a pass, then a PARTIAL |
| `cc-haiku-high` | high, no vision | fix, pin-tests | 261k | PASS / PASS / FAIL | PASS / PASS / FAIL | calibration-1 + calibration-2 |
| `cc-haiku-medium` | medium, no vision | fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / FAIL | calibration-1 + calibration-2 |
| `cc-haiku-low` | low, no vision | fix, docs-mechanical, pin-tests | 175k | PASS / PASS / FAIL | PASS / PASS / FAIL | session runs (host-policy-1) + calibration-1 + calibration-2 |

The session runs behind the host-policy-1 rows: `cc-fable-xhigh`, the lead's own direct fixes and integration units;
`cc-fable-high`, workflow runs `wf_1fcbe585-d1e` (U5 review 3, fix 3, re-review 3) and `wf_7f80ebc5-5a8` (U5 fix 4);
`cc-opus-high`, 302 completed dispatches (28 builds, 130 reviews, 39 fix rounds, 26 research runs), every unit at
ACCEPT within three fix rounds; `cc-haiku-low`, one mechanical extraction dispatch (91k tokens). Host-policy-3 adds
the four profiles the lead listed (`cc-opus-xhigh` and the review-only `cc-sonnet-xhigh`, `cc-opus-max`,
`cc-fable-max`), each with its siblings' config, tools, vision and context-tested. The exact model ids live in
`host-policy.json`. The `Profile:` line prints the full identity tuple
`(id, harness, provider, model, effort, config)`.

With the current prices the adapter routes `build-core`, `build-ui`, `build-tests` and `research-collect` to
`cc-opus-high` (no calibrated profile is qualified for any of them), `review` to `cc-opus-high` (`cc-opus-xhigh` ties
on the bound and loses on effort; `cc-fable-medium`'s 172k headroom is below the 209000-token review median), `fix` to
`cc-haiku-high` (above), and `docs-mechanical` and `pin-tests` to `cc-haiku-low`. Work of at most 15k tokens goes
direct to the lead.

**`pin-tests` routes to the cheapest qualified profile, `cc-haiku-low`.** A default pin (120000 tokens) has an
output-rate bound of $0.06 there (120000 x the output rate / 1e6), plus $1.00 of brief overhead at the lead's rate:
$1.06 all-in. No reviewer is added, because `pin-tests` names no review: every pin is verified mechanically (red before
the fix, green with it, the guard-removal proof, lint) and the lead reads the diff. The three profiles of that model
share the $1.06 bound, so Gate 5 ranks equal bounds by the lower output rate, then the **lower effort**, then the id:
calibration-1 measured fewer tokens at the lower effort for every model on every task (12 model-task pairs).
`cc-sonnet-low` (114k) is qualified, but its headroom is below a default pin, so a pin that size fails it at Gate 2.

### How to add evidence

1. A qualification run cannot go through `dispatch`: a profile not qualified for the category fails Gate 2, and
   `dispatch` refuses it even with `--deviation`. Running an unqualified profile on real work is a host policy
   that SmartRouter does not sanction (spec-v2 §12: "No dispatch on unknown ... capability"). The path this host
   uses is a **calibration run** outside SmartRouter routing: the same graded tasks for every profile, on past work
   with a known answer (calibration-1: the R16 finding), graded by the lead (friction item 14). Its grades go in
   `trace/calibration-<n>/observations.json`, never in the ledger.
2. Run `rate`. It prints one `CALIBRATION` line per profile and category with the pass, partial and fail counts
   across every calibration run, e.g. `CALIBRATION cc-sonnet-low review: 1 pass, 1 partial, 0 fail (calibration-1,
   calibration-2)`. It reads both observation formats: calibration-1 grades the review with the boolean
   `review-grade.score`, calibration-2 with the three-valued `review-grade.result` (PASS, PARTIAL or FAIL; any other
   value counts as ungraded, never as a pass). A task an observation does not carry (the review-only profiles' pin
   and fix) was not run and is not counted. It writes the counts under
   `calibration` in `trace/qualification-stats.json`, apart from the outcome stats. Calibration counts never make a
   proposal. Separately, three `accepted` outcomes for an unqualified (profile, category) produce a **qualification
   proposal**; such outcomes appear only if the lead records out-of-band runs in the ledger by hand, as dispatch
   records marked `deviation: true`.
3. The lead applies the qualification rules above and ratifies by editing `host-policy.json`: add the category to
   `qualified-for`, append the run ids and the `calibration-<n>: <category> PASS|PARTIAL|FAIL (n=<k>)` entries to `evidence`,
   set `qualified-at` to the ratification date, and set `expires` (at most three months out). Bump
   `policy-revision`. The decision files bind every decision to the policy digest, so old decisions stay readable.
   A decision not yet dispatched is rechecked against the edited policy at `dispatch`, so a demotion or a
   revocation takes effect on pending decisions too. When a revision changes what the goldens or the base tests
   assume, freeze the previous policy as `trace/policies/host-policy-<n>.json` and keep them on it (never in
   `trace/decisions/`, whose file names belong to decisions).
4. A profile with `qualified-at: null` or a past `expires` fails Gate 2 until this is done.

## The learning loop

`outcome` records go in, `rate` turns them into proposals, and the lead edits the policy. The adapter never
writes the policy.

- `rate` aggregates outcomes per (profile, category): accepted, verification-failed, partial, cost-overrun,
  cancelled, blocked, escalated, plus how many came from host deviations. It counts **one outcome per dispatch**:
  a later outcome record for the same dispatch supersedes the earlier one (spec-v2 §10.5, decision-trace.md §4),
  so recording a correction never double-counts. It writes `trace/qualification-stats.json`
  (`outcomes-counted` after supersession, `outcome-records` before), which is byte-identical when regenerated from
  the same ledger.
- It proposes **demotion** of a profile from a category after two consecutive `verification-failed` outcomes there
  since its `qualified-at`, or after any `cost-overrun`.
- It proposes **qualification** after three `accepted` outcomes in a category the profile is not qualified for.
  `dispatch` refuses such runs, so these outcomes can only come from runs the lead recorded by hand (see 'How to
  add evidence').
- It proposes a **`headroom-tested` raise** when an accepted outcome (the latest per dispatch) completed more tokens
  than its profile's current value:
  `PROPOSAL profiles.<id>.headroom-tested: <current> -> <tokens rounded up to the next thousand> (accepted outcome <task> completed <tokens> tokens); not applied — the lead ratifies by editing host-policy.json`.
  One proposal per profile, from its largest accepted run; unknown tokens propose nothing. It never moves a route:
  `decide` routes by `headroom-tested` as it stands. (The first sr-policy-3 decision was blocked on a stale
  headroom that nothing proposed: `cc-opus-high` had completed 770527 tokens at 514000.) The proposals are written
  under `headroom-proposals` in `qualification-stats.json`.
- It **flags** a profile whose `expires` falls within 14 days.
- It prints the **calibration evidence** next to the outcome stats, one `CALIBRATION` line per profile and category,
  read from every `trace/calibration-<n>/observations.json`, pass, partial and fail counted across runs (see 'How to
  add evidence'). These lines feed the lead's
  qualification rules, never a proposal: proposals stay outcome-based. An unreadable observations file stops `rate`
  with exit 4.
- Proposals are printed, never applied. Until the lead edits the policy, `decide` routes by the policy as it
  stands, and its Uncertainty line names every pending proposal for the chosen profile, e.g.
  `pending proposal (not applied): demote cc-opus-high from fix: 2 consecutive verification-failed (f-1, f-2)`.

- With usage windows configured, `rate` also derives **observed usage coefficients** from paired readings and
  proposes coefficient changes (section 'Usage windows').

MoonAliza the product gets the same loop later, through its Phase 6 advisory UI. That is out of scope here; this
adapter serves the build process only.

## Usage windows

This host runs on a Claude subscription. Its finite resource is not cash. It is two rolling usage windows, which
the platform reports on every turn as a `rate_limit_event`:

```
rate_limit_info.unifiedWindows = {
  "five_hour": { "resetsAt": 1792278000, "utilization": 0.2 },     // epoch seconds; 0..1
  "seven_day": { "resetsAt": 1792864800, "utilization": 0.05 }
}
```

(observed 2026-10-17T19:00:22Z: `five_hour` resets 2026-10-17T23:00:00Z, `seven_day` 2026-10-24T18:00:00Z). The
`usage-windows` block in `host-policy.json` turns the feature on. Without the block every decision says
`usage windows: not configured` in Uncertainty, and nothing here applies.

**The reading.** The lead reads the latest event with the `claude-code-remote` tool
`list_events(kinds=["rate_limit_event"])`. The adapter cannot call that tool. The lead pastes the event's
`rate_limit_info`, its bare `unifiedWindows`, or the normalised form
`{ "windows": { "<w>": { "utilization", "resets-at" } }, "note" }` into a file, then runs:

```
node docs/orchestration/smartrouter/route.mjs usage <reading.json> --now 2026-10-17T19:00:22Z
usage reading recorded: 2026-10-17T19:00:22Z five_hour 0.2 (resets 2026-10-17T23:00:00Z), seven_day 0.05 (resets 2026-10-24T18:00:00Z)
```

This appends `{ ts, windows: { <w>: { utilization, resets-at } }, source: "rate_limit_event", note }` to
`trace/usage.jsonl`. `ts` is the observation time: **pass `--now` with the `rate_limit_event`'s own timestamp**
(`2026-10-17T19:00:22Z` above), not the time of the paste. Every age, the 30-minute staleness included, is measured
from `ts`, so an event pasted 83 minutes after it happened is stale at once, as it should be. When `--now` is
omitted, `ts` is the clock, and `usage` says so on stderr:
`route.mjs: note: no --now, so the reading's ts is the clock (<ts>); pass --now <the rate_limit_event's own timestamp>, because staleness is measured from ts`. Only the windows the policy names are
recorded. Exit 2, with nothing appended, when:

- a policy window is missing from the reading;
- a utilization is not a number in [0, 1];
- a `resets-at` is not strictly after `ts`, or is more than one window length (`length-seconds`) after it. A rolling
  window cannot reset later than that, and the check catches epoch milliseconds pasted as seconds;
- `ts` is not after the previous reading's `ts` (readings are monotonic, like the ledger clock).

`route.mjs usage` with no file prints the latest reading, its age, and each window's headroom:

```
latest usage reading 2026-10-17T19:00:22Z (age 9.63 min, max 30)
  five_hour: utilization 0.2, resets 2026-10-17T23:00:00Z, headroom 9 Mtok ((0.9 - 0.25 - 0.2) / 0.05)
  seven_day: utilization 0.05, resets 2026-10-24T18:00:00Z, headroom 50 Mtok ((0.9 - 0.1 - 0.05) / 0.015)
```

**What refreshes a reading.** Only a new `route.mjs usage <reading.json>`. A reading is used by decisions whose `now`
is at most `reading-max-age-minutes` (30) after it. It stops counting for a window the moment that window's
`resets-at` passes: a reading from before a reset says nothing about the new window (fail-closed). When either
happens, `route.mjs usage` with no file reports it (`stale; refresh with route.mjs usage`, or
`reset since the reading`). A decision uses the latest reading at or before its own `now`, never a later one.

**The rule.** The standing rule (user, 2026-10-14) stops work at 0.90 of the weekly window, and this host applies
the same threshold to the five-hour window. Each window also keeps a `lead-reserve` for the lead's own work, which
no recorded sub-agent token counts: 0.25 of five_hour and 0.10 of seven_day since host-policy-3 (0.05 each before;
see 'Measured coefficients (run 2)'). Gate 4 runs after its call, repair, deadline and price checks, and
requires, in this order:

1. a reading exists at or before `now`, and `now - ts <= reading-max-age-minutes`. Otherwise it fails with
   `usage reading missing`, or `usage reading stale: age N min > 30; refresh with route.mjs usage`;
2. no window has reset since the reading (`now < resets-at` for each window). Otherwise:
   `usage window <w> reset at <iso> after the reading; refresh with route.mjs usage`;
3. for each window,
   `projected = utilization + ((dispatched + tokens) / 1e6) x utilization-per-mtok <= stop-at - lead-reserve`.
   `tokens` is the count the cash bound uses: the work alone for direct, and work + the required reviewer's
   median (for categories whose verification names a review) + `delegate-overhead-tokens` for a delegate.
   `dispatched` is the sum of the `usage-tokens` of every dispatch, of any task, recorded at or before `now` that
   the reading cannot hold in full:
   - a dispatch recorded after the reading's `ts`, finished or not: the reading cannot contain work dispatched
     after it;
   - a dispatch recorded at or before the reading's `ts` with no outcome at or before it: the unit was in flight
     when the reading was taken and keeps consuming after it. It counts at its **full** `usage-tokens`, which
     over-counts the part the reading already holds (the safe direction).
   A dispatch stops counting only at a reading taken at or after its outcome. A newer reading alone does not
   release a unit still running, and neither does an outcome alone. So record the outcome, then paste a fresh
   reading. Otherwise:
   `usage window <w>: projected P > S (stop-at X - lead-reserve Y); resets <iso>`, with
   ` (with N tokens dispatched and not in the reading)` after `P` when `dispatched` is not zero, followed by
   `; defer until the reset` when the window resets before the task deadline. A dispatch counted here with no
   `usage-tokens` (recorded while the feature was off) is unknown, and Gate 4 fails closed:
   `usage reading <ts> predates dispatch seq S of <task>, whose usage-tokens are unknown; refresh with route.mjs usage`
   for one recorded after the reading, and
   `usage reading <ts> does not hold dispatch seq S of <task> (in flight since <iso>, no outcome before the reading), whose usage-tokens are unknown; record its outcome, then refresh with route.mjs usage`
   for one in flight from before it.

A candidate that fails step 3 is ineligible, and Gate 5 ranks the remaining candidates. Every single delegate
projects the same tokens, so among single candidates only direct and delegate can differ here. In host-policy-1,
direct is the cheaper of the two whenever it is eligible (host-policy-2 too). `blocked` and every other route come out of the existing
flow unchanged.

A speculative set is the exception: both members are dispatched and run at once, so the set projects the **sum** of
its members' tokens (two delegates: twice one delegate's tokens), as its shared cash budget sums their cash. When the
sum does not fit, the route is not speculative: the best single candidate is chosen, and Uncertainty says
`uncertainty high; speculative not used (the set's summed usage projection, N tokens, does not fit: <step-3 reason>)`.
A speculative decision's `usage-tokens` is that sum, so `dispatch` re-checks the sum for each member.

The decision file carries
`usage: { reading-ts, reading-age-minutes, dispatched-not-in-reading-tokens, windows: { <w>: { utilization, resets-at, projected, headroom-mtok } } }`.
`projected` is the chosen profile's projection (the set's, for speculative), `null` when the route is blocked. It
also carries `usage-tokens`, the tokens projected for the chosen profile (the set's sum, for speculative). The decision ledger record carries `usage-tokens` as an additive
field. The Gate 4 note in the walkthrough names the binding window (`usage window five_hour binds: projected
0.2273 <= 0.65` for a default `build-core` unit against the reading above). Uncertainty says
`usage windows: coefficients host-declared (<coefficient-basis>)`.

`dispatch` re-checks steps 1-3 at its `--now`, against the decision's `usage-tokens` plus every dispatch the
reading does not hold, as in step 3 (other than the other members of the same speculative decision, which the decision's sum already
covers). A decision taken 25 minutes before can be stale by dispatch time, and the window can fill up in between:
two decisions taken against one reading cannot both be dispatched when only one fits. Each dispatch record carries
the additive field `usage-tokens` it commits (a speculative member: its share of the set's sum). A failing step refuses the dispatch
with exit 3 and the same reason text, e.g.
`usage check refused cc-opus-high (decision seq 1, usage-tokens 229000): usage reading stale: age 31 min > 30; refresh with route.mjs usage`.
The pre-dispatch recheck walks Gate 4 with the readings as well, so a host deviation is held to the windows too.

**Headroom.** `headroom-mtok = (stop-at - lead-reserve - utilization) / utilization-per-mtok - dispatched / 1e6`:
the million sub-agent tokens the window still admits after the dispatches the reading does not hold (step 3).
Against the reading above, five_hour admits (0.90 - 0.25 - 0.20) / 0.05 = 9 Mtok: sixteen default `build-core`
delegations (545k tokens each: 316k work + 209k review + 20k overhead; a seventeenth would bring the total to 9.265).
Gate 4 counts them: each dispatch lowers the headroom the next decision and dispatch see, and keeps lowering it
while it runs, across any number of newer readings, until a reading taken at or after its outcome. A delegation
that runs longer than `reading-max-age-minutes` therefore stays in the accounting through the refreshes the
staleness rule forces. seven_day admits (0.90 - 0.10 - 0.05) / 0.015 = 50 Mtok. `route.mjs usage` with no file
prints `dispatched and not in the reading: N tokens (A since the reading, B in flight from before it)` and
subtracts N from each window's headroom.

What the gate cannot see is the lead's own work, which is never dispatched. The `lead-reserve` is the margin for
that alone, and on this host it is the larger cost: run 2 measured about 0.40 of five_hour per hour of active lead
work, so the 0.25 reserve is about 40 minutes of it. In sub-agent terms the same 0.25 is 0.25 / 0.05 = 5 Mtok, more
than nine default `build-core` delegations (545k tokens = 0.0273 of the window each); the reserve is sized by the
lead's turns, not by delegations.

**Measured coefficients (run 2).** Host-policy-3 ratifies `utilization-per-mtok` from calibration run 2
(`wf_fe91e1d6-d78`), measured with the lead idle but for one check-in, from the readings in `trace/usage.jsonl` at
2026-10-17T23:22:51Z and 2026-10-18T01:23:32Z (nothing in flight at either end) over the run's 7,872,276 reported
sub-agent tokens:

| Window | Reading 23:22:51 | Reading 01:23:32 | Measured per Mtok | host-policy-2 | host-policy-3 (ratified) | lead-reserve |
|---|---|---|---|---|---|---|
| five_hour | 0.12 | 0.39 | 0.0343 | 0.24 (about 7x) | **0.05** | 0.05 -> **0.25** |
| seven_day | 0.28 | 0.36 | 0.0102 | 0.06 (about 6x) | **0.015** | 0.05 -> **0.10** |

The ratified values are about 1.5x the measured ones, rounded up: the conservative direction. Both windows carry
`ratified-at` 2026-10-18T01:23:32Z, so `rate` considers only later observations. Separately, lead-only work (no
sub-agent running) moved five_hour from 0.02 to 0.12 between 2026-10-17T23:07:08Z and 23:22:51Z: about 0.40 per hour
of active lead work. **The lead's own turns, not sub-agent tokens, are this host's dominant cost**, and the old 0.05
reserve covered about eight minutes of them; 0.25 covers about 40. `rate` could not learn any of this: the run was
not dispatched through the adapter, so every pair of readings during it had no recorded outcome tokens (`T` = 0,
skipped), and during ordinary work every pair spans a running unit (friction items 17 and 18). The gate's arithmetic
is unchanged. `route.mjs usage` against the committed readings, at 2026-10-18T01:45:00Z:

```
latest usage reading 2026-10-18T01:30:06Z (age 14.9 min, max 30)
  dispatched and not in the reading: 829000 tokens (829000 since the reading, 0 in flight from before it)
  five_hour: utilization 0.42, resets 2026-10-18T04:00:00Z, headroom 3.771 Mtok ((0.9 - 0.25 - 0.42) / 0.05 - 0.829 dispatched and not in the reading)
  seven_day: utilization 0.36, resets 2026-10-24T18:00:00Z, headroom 28.5043 Mtok ((0.9 - 0.1 - 0.36) / 0.015 - 0.829 dispatched and not in the reading)
```

**The coefficients before (host-policy-1 and -2, superseded).** `utilization-per-mtok` was host-declared from two
coarse observations:

- 2026-10-14 17:01 to 18:18: the weekly window went from 0.82 to 0.88 while about 1.06M recorded sub-agent tokens
  ran (the lead's own tokens unrecorded). That is 0.06 / 1.06 = 0.057 per Mtok, declared as **0.06** for
  `seven_day`.
- 2026-10-17 18:00 to 19:00 (both windows fresh at 18:00): `five_hour` reached 0.20 while `seven_day` reached 0.05,
  so the five-hour window moves about four times as fast. That gives **0.24** for `five_hour`.

The first observation divides by recorded sub-agent tokens only, while the lead's own unrecorded tokens moved the
window too, so it overstates the coefficient, which is the safe direction. The second fixes only the ratio between
the windows. A coefficient must be a finite number > 0: unknown is not allowed, because a window with no coefficient
cannot be projected.

**Learning the coefficients.** `rate` pairs consecutive readings. For each pair with no reset of the window between
them (same `resets-at`, not passed by the later reading), it computes
`observed = (u2 - u1) / (T / 1e6)`, where `T` sums the `tokens` of the outcome records with `ts` in `(ts1, ts2]`
(one outcome per dispatch). A pair is skipped and counted under `skipped` when any outcome in it has unknown tokens,
when `T` = 0 (only unrecorded tokens moved the window), or when utilization fell under one `resets-at`
(`negative-delta`: a rolling window shedding old usage, or a mistaken paste, says nothing about what the tokens
cost). `qualification-stats.json` gets
`usage: { <w>: { observed: [{ from, to, delta, tokens, coefficient }], max-observed, current, skipped } }`. `rate`
prints `PROPOSAL usage-windows.windows.<w>.utilization-per-mtok: <current> -> <max-observed>` when the maximum
observed exceeds the current by more than 10 % (upward at once: the conservative direction). It proposes a lower
value only when the last three observations are all below 90 % of the current, and then proposes the highest of
those three (downward slowly), and never a value <= 0, which the policy refuses. The lead ratifies by editing the policy, as for every other proposal.

**`ratified-at`.** Each window may carry `ratified-at` (ISO-8601): the time the lead last ratified its
coefficient. `rate` considers only observations whose later reading is after it for the upward maximum and
the three-in-a-row downward rule, so a ratified downward change is not followed by an upward proposal from
older history (re-review finding SW-5). Ratify by editing the coefficient and `ratified-at` together. Pairs
of readings with a unit in flight at either reading are skipped as `spanning` (SW-8): a unit's tokens are
recorded whole at its outcome, so such a pair cannot say what they cost.

## Policy findings (host-policy-3)

Found while building revision 3 (unit sr-policy-3). The lead decides.

1. **The suite was red at the start.** At `b525131` the suite gave 78 pass, 2 fail (cwd the unit's worktree):
   commit `490b7ed` raised `cc-opus-high` to 771000 in the policy only, while the README table said 514k and the
   host-policy-2 test computed the headroom from calibration runs alone. Fixed first, on its own commit: the README
   row says 771k and the test counts accepted ledger outcomes as completed runs, as the policy's definition does.
2. **The brief's headroom list was stale for `cc-opus-high`** ('514000 (unchanged)'). The policy has carried 771000
   since `490b7ed`; 'never lowered' keeps it.
3. **'Every entry this revision adds or changes'** was read as every qualification added or changed: the profiles
   whose `qualified-for` changed and the four new ones take `qualified-at` 2026-10-18 and the new reviewer. The
   three unchanged profiles keep theirs, because a new `qualified-at` would also restart their demotion streams
   (the learning loop counts outcomes since `qualified-at`).
4. **The review-only run-id entry** says `review graded ... a review-only profile in that run (no pin or fix cell)`
   rather than the brief's `pin, fix and review graded`, which would not be true of those three profiles.
5. **A default `fix` now goes to the cheapest model.** It is the policy's own economics under the lead's table and
   note on `fix`; the guards the note names (headroom, fresh re-review, demotion) are the only difference from a
   production-qualified worker. A lead who wants a size floor for `fix` would raise the category's median or pass a
   larger `estimatedTokens`.
6. **The usage-window tests moved to the host-policy-2 fixture.** SW-1 and SW-2 assumed host-policy-2's profile set
   (the speculative review pair was `cc-opus-high` + `cc-fable-high`; under host-policy-3 `cc-opus-xhigh` ties
   `cc-opus-high` and joins the pair), and the others its coefficients. They run on the frozen fixture unchanged;
   P2-4 and the two 'committed policy' tests stay on the live policy.

## Policy findings (host-policy-2)

Found while building revision 2 (unit sr-policy-2). The lead decides.

1. **Equal bounds at one model.** Rule 4 and the table qualify the three profiles of the cheapest model for
   `pin-tests`, and the bound prices them on the same tokens, so they tie at $1.06. The rule the adapter had
   (lower output rate, then alphabetical id) picked `cc-haiku-high`, the costliest of the three in tokens. Gate 5 now
   ranks the lower effort before the id (commit "Gate 5 ranks equal all-in bounds by lower effort"), on the
   calibration-1 token counts. That commit stands alone so the lead can ratify or revert it. The reviewer choice for
   the categories that need one still ranks by rate, then id: no two review-qualified profiles tie in host-policy-2.
2. **`headroom-tested` of `cc-haiku-low` rose from 92000 to 139000** on its calibration-1 runs (largest completed:
   138101 tokens, a review graded FAIL on its findings, not on its context). That resolves host-policy-1 finding 1
   below: a default `docs-mechanical` request now routes to `cc-haiku-low`. A pin needs it too: 120000 tokens are
   not below 92000.
3. **Two qualified profiles cannot take a default pin.** `cc-sonnet-low` (110k) and `cc-opus-medium` (115k) ran
   every calibration task below 120000 tokens, so their tested headroom is below the `pin-tests` median. They are
   more expensive than the `cc-haiku-*` profiles anyway; a later run with a larger pin would raise them.
4. **The adapter checks the form of the evidence, not the rules.** `validatePolicy` refuses a `qualified-for` or a
   `calibration-<n>:` entry naming an unknown category and a malformed grade entry. It does not count passes for
   rule 2 or rule 3: production passes live in the ledger and in the session's run journal, not in the policy, so a
   check over the policy alone would refuse a qualification the rules allow.
5. **The base tests moved to the fixture with the goldens.** Three base tests asserted host-policy-1 facts that
   revision 2 changes (`cc-sonnet-high` without a fingerprint, `cc-haiku-low` at 92000). They run on the
   host-policy-1 fixture, unchanged, and the live policy has its own tests.

## Policy findings (host-policy-1)

These were found while building the adapter. The lead decides.

1. **A default `docs-mechanical` request is blocked** (resolved in host-policy-2, finding 2 above). `cc-haiku-low` has `headroom-tested` 92000, which equals the
   category's `median-tokens` 92000. Gate 2 requires the estimate to be strictly below headroom, so a request
   without `estimatedTokens` fails on the only delegate qualified for that category, and the lead's direct path
   stops at 15k tokens. Reproduction: `decide` on a `docs-mechanical` request with no `estimatedTokens` prints
   `context: 92000 tokens not below headroom-tested 92000 on cc-haiku-low`. Either test haiku above 92k, or pass a
   real estimate.
2. **`tools: true` cannot attest a tool list.** Categories require named tools (`research-collect` needs
   `firecrawl`), but profiles declare a boolean. The adapter accepts `true` as covering every required tool, and
   checks a list when one is given. A per-profile tool list would make Gate 2's "required tools present" checkable.
3. **The hand-walked ledger records `cash-spent: 0.0`.** decision-trace.md §1 says missing billable usage is
   "`unknown`, never zero". The adapter writes `null` for both `cash-spent` and `cash-cap`. The lead's six initial
   lines keep `0.0` because the ledger is never rewritten.
4. **The hand walk for `cc-haiku-low` on a `review` request stopped at its first reason.** The adapter's Gate 2
   collects every reason, as the fixture runner's `run_gates` does, and also reports
   `context: 209000 tokens not below headroom-tested 92000`. The first failing gate (2) and the route are
   identical.
5. **The `gsi-u5-rereview4` dispatch (18:12) precedes its decision (18:40).** The decision was walked after the
   fact, and the dispatch is honestly marked as a host deviation. The adapter now refuses a `now` earlier than a
   task's latest event, so such a sequence cannot be produced through it.

## Friction log for SmartRouter upstream

Every point where the spec was ambiguous or did not fit a subscription host. Citations are to
`StepenkoAnatoli/SmartRouter@fbe7bca`.

1. **No cash accounting in subscription hosts.** gates.md Gate 4: "Strict caps additionally require a reliable
   conservative billable bound and reliable host accounting". A subscription with weekly token limits has neither
   per-call USD nor a cap to enforce. Yet spec-v2 §10.5 types `counters.cash-spent` and `cash-cap` as numbers, and
   §10.3 types `evidence.actual-spend` as a number. This host writes `null` for all three and reports cash as an
   estimate on every Uncertainty line. Upstream could add an `accounting: estimate-only` mode that types these
   fields as `number | null` and names the resource that *is* finite here (weekly tokens).
2. **What counts as one "original task" across iterative review rounds.** SKILL.md 'Closed feedback loop' and
   spec-v2 §7 allow "at most one same-profile corrective dispatch per original task". brief-and-result.md
   'Attempt, repair and ledger rules' forbids renewing the allowance "by restarting, renaming, changing profiles or
   escalating". This build runs review, fix and re-review rounds (U5 needed four fix rounds). If every round is one
   task, its 6 calls and 1 repair run out by the second fix round. If every round is a new task, the cap is renewed
   by renaming, which is forbidden. Neither spec-v2 nor host-task-id.md (non-normative, and about id format and
   uniqueness only) defines the boundary. This host uses one task id per dispatch unit (one build, one review, one
   fix round). Upstream should define whether a fresh review finding opens a new task.
3. **The README's dead link to `docs/HANDOFF_RESEARCH_KIT.md` is no longer present at `fbe7bca`.** Commit
   `56fe172` (2026-10-13, "Make routing autonomous and separate project scope") deleted the file together with the
   README row that linked it, and `git grep HANDOFF_RESEARCH_KIT` at `fbe7bca` finds nothing. This was carried as a
   known item from an earlier revision. It is recorded here as resolved upstream, not as an open defect.
4. **MaxNestingDepth has two numberings.** The Required output format (SKILL.md, spec-v2 §9) allows `<0 | 1 | 2>`.
   brief-and-result.md allows `max-nesting-depth: <1 | 2>` in the Brief. spec-v2 §10.4 says "a top-level Brief is
   depth 1". With nesting off, this host prints `MaxNestingDepth: 0` (the policy's value) and emits
   `"max-nesting-depth": 1` in the Brief, meaning the top level only. One numbering would remove the ambiguity.
5. **Tools are a boolean in the fixture runner.** gates.md Gate 2 asks for "required tools (active, not
   decorative)", but `tests/smart_router_decisions.py` models `Profile.tools: bool`, and no §10 object carries a
   profile's tool list. Policy finding 2 above follows from this.
6. **The direct bound is not specified.** gates.md Gate 5 says to compare "against the full direct bound". This
   host's builder brief sets the direct bound to the lead's rate on the tokens, without the required review that a
   delegate carries. That favours direct, which SmartRouter prefers anyway, but the asymmetry is the host's choice,
   not the spec's.
7. **Fingerprint expiry at equality.** gates.md 'Qualification, freshness and pre-dispatch binding' item 4 makes
   quote and deadline equality expiry, but says nothing explicit about capability-fingerprint freshness limits. The
   adapter applies the same rule: `now` equal to `expires` is stale.
8. **"Report the first failing gate and reason" vs collected reasons.** SKILL.md decision-flow step 3 asks for the
   first failing gate and reason, while the fixture runner's Gate 2 joins every capability reason into one string.
   The adapter reports the first failing gate with that gate's full reason.
9. **The speculative "hard shared budget" cannot be hard for cash here.** speculative-mode.md 'When It Is Used'
   condition 4 requires "a hard shared budget". Without accounting only the call half is enforceable. The adapter
   keeps speculative off by default (policy opt-in false) and, when opted in, enforces the calls and labels the
   cash `estimate-only`.
10. **Verification names have no schema link to acceptance checks.** gates.md Gate 3 requires the checks
    "available", but nothing ties a category's verification names to the `acceptance.checks` of §10.1. The adapter
    matches each name case-insensitively as a substring of a check's `command` or `expect`, which is documented
    here, not in the spec.
11. **Task id format.** host-task-id.md §1 (non-normative) specifies `^[0-9a-f]{4,16}$` and branch
    `sr/<task-id>/<slug>`. This host uses descriptive ids (`sr-host-build`) and `build/<unit-slug>` branches. The
    adapter accepts `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`, which is safe in file names. A hex id would be safer
    against collisions but unreadable in the run ledgers.
12. **Sameness includes the host profile id, which lets a rename renew a repair.** brief-and-result.md 'Attempt,
    repair and ledger rules' defines a same-profile repair by the tuple `(host-profile-id, harness, provider,
    model-id/revision, tool/output-config revision)`. Read literally, renaming a profile in the host policy makes
    the next dispatch a "different" profile and renews the repair. That contradicts SKILL.md 'Hard prohibitions'
    ("No reset of call/repair/attempt counters by restart, rename, or profile change") and spec-v2 §11.9. The
    adapter drops the host id from the sameness key. Upstream could state that the host id is a label, not part of
    sameness.
13. **`recommend-escalation` and the candidate set.** spec-v2 §5 defines `recommend-escalation` as "No current
    candidate is suitable; recommend a stronger eligible profile", which reads as reaching outside the candidates.
    The fixture-pinned semantics say the opposite: SKILL.md decision flow step 3 ("No eligible candidate ⇒ route is
    `blocked`"), 'Hard prohibitions' ("No empty-set resurrection"), gates.md Gate 5 ("do not fall back to a cheaper
    tier to avoid blocking"), and fixture E01's first leg in `tests/smart_router_decisions.py` (only C is a
    candidate, C fails Gate 2, expected `BLOCKED`). The fixture runner's `choose_route` never returns
    `recommend-escalation`, and the policy has no order of strength between profiles. The adapter follows the
    fixtures: an empty eligible set is `blocked`, and a would-be-eligible non-candidate is only a hint in
    Uncertainty. Upstream could say which profiles §5's "stronger eligible profile" may be drawn from, and add a
    fixture that reaches the route.
14. **No sanctioned path to qualification evidence.** gates.md Gate 2 and spec-v2 §11.10 require declared, tested
    qualification. §12 forbids dispatch on unknown capability, and §11.2 requires every gate decision to be
    enforced. So a host cannot route the first runs that would produce the evidence. The builder brief asked for a
    "qualification run" deviation; the adapter refuses it (review finding F3). Upstream could define a
    qualification mode, for example shadow runs whose output is never merged, with its own ledger kind.
15. **Unknown price without a strict cap.** gates.md Gate 4 says "Unknown or unbounded fees block a strict cap".
    The fixture runner checks price and accounting only under `if ctx.strict_cap is not None`. spec-v2 §12 reads
    "No dispatch on unknown permissions, identity, destination, capability, price or accounting under a strict
    cap", which can be read either way. This host has no strict cash cap, so the fixtures would let an unpriced
    profile through. The adapter still rejects it at Gate 4, as a deliberate host choice: Gate 5 ranks candidates
    by their all-in bound, and an unknown bound can neither be ranked honestly nor reported in Reservations. The
    other option, eligible but ranked after every priced candidate with 'unpriced' in Uncertainty, was set aside.
    It never matters while every profile is priced, and it would let a profile be chosen on a bound nobody can
    state. Every profile in host-policy-1 is priced. `validatePolicy` requires a price only for the lead-direct
    profile, so the reject is what keeps an unpriced profile out of routing. Upstream could say whether an unknown
    price blocks only a strict cap.
16. **Gate 4's budget has no place for a usage window.** gates.md Gate 4 and spec-v2 §10.1 type the budget as cash,
    calls and a deadline (`allowance: { cash, calls, deadline }`), and §10.5's `counters` carry cash, calls and
    repairs. On a subscription host the finite resource is a set of rolling usage windows (here five-hour and
    seven-day). Each has a utilization, a reset time and a host-learned tokens-to-utilization coefficient. Nothing
    in §10.1 or §10.5 carries a window, so this host enforces the windows in Gate 4 as a host check. It records
    them in additive fields: the decision's `usage` block, `usage-tokens` on the decision record, and `tokens` on
    the outcome record. Upstream could type a `windows` allowance, or a window counter in §10.5, next to cash.
    (The brief named this item 13. Item 13 was already taken, so it is 16.)
17. **`rate` cannot learn the usage coefficients on this host.** It pairs readings and divides by the outcome tokens
    recorded between them. Calibration run 2 was not dispatched through the adapter, so it recorded no outcome
    tokens and every pair during it had `T` = 0; and on a host where units overlap continuously every pair of
    readings is `spanning` (a unit in flight at either end) or `T` = 0, so the learning loop never gets a clean pair.
    The run-2 coefficients were measured by hand and ratified (host-policy-3). Upstream could add a
    `usage-observation` record (a pair of readings with a token count the lead attests), or let calibration runs be
    recorded as outcomes without a decision.
18. **The budget model does not see the lead.** The spec's budget is cash and tokens per dispatched unit. On a
    subscription host the lead's own turns dominate the usage windows (run 2: about 0.40 of the five-hour window per
    hour of active lead work, against 0.034 per million sub-agent tokens), and no record carries them; this host
    covers them with a `lead-reserve` sized by hand. Upstream could add a per-turn lead cost to the host model.
