# Holdshort host adapter (MoonAliza build process)

`route.mjs` is the host side of [Holdshort](https://github.com/StepenkoAnatoli/Holdshort) (pinned at `fbe7bca`,
skill 3.0.0) for this repository's build runs. Holdshort itself is a routing policy: advisory and stateless. It
says which route (direct, delegate, speculative, recommend-escalation, blocked), which profile (model and effort)
and which isolation apply to a unit of work, and why. The **host** is this adapter plus the lead session. The host
collects the inputs, enforces the decision, and keeps the Outcome Ledger. The adapter never dispatches anything
itself. Every output it prints carries `Advisory: recommendation only — no dispatch performed or claimed`.

| File | What it is |
|---|---|
| `host-policy.json` | The host's declared inputs: harness, authorization, accounting mode, prices, categories, profiles with qualification evidence, economics constants, opt-ins. Edited only by the lead. Current revision: `host-policy-6` (calibration-first evidence: every qualification backed by a typed evidence entry, section 'Calibration-first evidence'; difficulty tiers enforced since `host-policy-5`, section 'Difficulty tiers'). |
| `route.mjs` | The adapter: CLI plus named exports. Node built-ins only. |
| `route.test.mjs` | `node --test` suite, one test per Holdshort fixture it mirrors, plus the three golden hand-walked decisions. The base tests and the goldens run on `host-policy-1`, the usage-window and host-policy-2 tests on `host-policy-2`, the host-policy-3 tests on `host-policy-3`, the host-policy-4 tests on `host-policy-4`, the host-policy-5 tests on `host-policy-5` (the fixtures below), the live policy on its own tests. Since host-policy-6 the tests write the live policy's derivatives beside a copy of the committed store, because its typed references resolve against the policy file's directory. |
| `trace/ledger.jsonl` | The Outcome Ledger: spec-v2 §10.5 records, append-only, never rewritten. |
| `trace/decisions/<task>-<seq>.json` | One file per decision: the request, input and policy digests, the per-candidate gate walkthrough with reasons, the chosen profile, estimates vs accounting, the Brief. `hand-*.json` are the lead's hand-walked decisions from before the adapter existed. |
| `trace/policies/host-policy-1.json` | The policy before revision 2, byte-identical to the one the hand-walked decisions and `sr-policy-2-1` were decided under. A test fixture, never edited: the goldens decide against it with `--policy`. It lives apart from `trace/decisions/`, whose `<task>-<seq>.json` names belong to decisions (a fixture there would block a task named `host-policy` at seq 1). `sr-policy-2-1`'s Brief names the fixture's first path, `trace/decisions/host-policy-1.json`; the decision file is a record and is not rewritten. |
| `trace/policies/host-policy-2.json` | The policy before revision 3, byte-identical to the one the `sr-policy-3` decisions were bound to (sha256 `71e47f17...`). A test fixture, never edited: the host-policy-2 assertions and the usage-window tests run on it. |
| `trace/policies/host-policy-3.json` | The policy before revision 4, byte-identical to the one the `sr-policy-4` decisions were bound to (sha256 `43fc8d9a...`). A test fixture, never edited: the host-policy-3 assertions (its table, validation and routing, revision 3's routing consequence, its usage tests, `committed policy (ii)`) run on it, and the tests that read the ledger for it stop at its freeze instant (2026-10-18T09:07:43Z). |
| `trace/policies/host-policy-4.json` | The policy before revision 5 (untiered), byte-identical to the one the `sr-policy-5` decision was bound to (sha256 `36094c90...`). A test fixture, never edited: the host-policy-4 assertions (its table, its routing, run 3's routing consequence, its rate tests) and the tiers tests' enforced derivatives run on it; the tests that read the ledger for it stop at its freeze instant (2026-10-18T18:56:28.087Z). |
| `trace/policies/host-policy-5.json` | The policy before revision 6 (tiered, free-text production evidence), byte-identical to the one the `sr-policy-6` decisions were bound to (sha256 `47b14000...`). A test fixture, never edited: the host-policy-5 assertions (its table, its routing, the tiers section's routing consequence, its rate and dispatch tests) run on it. It carries no typed reference, so it loads from `trace/policies/`. |
| `trace/outcomes/<task>-<seq>.json` | The §10.3 Outcome objects that outcome records point at. Since host-policy-6 also the outcome store the policy's typed production references resolve against (section 'Calibration-first evidence'). |
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
   route to it. The adapter never emits `recommend-escalation` (friction item 13). Under host-policy-5 **declare the
   request's `difficultyTier`** by the rubric in 'Difficulty tiers': an undeclared tier reads T3 for `build-core`,
   `review` and `fix` and T2 for every other category, and several categories have no delegate qualified there.
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
   is the profile id or its exact identity tuple. The adapter adds `actual-spend-basis: "estimate-only"` to the
   stored copy when the Outcome has none or a `null` one (Holdshort Item 4). A supplied `"estimate-only"` is kept, and
   any other basis is refused (exit 2), because upstream `conform_spec.py` refuses it. Put the unit's total tokens in the additive
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
(the only way to reach `speculative`, and only with the host opt-in; it also raises the difficulty floor to T3), `requiredIsolation` (a lower bound on the
§6 lattice) and `difficultyTier` (`"T1" | "T2" | "T3"`, section 'Difficulty tiers'). Every command takes `--trace <dir>` and `--policy <file>`. `dispatch`, `outcome`, `rate` and `usage`
also take `--now <iso>`. `dispatch` requires `--project-stop <json>` and takes `--deviation <reason>`.

Exit codes: 0 done; 2 invalid input, including a `now` earlier than the task's latest ledger event (the task clock
is monotonic), a `difficultyTier` below the floor under an enforced policy, and a usage reading `usage` refuses; 3 refused; 4 ledger integrity (an unparseable or non-§10.5 line,
a seq gap, or a last line with no trailing newline; the same for an unparseable or unterminated `usage.jsonl`).
The adapter refuses to append to a ledger it cannot read; it never skips a line. When writing a
ledger line by hand, end it with a newline: the adapter refuses an unterminated last line rather than append onto
it, and the fix is to add the missing newline, which changes no record.

## Enforced vs advisory in this host

| Concern | Status | Where |
|---|---|---|
| Permissions, data classes, project stops | **enforced**: Gate 1 denies before anything else; a forbidden data class never reaches Gate 2. A request that declares no data class is invalid (exit 2): every dispatch transmits at least the objective and sources. `dispatch` re-walks Gate 1 with the project-stop state the lead passes as `--project-stop` (required), never with the snapshot taken at decide time | `decide`, `dispatch` |
| Capability qualification and fingerprint freshness | **enforced**: declared `qualified-for`, `qualified-at`, `expires`, `headroom-tested`; equality with `expires` is expiry | `decide` |
| Difficulty tier (host-policy-5) | **enforced** under `"difficulty-tiers": "enforced"`: a declared `difficultyTier` below the mechanical floor is exit 2; Gate 2 passes a profile only at the request's tier or above; the required reviewer is walked at `review@T1`; the tier is printed (`DifficultyTier`) and recorded on the decision, the Brief and the ledger decision record, so `dispatch`'s recheck binds it. Whether the declared tier is honest is **the lead's duty** (the rubric in 'Difficulty tiers') | `decide`, `dispatch`, lead |
| Verification prerequisites | **enforced**: every category check must be named in `acceptanceChecks`; a required review needs a reviewer drawn from the request's `candidates` (never the lead-direct profile) that passes Gate 1 and Gate 2 for the `review` category, with headroom checked against the review median, and has a price. The decision file lists each would-be reviewer's first failing gate under `review-candidates` | `decide` |
| Call slots (6 per task) | **enforced**: `used + 1 <= limit` in `decide` and again in `dispatch` | `decide`, `dispatch` |
| Same-profile repairs (1 per task) | **enforced**: counted from the ledger by identity (harness, provider, model, effort, config); renaming a profile in the policy does not reset them | `decide`, `dispatch` |
| Reconcile first | **enforced**: `dispatch` refuses while an earlier dispatch of the task has no later outcome naming its dispatch seq, whatever profile either names, so two workers never own one task and no provider switch follows effects of unknown acceptance (SKILL.md 'Hard prohibitions', spec-v2 §7, §12). The other members of the same speculative decision are the only exception | `dispatch` |
| Deadline | **enforced**: `now` strictly before; capped at 12 h from the task's first ledger event | `decide`, `dispatch` |
| Pre-dispatch recheck | **enforced**: `dispatch` re-runs Gates 1-5 on the stored request with the current policy, `now` and project-stop state; the decided profile must still be eligible and still the route's choice, and the recomputed Brief must have the decided brief fingerprint, so the worker is never handed an allowance (calls, attempts, deadline, cash) that no longer matches the task (gates.md 'Qualification, freshness and pre-dispatch binding' items 3-4). A host deviation is bound the same way: it is handed the decided Brief, so its record carries that fingerprint, the same comparison refuses it when the Brief changed, and its same-profile repair status must match the decided profile's, since the Brief's `attempts` assume it (re-review finding R3-1). A decision record with no decision file behind it is unknown evidence and is refused | `dispatch` |
| Lead-direct profile | **enforced**: the lead profile is walked only as `direct`, eligible up to `direct-max-tokens` (Gate 5); `dispatch` refuses it as a delegated worker, `--deviation` or not | `decide`, `dispatch` |
| Isolation | **enforced as a lower bound**: `worktree+branch` for delegated work; a stronger requirement than the host's capability is denied at Gate 1 | `decide` |
| Cash | **advisory**: the conservative bound (tokens x output rate) is computed, recorded and printed, never a cap. The Uncertainty line always says `cash: estimate only, no host accounting (subscription); not a strict cap` | `decide` |
| Cash markers (Holdshort Item 4) | **written**: Item 4 is accepted upstream (2026-10-18): a `null` cash counter or spend is conformant only beside its `estimate-only` marker. While `host-policy.json`'s `accounting.mode` is `"estimate-only"`, every record the adapter appends carries `counters["cash-basis"]: "estimate-only"` beside its `null` `cash-spent` and `cash-cap`. An Outcome whose `evidence.actual-spend` is `null` and that names no basis (absent or `null`) is stored (`trace/outcomes/<task>-<seq>.json`) with `evidence["actual-spend-basis"]: "estimate-only"`. A supplied `"estimate-only"` is kept, any other basis is refused (exit 2, the only value upstream accepts), a `null` basis is never stored, and a non-null spend gets no marker. The outcome record carries the stored basis as `actual-spend-basis`, beside `tokens`. Decision files and `status` keep the six §10.5 counters. The ledger is append-only, so lines written before the markers stay unmarked, and `conform_spec.py --record` keeps refusing them | `decide`, `dispatch`, `outcome` |
| Usage windows | **enforced when configured**: fresh reading required; projection against stop-at - lead-reserve in decide and dispatch. Gate 4 fails a candidate with no reading at or before `now`, a reading older than `reading-max-age-minutes`, a window reset since the reading, or a projection over any window's limit, counting the `usage-tokens` of every dispatch the reading does not hold (recorded after it, or in flight from before it). `dispatch` re-checks at its `--now` against the decision's `usage-tokens` and those dispatches (section 'Usage windows') | `decide`, `dispatch` |
| Unknown price | **enforced, by host choice**: a profile whose model has no price fails Gate 4 (`unknown price for <model>: the bound cannot be computed (no silent zero)`), though cash is not a cap here (friction item 15) | `decide` |
| Speculative and nested delegation | **off**: speculative needs the opt-in plus `uncertainty: "high"`; a nested opt-in is refused with a note, because this host cannot produce or enforce a NestedBrief (§14) | `decide` |
| Speculative shared budget | **enforced** when opted in: the decision record stores the set's `shared-budget.calls` as `speculative-calls`; `dispatch` refuses once the decision has that many dispatches, and refuses any profile outside the set, `--deviation` or not (spec-v2 §8.4) | `decide`, `dispatch` |
| Counters across task-id renames | **the lead's duty**: the adapter keys every counter by `taskId`, so a renamed task would start from zero. Never rename a task to get slots back (spec-v2 §11.9) | lead |

## Difficulty tiers (host-policy-5)

Host-policy-5 adopts Holdshort's difficulty-tiers proposal (`docs/proposals/difficulty-tiers.md` on Holdshort
main, PR #100, merged 2026-10-18 by the operator): Items 1-3 and 5 in the adapter and the policy. Item 4 (calibration
run 4, the T3 cells) is a later unit. The proposal is the specification; where it leaves a choice the lead's
decisions D1-D9 bind (section 'How the tiers proposal was applied'). The proposal's own status line still reads "draft
proposal, not normative" and says that until an independent review accepts it "hosts MUST NOT emit or require" its
fields; its review record shows revision 2 as `pending delta review`. This host emits and requires them anyway, on the
operator's decision to merge PR #100 without the delta review and the lead's D1-D9 (policy finding 7, friction item
22). A policy turns the rules on with the top-level
key `"difficulty-tiers": "enforced"`; any other value is invalid (exit 2), and without the key a policy is untiered
and the adapter behaves exactly as before: no `DifficultyTier` line, no `difficulty-tier` field, Gate 2 per category.
One exception: `rate` splits a calibration observation that carries a tier under any policy (D8, below).
The fixtures host-policy-1..4 are untiered, so every golden and every assertion on them is unchanged.

**The tier scale** (proposal Item 1, quoted). "Three tiers, the same names for every category, with **predicates per
category**: 'edit set' is meaningful for the building categories only, so each category defines its own T1 and T3
tests and T2 is what is neither. A tier is a property of the **request**, declared by the host and recorded. It is not
an estimate of tokens and not a price."

| Category | T1 (all hold) | T3 (any holds) |
|----------|---------------|----------------|
| `fix`, `build-core`, `build-ui`, `build-tests` | the edit set (`permitted-effects` minus the architecture map) is at most two files in one module; the cause, or the rule, is named in the request; the acceptance checks run on an existing harness | the edit set spans more than three files or more than one seam; the cause is unknown; the acceptance checks need a new harness; the edit set includes the code that handles credentials, persistence, concurrency or an external service (the data class alone does not trigger it); `uncertainty` is `high` |
| `pin-tests` | one rule, one existing harness, one test file | the rule spans two modules, or the harness does not exist (a fake, a recorder, a process boundary) |
| `review` | one module against its own specification section, with the shipped tests as the harness for reproductions | two or more modules and their seam, where a finding can exist only in the interaction; or no shipped harness for reproductions; or the specification is incomplete and the review must say what it would have to say |
| `research-collect` | the unknowns are enumerated and each names its owning page; the budget is under ten pages | an unknown with no known owning page; a contradiction between primary sources to resolve; a budget over thirty pages |
| `docs-mechanical` | always T1 | never |

"T2 is a request that is neither T1 nor T3 in its category."

**The request declares its tier; the adapter enforces a floor** (D3, proposal Item 1 rules 1-2). The request carries
`difficultyTier: "T1" | "T2" | "T3"` (any other value is exit 2, under any policy). The floor: `T3` when
`uncertainty` is `"high"` or the edit set has more than three entries; `T2` when it has exactly three; `T1`
otherwise; `docs-mechanical` is always `T1`. The edit set is `permittedEffects` without the entries ending in
`ARCHITECTURE.md`. The floor reads only those structural fields: the rest of the predicates (a named cause, an
existing harness, one seam) are the lead's to judge. A declared tier below the floor is an invalid request, naming
both and the reason:

```
route.mjs: invalid request: difficultyTier T1 is below the floor T3 (edit set of 5 files, more than three); a declared tier above the floor is accepted as given, one below it never
```

A declared tier at or above the floor is accepted as given: the host may know the task is harder than it looks, never
easier. An undeclared tier reads as the proposal's default, `T3` for a high-risk category (`build-core`, `review`,
`fix`) and `T2` for every other one, raised to the floor if the floor is higher. Under an untiered policy a
`difficultyTier` is checked for form only (no floor), and the Uncertainty line then carries `difficulty tiers: not
enforced by this policy`; nothing else changes.

**Gate 2 reads the tier** (D4, proposal Item 3). A profile passes for the request's category only when it holds the
category at the request's tier or above: a qualification at tier k covers every lower tier, and a bare entry reads
`@T1`. The reason names both, `<id> not qualified for <category>@<tier> (holds <category>@T<j>)`; a profile holding
nothing of the category keeps `<id> not qualified for <category>`. Nothing else in the gates changes. An empty
eligible set at the request's tier stays `blocked` (no new route, no `recommend-escalation`), and the existing hint
(`not among candidates: ... would pass all five gates`, the decision's `eligible-outside-candidates`) names a profile
outside the candidates that would pass (friction item 21).

**The required reviewer is walked at `review@T1`** (D5). The reviewer of a `build-*` or `fix` unit is chosen as
before, with Gates 1-2 for the `review` category at the review median. Under an enforced policy that walk requires
`review@T1`, whatever the unit's tier: the review of a unit is its own request when the lead dispatches it, with its
own declared tier. The alternative, walking the reviewer at the unit's tier, would block every T2 and T3 unit until a
`review@T2` or higher profile exists; the lead set it aside. The review the lead dispatches declares its own tier, and
under host-policy-5 a review above T1 has no delegate (below).

**Printed and recorded** (D6, proposal Item 1 rule 3). Under an enforced policy the decision text carries
`DifficultyTier: T<k>` directly after the unchanged `Difficulty` line (its enum stays `trivial | moderate |
high-or-ambiguous`), and `difficulty-tier` is recorded on the decision file's `decision`, on the Brief (additive,
spec-v2 §13; `conform_spec.check_brief` checks required keys only) and on the ledger decision record (additive, as
`usage-tokens` is). The Brief's field is inside its fingerprint, so `dispatch`'s pre-dispatch recheck binds the tier:
a decision made under host-policy-5 dispatches as decided. A decision taken under an untiered revision cannot be
dispatched under an enforced one: its recomputed Brief gains `difficulty-tier`, and `dispatch` refuses with `the
Brief changed since decision seq N; decide again (changed: difficulty-tier)`, even where the route is unchanged. Decide
such a task again. The ledger held no pending decision when host-policy-5 landed: at the base commit (`69b8e3f`)
every task's latest decision was blocked or followed by a dispatch (`sr-policy-3` seq 2 is a delegate decision with
no dispatch, superseded by seq 3, and `dispatch` acts only on a task's latest decision); the suite asserts it on the
ledger frozen at that commit.

**The learning loop and `rate`** (D7, D8). Under an enforced policy the outcome streams are per (profile, category,
tier): `qualification-stats.json` keys read `fix@T1`, the demotion proposal `demote <profile> from <category>@T<k>:
...` and the qualify proposal `qualify <profile> for <category>@T<k>: ...`. An outcome counts at the tier of the
decision its dispatch was made under; a decision without a tier (every one before host-policy-5) counts at `T1`. A
calibration observation's task object (`pin`, `fix`, `review`) may carry `"tier": "T2" | "T3"` (run 4 will); its
`CALIBRATION` line then reads `<category>@T<k>` and counts apart. Runs 1-3 carry none and print as before. The split
applies under any policy, tiered or not: an observation's tier is a fact of the cell, not of the policy, so under an
untiered policy a tiered observation also prints `<category>@T<k>` and is not counted in the bare line. Before
host-policy-5 such an observation counted in the bare line; no committed trace holds one, so no untiered output
changes (the lead may gate the split on an enforced policy instead, if D1 is read as overriding D8).

**The lead's declaration rubric.** Before declaring T1, the lead checks, per category (a request that fails a T1 check
is T2, and one that meets any T3 test in the table is T3):
- `fix`, `build-core`, `build-ui`, `build-tests`: the edit set is at most two files in one module; the objective names the cause or the rule; every acceptance check runs on a harness that already exists; the edit set holds no credential, persistence, concurrency or external-service code; `uncertainty` is not `high`.
- `pin-tests`: one rule, one test file, a harness that already exists (no new fake, recorder or process boundary).
- `review`: one module, reviewed against its own specification section, with the shipped tests as the harness for reproductions.
- `research-collect`: every unknown is enumerated with the page that owns it, and the budget is under ten pages.
- `docs-mechanical`: always T1, and declared: an undeclared request reads T2, which no delegate holds.

A request whose tier turned out wrong is a lesson for this rubric, recorded in the lead's notes, never an edit to the
ledger (proposal 'Non-goals').

**The re-declaration table** (D9, proposal Item 2 rule 2). Bare entries read `@T1`. That is the honest reading of the
calibration-derived qualifications, whose cells are T1 by the table above; for the production-derived ones
(`cc-opus-high`, `cc-fable-high`, `cc-fable-xhigh`) it would narrow them, so host-policy-5 re-declares each at the tier
of the units that produced it, as Item 1 would have declared them ("would be T<k> by the table": they were not declared
at the time, and they are sizing information, never calibration evidence). The three re-declared profiles take
`qualified-at` 2026-10-18 and keep the reviewer `host-declared (lead), not independent`.

| profile | entry | evidence line (in addition to the lines the profile already carries) |
|---|---|---|
| `cc-opus-high` | `build-core@T3` | `build-core@T3: pre-adapter units U1-U5 of github-sign-in (28 builds, RUN.md), multi-file units with new harnesses, would be T3 by the table; host-declared (lead), not independent` |
| `cc-opus-high` | `build-ui@T3` | `build-ui@T3: accepted outcomes sr-policy-2 seq 3, sr-policy-3 seq 5, sr-policy-4 seq 4 (five files), sr-ci-item4 seq 3 (nine files), would be T3 by the table` |
| `cc-opus-high` | `build-tests@T3` | `build-tests@T3: pre-adapter test units of U1-U5 (RUN.md), new harnesses (fakes, recorders), would be T3 by the table; host-declared (lead), not independent` |
| `cc-opus-high` | `review@T1` | `review@T1: accepted outcomes sr-host-review seq 3, sr-host-rereview1 seq 3, sr-host-rereview2 seq 3 (one module against gates.md with the shipped tests), would be T1 by the table; calibration-1..3 review PASS` |
| `cc-opus-high` | `fix@T2` | `fix@T2: accepted outcomes sr-host-fix1 seq 4, sr-host-fix2 seq 4 (three files, one module, cause named by the findings, existing harness), would be T2 by the table; two passes at T2 (rule 2.3)` |
| `cc-opus-high` | `research-collect@T2` | `research-collect@T2: 26 research runs this session (RUN.md), 20-page budgets with enumerated unknowns, would be T2 by the table (budget over ten pages); host-declared (lead), not independent` |
| `cc-opus-high` | `pin-tests` (bare) | unchanged (calibration-derived) |
| `cc-fable-high` | `fix@T2` | `fix@T2: U5 fix rounds 3 and 4 (wf_1fcbe585-d1e, wf_7f80ebc5-5a8; src/main/github-signin.ts, its tests and fixtures: three files, cause named by the findings), would be T2 by the table; host-declared (lead), not independent` |
| `cc-fable-high` | `review@T1` | `review@T1: U5 review and re-review rounds (wf_1fcbe585-d1e) and accepted outcome gsi-u5-rereview4 seq 3 (one module with the shipped tests), would be T1 by the table; calibration-1..3 review PASS` |
| `cc-fable-high` | `pin-tests` (bare) | unchanged |
| `cc-fable-xhigh` | every category it holds, `@T3` (`build-core@T3`, `build-ui@T3`, `build-tests@T3`, `review@T3`, `fix@T3`, `docs-mechanical@T3`, `research-collect@T3`, `pin-tests@T3`) | one line per entry: `<category>@T3: the lead-direct profile integrates every unit of every tier and fixes inline (U1-R11 d4c4bdb, U2-R15 d37652e); host-declared (lead), not independent; eligible only below direct-max-tokens` |
| `cc-haiku-high` | `fix` (bare) | the added line `fix-x2-1 seq 3 accepted (five files, src/main and tests), would be T3 by the table: one pass at T3, not a qualification (rule 2.3)` |
| every other profile | unchanged, bare | nothing added |

**The routing consequence** (host-policy-5). `decide` on the live policy (feature-off derivative, as the tests use;
the model id elided) prints, for a `fix` of 193000 tokens declared `T1`:

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T1
Route:             delegate
Profile:           (cc-haiku-high, claude-code-workflow-subagent, anthropic, <model>, high, workflow-subagent/structured-output@1)
Reservations:      $3.19 conservative all-in bound, estimate only (work $0.10 + review $2.09 + brief overhead $1.00)
```

The same as host-policy-4: `cc-haiku-high` holds `fix` bare (T1), and the required reviewer `cc-sonnet-xhigh` holds
`review` bare (T1). Declared `T2`, only the `fix@T2` holders pass, and `cc-opus-high` is the cheaper:

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T2
Route:             delegate
Profile:           (cc-opus-high, claude-code-workflow-subagent, anthropic, <model>, high, workflow-subagent/structured-output@1)
Reservations:      $6.95 conservative all-in bound, estimate only (work $3.86 + review $2.09 + brief overhead $1.00)
Gate walk (per candidate):
  cc-fable-xhigh   direct    gate 5: direct unsuitable: 193000 tokens > direct-max-tokens 15000
  cc-fable-max     delegate  gate 2: cc-fable-max not qualified for fix
  cc-fable-high    delegate  eligible, all-in $12.74
  cc-fable-medium  delegate  gate 2: cc-fable-medium not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 172000 on cc-fable-medium
  cc-opus-max      delegate  gate 2: cc-opus-max not qualified for fix
  cc-opus-xhigh    delegate  gate 2: cc-opus-xhigh not qualified for fix@T2 (holds fix@T1)
  cc-opus-high     delegate  eligible, all-in $6.95
  cc-opus-medium   delegate  gate 2: cc-opus-medium not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 154000 on cc-opus-medium
  cc-sonnet-xhigh  delegate  gate 2: cc-sonnet-xhigh not qualified for fix
  cc-sonnet-high   delegate  gate 2: cc-sonnet-high not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 183000 on cc-sonnet-high
  cc-sonnet-medium delegate  gate 2: cc-sonnet-medium not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 128000 on cc-sonnet-medium
  cc-sonnet-low    delegate  gate 2: cc-sonnet-low not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 114000 on cc-sonnet-low
  cc-haiku-high    delegate  gate 2: cc-haiku-high not qualified for fix@T2 (holds fix@T1)
  cc-haiku-medium  delegate  gate 2: cc-haiku-medium not qualified for fix@T2 (holds fix@T1); context: 193000 tokens not below headroom-tested 183000 on cc-haiku-medium
  cc-haiku-low     delegate  gate 2: cc-haiku-low not qualified for fix; context: 193000 tokens not below headroom-tested 175000 on cc-haiku-low
```

Undeclared, a `fix` reads `T3` (a high-risk category). No delegate holds `fix@T3`; `cc-fable-xhigh` does, as the
lead-direct profile, eligible only below `direct-max-tokens`, so it fails Gate 5:

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T3
Route:             blocked
Profile:           none — blocked
Reservations:      unknown/blocked
Gate walk (first failing gate and reason per candidate):
  cc-fable-xhigh   direct    gate 5: direct unsuitable: 193000 tokens > direct-max-tokens 15000
  cc-fable-max     delegate  gate 2: cc-fable-max not qualified for fix
  cc-fable-high    delegate  gate 2: cc-fable-high not qualified for fix@T3 (holds fix@T2)
  cc-fable-medium  delegate  gate 2: cc-fable-medium not qualified for fix@T3 (holds fix@T1); context: 193000 tokens not below headroom-tested 172000 on cc-fable-medium
  cc-opus-max      delegate  gate 2: cc-opus-max not qualified for fix
  cc-opus-xhigh    delegate  gate 2: cc-opus-xhigh not qualified for fix@T3 (holds fix@T1)
  cc-opus-high     delegate  gate 2: cc-opus-high not qualified for fix@T3 (holds fix@T2)
  cc-opus-medium   delegate  gate 2: cc-opus-medium not qualified for fix@T3 (holds fix@T1); context: 193000 tokens not below headroom-tested 154000 on cc-opus-medium
  cc-sonnet-xhigh  delegate  gate 2: cc-sonnet-xhigh not qualified for fix
  cc-sonnet-high   delegate  gate 2: cc-sonnet-high not qualified for fix@T3 (holds fix@T1); context: 193000 tokens not below headroom-tested 183000 on cc-sonnet-high
  cc-sonnet-medium delegate  gate 2: cc-sonnet-medium not qualified for fix@T3 (holds fix@T1); context: 193000 tokens not below headroom-tested 128000 on cc-sonnet-medium
  cc-sonnet-low    delegate  gate 2: cc-sonnet-low not qualified for fix@T3 (holds fix@T1); context: 193000 tokens not below headroom-tested 114000 on cc-sonnet-low
  cc-haiku-high    delegate  gate 2: cc-haiku-high not qualified for fix@T3 (holds fix@T1)
  cc-haiku-medium  delegate  gate 2: cc-haiku-medium not qualified for fix@T3 (holds fix@T1); context: 193000 tokens not below headroom-tested 183000 on cc-haiku-medium
  cc-haiku-low     delegate  gate 2: cc-haiku-low not qualified for fix; context: 193000 tokens not below headroom-tested 175000 on cc-haiku-low
```

A `fix` whose `permittedEffects` hold five files has the floor `T3`, so declaring it `T1` is the invalid request quoted
above. A `review` of 209000 tokens declared `T1` routes as under host-policy-4:

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T1
Route:             delegate
Profile:           (cc-sonnet-xhigh, claude-code-workflow-subagent, anthropic, <model>, xhigh, workflow-subagent/structured-output@1)
Reservations:      $3.09 conservative all-in bound, estimate only (work $2.09 + review $0.00 + brief overhead $1.00)
```

Undeclared, a `review` reads `T3`, which only the lead-direct profile holds: blocked, every delegate failing Gate 2
with `<id> not qualified for review@T3 (holds review@T1)` or `not qualified for review`:

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T3
Route:             blocked
Profile:           none — blocked
Reservations:      unknown/blocked
```

A `build-ui` request of 250000 tokens, undeclared, reads `T2` (normal risk); `cc-opus-high` holds `build-ui@T3`:

```
Difficulty:        moderate
DifficultyTier:    T2
Route:             delegate
Profile:           (cc-opus-high, claude-code-workflow-subagent, anthropic, <model>, high, workflow-subagent/structured-output@1)
Reservations:      $8.09 conservative all-in bound, estimate only (work $5.00 + review $2.09 + brief overhead $1.00)
```

A `docs-mechanical` request declared `T3` is above its `T1` floor, so it is accepted as declared. The only
`docs-mechanical@T3` holder is `cc-fable-xhigh`, direct only: at the 92000-token median the route is blocked
(`cc-haiku-low not qualified for docs-mechanical@T3 (holds docs-mechanical@T1)`); at 15000 tokens or fewer it is
`direct` to the lead.

```
Difficulty:        trivial
DifficultyTier:    T3
Route:             blocked
Profile:           none — blocked
Reservations:      unknown/blocked
```

So under host-policy-5 a T1 request routes as under host-policy-4, a `fix` or `research-collect` request at T2, and a
`build-*` request at T2 or T3, goes to `cc-opus-high`; a `fix`, `review`, `pin-tests` or `research-collect` request at
T3, and a `review`, `pin-tests` or `docs-mechanical` request at T2, is blocked until a calibration run qualifies a
profile there (run 4 adds T3 cells, not T2: a T2 request then routes to the cheapest profile qualified at T3). The default matters: an undeclared `pin-tests` or
`docs-mechanical` request reads `T2`, and every holder of those categories is bare (T1), so it is blocked; declared
`T1` it routes to `cc-haiku-low` as before. The lead declares every request's tier.

## Calibration-first evidence (host-policy-6)

Host-policy-6 adopts Item 1 of Holdshort's calibration-first onboarding proposal
(`docs/proposals/calibration-first-onboarding.md` on Holdshort main, PR #102, merged 2026-10-18 by the operator): no
hand-declared qualification. Every `qualified-for` entry is backed by a typed evidence entry, and the adapter's
validator resolves typed production references against the outcome store. Items 2-4 (the kit under one path, the
shared subject pack, the evidence-folder CI check and the generated qualification table) are upstream units that
follow. The proposal is the specification; where it leaves a choice the lead's decisions E1-E7 bind (section 'How
the onboarding proposal was applied'). Revision 5's difficulty tiers stay in force: the proposal's Item 1.4 says the
two proposals' re-declarations are one revision when both land; here they are two consecutive revisions, and this one
rewrites revision 5's production-derived entries into the typed form or drops them.

Like the tiers proposal, this one still opens with its draft status:

> Status: **draft proposal, not normative; revision 2 after the independent review of 2026-10-18 (Request Changes on c53cd77).** Nothing in `skills/` is amended by this document. If accepted after independent review (plan §15), the items below would become one additional host-policy validation rule, one new tools path holding the calibration kit, one evidence-folder contract with a CI check, and an additive host-policy field; until then hosts MUST NOT emit or require them.

and its review record ends with `| 1-5 (revision 2) | pending delta review | — | — |`. This host requires typed
evidence anyway, on the operator's decision to merge PR #102 and the lead's E1-E7 (policy finding 2 of host-policy-6;
friction item 22 applies to this proposal as it did to the tiers one).

**Two typed evidence forms** (E1). A profile's `evidence` may carry:

- (a) the **grade entry**, as before: `calibration-<n>: <category>[@T<k>] PASS|PARTIAL|FAIL (n=<k>)`, a tierless
  entry read `@T1`;
- (b) the **typed production reference**: `outcome: <task-id> <category>[@T<k>] accepted <ISO date> (<path>)`,
  optionally followed by `; <note>`. `<path>` is the outcome file the host writes, `trace/outcomes/<task>-<seq>.json`,
  relative to the policy file's directory, never to `--trace`, so a test's temp trace does not interfere and an
  upstream copy of the policy with its trace resolves. The path **cannot leave the policy file's directory**: a `..`
  that climbs out of it (`../x/trace/outcomes/...`, `trace/../../x/trace/outcomes/...`) or a symlink that points out
  of it is refused (exit 2, `<path> leaves the policy file's directory <dir>`), whether or not the file is there, so
  a store that is never committed with the policy, such as a temp trace, cannot back a qualification (sr-policy-6 fix
  round 1, F1); a `..` that stays inside is only a spelling. `<ISO date>` is a day, `YYYY-MM-DD`.

Any evidence line that starts `outcome:` is checked for form from the policy alone (the literal `accepted`, a tier
T1-T3, a category the policy has, a calendar day, a relative `/`-separated path naming `outcomes/<task-id>-<seq>.json`)
and then **resolved**: the file must lie inside the policy file's directory (F1), exist, parse as a §10.3 Outcome of
that task, be `accepted`, be owned by the referencing profile, be the **latest outcome record of its dispatch** (one
outcome per dispatch, spec-v2 §10.5 and decision-trace.md §4, the rule `rate` counts by: a later outcome record for
the same dispatch supersedes it whatever its value, and the reference is refused as `<path> is superseded by outcome
record <task> seq <n> (<value>) for the same dispatch (seq <d>)`; F2), have been recorded on that day (the Outcome's own `ts`, else its outcome record `<task> seq
<seq>` in the store's `ledger.jsonl`; this host's Outcomes carry no `ts`), and the task must have been decided in that
category (its decision file under the store's `decisions/`, as `categoryMap()` reads it). The tier on a reference is
the host's declaration: when the task's decision carries `difficulty-tier` the two must match; when it does not (every
decision before revision 5) any declared tier is accepted, and the line must then say `would be T<k> by the table`.
A bare reference reads T1. An unresolvable reference is an invalid policy: exit 2, the reason naming the profile and
the entry, from every command (`decide`, `dispatch`, `outcome`, `status`, `rate`, `usage`; E7).

**Supported entries** (E2). Under a policy that carries the top-level key `"evidence": "typed"` (the adopting switch,
in the shape of revision 5's `"difficulty-tiers"`; any other value is exit 2; absent, the old behaviour, so the
fixtures host-policy-1..5 load unchanged), every `qualified-for` entry `<category>[@T<k>]` (bare reads `@T1` under an
enforced-tiers policy, else untiered) needs at least one supporting evidence entry: a grade entry with PASS for that
category at tier >= k (a tierless grade entry is T1), or a production reference for it at tier >= k. A PARTIAL or FAIL
grade entry supports nothing. The validator still counts no passes (the lead's rules do); an entry with nothing typed
behind it is exit 2 naming the profile and the entry: `invalid policy: profile <id> qualified-for '<entry>' has no
typed evidence behind it (a PASS grade entry or an accepted outcome reference for <category> at T<k> or above; free
text supports nothing)`. Extra references that support no entry are allowed: they are the record. A new profile with
no evidence is valid only as `qualified-for: []` (the proposal's onboarding state: present, priced, unroutable).

**The lead-direct profile is exempt** (E3) from E2 (`economics.lead-direct-profile`, `cc-fable-xhigh`): its
qualifications are the operator's authorization of the lead's own inline work, not a capability claim about a
delegate, and dropping them would make `direct` unroutable for every bounded task. Its typed lines, if it had any,
would still be resolved. The proposal has no exemption clause (policy finding 3, friction item 23).

**Free text stays as prose** (E4). The existing free-text evidence lines ("302 completed dispatches ...",
"sr-policy-2 outcome accepted ...", revision 5's re-declaration lines) are kept as the record, but free text supports
nothing. Revision 6 rewrites each production-derived entry of revision 5 into form (b) where the outcome store holds
the outcome, and drops the entry where it does not (the proposal's Item 1.1 last sentence); the line of a dropped entry
stays as prose with the suffix `; entry dropped in host-policy-6 (no outcome row to reference)`.

**Revision 6** (E5) is revision 5 plus `"evidence": "typed"` and this table. Every changed profile carries
`qualified-at: 2026-10-18`.

| profile | entry | action |
|---|---|---|
| `cc-opus-high` | `build-ui@T3` | kept; references (each against a decision without a tier): `outcome: sr-policy-2 build-ui@T3 accepted 2026-10-17 (trace/outcomes/sr-policy-2-3.json); would be T3 by the table (five permitted files; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-policy-3 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-policy-3-5.json); would be T3 by the table (five permitted files; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-policy-4 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-policy-4-4.json); would be T3 by the table (five permitted files; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-ci-item4 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-ci-item4-3.json); would be T3 by the table (nine permitted files; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-policy-5 build-ui@T3 accepted 2026-10-18 (trace/outcomes/sr-policy-5-3.json); would be T3 by the table (six permitted files; the decision predates revision 5 and carries no tier)` |
| `cc-opus-high` | `review@T1` | kept (also supported by the calibration-1..3 review PASS, T1); references: `outcome: sr-host-review review@T1 accepted 2026-10-17 (trace/outcomes/sr-host-review-3.json); would be T1 by the table (one module against gates.md with the shipped tests; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-host-rereview1 review@T1 accepted 2026-10-17 (trace/outcomes/sr-host-rereview1-3.json); would be T1 by the table (one module against gates.md with the shipped tests; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-host-rereview2 review@T1 accepted 2026-10-17 (trace/outcomes/sr-host-rereview2-3.json); would be T1 by the table (one module against gates.md with the shipped tests; the decision predates revision 5 and carries no tier)` |
| `cc-opus-high` | `fix@T2` | kept; references: `outcome: sr-host-fix1 fix@T2 accepted 2026-10-17 (trace/outcomes/sr-host-fix1-4.json); would be T2 by the table (three files, one module, cause named by the findings; the decision predates revision 5 and carries no tier)`<br>`outcome: sr-host-fix2 fix@T2 accepted 2026-10-17 (trace/outcomes/sr-host-fix2-4.json); would be T2 by the table (three files, one module, cause named by the findings; the decision predates revision 5 and carries no tier)` |
| `cc-opus-high` | `pin-tests` | kept (the calibration grade entries) |
| `cc-opus-high` | `build-core@T3`, `build-tests@T3`, `research-collect@T2` | **dropped**: the units behind them (U1-U5, the research runs) predate the adapter and have no outcome rows; the revision-5 lines stay as prose with the dropped suffix |
| `cc-fable-high` | `review@T1` | kept; reference `outcome: gsi-u5-rereview4 review@T1 accepted 2026-10-17 (trace/outcomes/gsi-u5-rereview4-3.json); would be T1 by the table (one module with the shipped tests; the decision predates revision 5 and carries no tier)`, plus the calibration grade entries |
| `cc-fable-high` | `fix@T2` | **dropped to bare `fix`** (the calibration fix PASS x3 support `fix@T1`); the U5 fix-round line stays as prose with the dropped suffix |
| `cc-fable-high` | `pin-tests` | kept |
| `cc-fable-xhigh` | all | unchanged (E3) |
| `cc-haiku-high` | `fix`, `pin-tests` | kept (grade entries); the fix-x2-1 line rewritten in place as `outcome: fix-x2-1 fix@T3 accepted 2026-10-18 (trace/outcomes/fix-x2-1-3.json); would be T3 by the table: one pass at T3, not a qualification` |
| `cc-haiku-low` | `docs-mechanical` | **dropped**: the "one completed mechanical extraction dispatch" has no outcome row (its line stays as prose with the dropped suffix); `pin-tests` kept |
| every other profile | unchanged | calibration-derived: the validator finds every entry supported by its own PASS grade entries (asserted entry by entry) |

The "would be" notes give each decision's permitted-file count (`sr-policy-5`'s request named six files). Every
reference resolves against the committed store as it stands: `loadPolicy` on `host-policy.json` succeeds.

**Routing consequence** (E6). Under revision 6 no delegate holds `build-core`, `build-tests`, `research-collect` or
`docs-mechanical`. A request in those categories above `direct-max-tokens` (15000) is **blocked**: every delegate
fails Gate 2 with `<id> not qualified for <category>`, and the lead-direct profile fails Gate 5 on
`direct unsuitable: <n> tokens > direct-max-tokens 15000`; at 15000 tokens or fewer the lead takes it inline
(`direct`). A default `build-core` request (316000 tokens, undeclared, read `T3`):

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T3
Route:             blocked
Profile:           none — blocked
Reservations:      unknown/blocked
```

```
Gate walk (first failing gate and reason per candidate):
  cc-fable-xhigh   direct    gate 5: direct unsuitable: 316000 tokens > direct-max-tokens 15000
  cc-fable-max     delegate  gate 2: cc-fable-max not qualified for build-core; context: 316000 tokens not below headroom-tested 230000 on cc-fable-max
  cc-fable-high    delegate  gate 2: cc-fable-high not qualified for build-core
  cc-fable-medium  delegate  gate 2: cc-fable-medium not qualified for build-core; context: 316000 tokens not below headroom-tested 172000 on cc-fable-medium
  cc-opus-max      delegate  gate 2: cc-opus-max not qualified for build-core; context: 316000 tokens not below headroom-tested 307000 on cc-opus-max
  cc-opus-xhigh    delegate  gate 2: cc-opus-xhigh not qualified for build-core; context: 316000 tokens not below headroom-tested 246000 on cc-opus-xhigh
  cc-opus-high     delegate  gate 2: cc-opus-high not qualified for build-core
  cc-opus-medium   delegate  gate 2: cc-opus-medium not qualified for build-core; context: 316000 tokens not below headroom-tested 154000 on cc-opus-medium
  cc-sonnet-xhigh  delegate  gate 2: cc-sonnet-xhigh not qualified for build-core
  cc-sonnet-high   delegate  gate 2: cc-sonnet-high not qualified for build-core; context: 316000 tokens not below headroom-tested 183000 on cc-sonnet-high
  cc-sonnet-medium delegate  gate 2: cc-sonnet-medium not qualified for build-core; context: 316000 tokens not below headroom-tested 128000 on cc-sonnet-medium
  cc-sonnet-low    delegate  gate 2: cc-sonnet-low not qualified for build-core; context: 316000 tokens not below headroom-tested 114000 on cc-sonnet-low
  cc-haiku-high    delegate  gate 2: cc-haiku-high not qualified for build-core
  cc-haiku-medium  delegate  gate 2: cc-haiku-medium not qualified for build-core; context: 316000 tokens not below headroom-tested 183000 on cc-haiku-medium
  cc-haiku-low     delegate  gate 2: cc-haiku-low not qualified for build-core; context: 316000 tokens not below headroom-tested 175000 on cc-haiku-low
```

A `docs-mechanical` request declared `T1` (92000 tokens), which revision 5 routed to `cc-haiku-low` at $1.05:

```
Difficulty:        trivial
DifficultyTier:    T1
Route:             blocked
Profile:           none — blocked
Reservations:      unknown/blocked
```

A `build-tests` (250000) or `research-collect` (232000) request is blocked the same way, read `T2`. The remedy is
calibration, not production: **Run 4 gains one T1 host-pack cell for each of `build-core`, `build-tests`,
`research-collect` and `docs-mechanical`**, so that a profile can be qualified for them on graded evidence (one pass
for a normal-risk category, two for `build-core`, rule 2) and the lead ratifies it with the grade entries. Until then
those units are blocked or done by the lead inline; the consequence for the build run (RUN.md) is the lead's to
report. `fix` at T1 and T2, `review` at T1, `build-ui` undeclared and `pin-tests` at T1 route as under revision 5:
`cc-haiku-high` ($3.1865), `cc-opus-high` ($6.95), `cc-sonnet-xhigh` ($3.09), `cc-opus-high` ($8.09) and
`cc-haiku-low` ($1.06). A `fix` declared `T2` now has one eligible profile, because `cc-fable-high` holds a bare `fix`:

```
Difficulty:        high-or-ambiguous
DifficultyTier:    T2
Route:             delegate
Profile:           (cc-opus-high, claude-code-workflow-subagent, anthropic, <model>, high, workflow-subagent/structured-output@1)
Reservations:      $6.95 conservative all-in bound, estimate only (work $3.86 + review $2.09 + brief overhead $1.00)
```

with `cc-fable-high` failing Gate 2 on `cc-fable-high not qualified for fix@T2 (holds fix@T1)`.

## Qualification table

Status of every row: **host-declared, reviewer: lead, expires 2027-01-15**. The seven profiles whose qualifications
host-policy-4 adds or removes carry the reviewer `host-declared (lead) from calibration-1, calibration-2 and
calibration-3 grades` and `qualified-at` 2026-10-18. The other profiles whose qualifications host-policy-3 added or
changed keep `host-declared (lead) from calibration-1 and calibration-2 grades`; `cc-opus-high`, `cc-fable-high` and
`cc-fable-xhigh` keep their production qualifications and reviewer (`host-declared (lead), not independent`);
host-policy-5 re-declares those qualifications at the tier of the units that produced them, with `qualified-at`
2026-10-18 (section 'Difficulty tiers'). Host-policy-6 requires typed evidence behind every entry of every profile but
the lead-direct one: each production-derived entry is backed by typed references to accepted outcomes in the store, or
dropped (section 'Calibration-first evidence'). Every profile gains the entries of each run. None of this is an independent review. Qualification is declared by the host, never inferred from price
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
5. **Per (category, tier)** (host-policy-5; Holdshort `docs/proposals/difficulty-tiers.md` Item 2 rules 3-5,
   quoted). Rules 1-4 apply at each tier, and a bare entry reads `@T1`:
   > 3. The two-pass rule applies per (category, tier): a high-risk category needs two independent passes **at that
   > tier** (calibration cells of that tier, or an accepted production outcome whose request carried that tier).
   >
   > 4. A calibration FAIL or a `verification-failed` outcome at tier k is a fail for tier k and every higher tier of
   > the category, and blocks them until two later passes at that tier; lower tiers keep their standing. The learning
   > loop's demotion proposal (two consecutive `verification-failed` outcomes) moves from (profile, category) to
   > (profile, category, tier).
   >
   > 5. The return path after a block is **calibration, never production**: the two later passes come from kit cells
   > at that tier (or an accepted outcome at that tier on another host policy that still routes there). Production
   > routing on this host cannot grant them, because Gate 2 no longer routes the pair; so there is no deadlock, only a
   > cost: a blocked pair stays blocked until a calibration run includes it. The host's one same-profile repair
   > (R01-R03) is unaffected: it runs under the original allowance before any outcome is recorded and is not a fresh
   > decision.

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
Holdshort `docs/evidence/2026-10-17/claude-code-calibration-2/`) graded twelve profiles on pin and fix and fifteen
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

**The routing consequence (host-policy-3; host-policy-4 moves the reviewer, below).** A default `fix` request (193000 tokens) fits only the fix-qualified profiles whose
headroom admits it: `cc-haiku-high` (726k), `cc-opus-xhigh` (246k), `cc-opus-high` (1492k), `cc-fable-high` (352k)
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
`cc-opus-xhigh` and $14.83 for `cc-fable-high`. A fix estimated at 726000 tokens or more no longer fits
`cc-haiku-high` (or `cc-opus-xhigh`, 246k) and goes to `cc-opus-high` ($19.70 at 726000).

### How calibration run 3 was applied (host-policy-4)

Calibration run 3 (`trace/calibration-3/`, main run `wf_4e9ef48d-066` plus the supplementary run `wf_dbe29a64-3b2`
for the two cells void under amendment A-1; protocol preregistered upstream in Holdshort
`docs/evidence/2026-10-18/claude-code-calibration-3/`) graded twelve profiles on pin and fix (U1-R11 at `e68583c`,
history-less checkouts) and fifteen on review (U1-R8 + U1-R11 at `0e7a7f3`, a reachability-defined classification, a
preregistered three-lens adjudication). Final tally: pin 11 of 12, fix 12 of 12, review 15 of 15 PASS, no PARTIAL.
With runs 1 and 2 that gives second passes for several high-risk review cells, one pin fail, and the learning loop's
first demotion proposal from production outcomes. The lead applied rules 1-4 (unchanged); `rate` prints the counts.

| profile | review run 1 / 2 / 3 | pin run 3 | fix run 3 | host-policy-4 |
|---|---|---|---|---|
| `cc-haiku-low` | FAIL / FAIL / PASS | PASS | PASS | review: one of the two later passes rule 3 needs, not qualified. **`fix` removed** (demotion ratified, below). Keeps `docs-mechanical`, `pin-tests` |
| `cc-haiku-medium` | FAIL / FAIL / PASS | PASS | PASS | review: one of two later passes, not qualified. Unchanged otherwise |
| `cc-haiku-high` | FAIL / FAIL / PASS | PASS | PASS (supplementary run) | review: one of two later passes, not qualified. Unchanged otherwise |
| `cc-sonnet-low` | PASS / PARTIAL / PASS | PASS | PASS | **`review` added**: two independent passes (rule 2); the PARTIAL is neither a pass nor a fail and is recorded as such |
| `cc-sonnet-medium` | PASS / FAIL / PASS | PASS | PASS | review: one of the two later passes rule 3 needs after the fail, not qualified |
| `cc-sonnet-high` | FAIL / PASS / PASS | PASS | PASS | **`review` added**: two passes after the fail (rule 3 satisfied) |
| `cc-sonnet-xhigh` (review only) | - / PASS / PASS | - | - | **`review` added** (two passes) |
| `cc-opus-medium` | PASS / FAIL / PASS | PASS | PASS | review: one of two later passes, not qualified |
| `cc-opus-high` | PASS / PASS / PASS | PASS | PASS | unchanged; gains the entries |
| `cc-opus-xhigh` | PASS / PASS / PASS | PASS | PASS | unchanged; gains the entries |
| `cc-opus-max` (review only) | - / PASS / PASS | - | - | **`review` added** (two passes) |
| `cc-fable-medium` | PASS / PASS / PASS | **FAIL** | PASS | **`pin-tests` removed** (rule 3, below). Keeps `review`, `fix` |
| `cc-fable-high` | PASS / PASS / PASS | PASS | PASS | unchanged; gains the entries |
| `cc-fable-xhigh` | PASS / PASS / PASS | PASS | PASS | unchanged (lead-direct); gains the entries |
| `cc-fable-max` (review only) | - / PASS / PASS | - | - | **`review` added** (two passes) |

G-2 (lead-notes.md): two of the five adjudicated clusters rest on two prongs of the classification; under the full
definition the run-3 review of cc-haiku-medium and cc-haiku-high would be FAIL. The preregistered score (PASS) is
what the evidence entries record, and it changes nothing above (both profiles need two later passes either way).

- **The demotion is ratified.** `rate` proposed demoting `cc-haiku-low` from `fix` after two consecutive
  `verification-failed` production outcomes (fix-u7-r3 seq 4, fix-x2-2 seq 3): the learning loop's first demotion
  from production outcomes. Host-policy-4 removes `fix` from the profile, and its evidence records
  `demoted from fix 2026-10-18: ...; re-qualification needs two later passes`, which means two later passes dated
  after 2026-10-18. Its three calibration fix passes stay recorded; they do not outweigh the production failures.
  Under host-policy-4 `rate` no longer prints the proposal, because a demotion concerns a qualified profile, and the
  outcome stats keep both failures.
- **The pin block.** The run-3 pin FAIL of `cc-fable-medium` (an over-specified pin: red at the base and still red
  with the accepted fix, lead-notes.md) blocks `pin-tests` for `cc-fable-medium` until two later passes (rule 3). It
  keeps `review` and `fix`.
- **Entries.** Each profile gains the run-id entry `wf_4e9ef48d-066 (calibration-3): pin, fix and review graded in
  trace/calibration-3/ (results-table.md, observations.json)` and one grade entry per task it ran. For `cc-haiku-high`
  and `cc-haiku-low` the run-id entry adds `; fix (cc-haiku-high) and review (cc-haiku-low) from the supplementary run
  wf_dbe29a64-3b2 (amendment A-1)`. The three review-only profiles say `review graded ...; a review-only profile in
  that run (no pin or fix cell)`, as revision 3 wrote it (finding 2 below). The seven profiles whose qualifications
  change take `qualified-at` 2026-10-18 and the reviewer `host-declared (lead) from calibration-1, calibration-2 and
  calibration-3 grades`; the rest keep theirs. `expires` stays 2027-01-15.
- **`headroom-tested` raises nothing.** Every run-3 cell is below its profile's current figure (largest:
  `cc-sonnet-xhigh` review 227264 < 328000; `cc-opus-max` review 266339 < 307000; `cc-fable-max` review 189364 <
  230000; `cc-haiku-high` fix 142418 < 726000).

**The routing consequence.** Two defaults move, and so does the required reviewer. `cc-sonnet-xhigh` is now
review-qualified, and it is the cheapest review-qualified profile whose headroom (328k) admits the 209000-token review
median. So it becomes the required reviewer of every `build-core`, `build-ui`, `build-tests` and `fix` delegate:
$2.09 of review bound, where `cc-opus-high`'s was $4.18. This applies the existing reviewer rule (Gate 3, the
`review` category's median at the cheapest review-qualified candidate that passes Gates 1-2) to the table; no rule
changed. `cc-sonnet-low` and `cc-sonnet-high` are review-qualified too, but their headroom (114k, 183k) is below the
review median, so they fail Gate 2 for a default review and are never the reviewer.

A default `fix` request (193000 tokens) loses `cc-haiku-low` (demoted; its 175k headroom would have failed it anyway),
and `cc-haiku-medium`'s 183k does not admit it, so the cheapest eligible worker is still `cc-haiku-high`. The demotion
does change smaller fixes: a fix estimated below 175000 tokens, which host-policy-3 sent to `cc-haiku-low`, now goes
to `cc-haiku-medium`, the cheapest fix-qualified profile whose 183k headroom admits it (a 150000-token fix:
`cc-haiku-medium`, reviewer `cc-sonnet-xhigh`; pinned in the host-policy-4 routing test). `decide` on
that request with host-policy-4 (since revision 5 the `trace/policies/host-policy-4.json` fixture's feature-off
derivative, as the tests use) prints:

```
Route:             delegate
Profile:           (cc-haiku-high, claude-code-workflow-subagent, anthropic, <model>, high, workflow-subagent/structured-output@1)
Reservations:      $3.19 conservative all-in bound, estimate only (work $0.10 + review $2.09 + brief overhead $1.00)
Gate walk (per candidate):
  cc-fable-xhigh   direct    gate 5: direct unsuitable: 193000 tokens > direct-max-tokens 15000
  cc-fable-max     delegate  gate 2: cc-fable-max not qualified for fix
  cc-fable-high    delegate  eligible, all-in $12.74
  cc-fable-medium  delegate  gate 2: context: 193000 tokens not below headroom-tested 172000 on cc-fable-medium
  cc-opus-max      delegate  gate 2: cc-opus-max not qualified for fix
  cc-opus-xhigh    delegate  eligible, all-in $6.95
  cc-opus-high     delegate  eligible, all-in $6.95
  cc-opus-medium   delegate  gate 2: context: 193000 tokens not below headroom-tested 154000 on cc-opus-medium
  cc-sonnet-xhigh  delegate  gate 2: cc-sonnet-xhigh not qualified for fix
  cc-sonnet-high   delegate  gate 2: context: 193000 tokens not below headroom-tested 183000 on cc-sonnet-high
  cc-sonnet-medium delegate  gate 2: context: 193000 tokens not below headroom-tested 128000 on cc-sonnet-medium
  cc-sonnet-low    delegate  gate 2: context: 193000 tokens not below headroom-tested 114000 on cc-sonnet-low
  cc-haiku-high    delegate  eligible, all-in $3.19
  cc-haiku-medium  delegate  gate 2: context: 193000 tokens not below headroom-tested 183000 on cc-haiku-medium
  cc-haiku-low     delegate  gate 2: cc-haiku-low not qualified for fix; context: 193000 tokens not below headroom-tested 175000 on cc-haiku-low
```

Gate 5's reason: `cc-haiku-high` has the lowest all-in bound among the four eligible delegates, $3.1865 (work 193000
x the output rate / 1e6 = $0.0965, review $2.09 at `cc-sonnet-xhigh`, overhead $1.00), against $6.95 for
`cc-opus-high` and `cc-opus-xhigh` (equal bounds: the lower effort ranks first) and $12.74 for `cc-fable-high`.
A fix estimated at 726000 tokens or more no longer fits `cc-haiku-high` (or `cc-opus-xhigh`, 246k) and goes to `cc-opus-high` ($17.61 at 726000).

A default `review` request (209000 tokens) now routes to `cc-sonnet-xhigh`. A review names no further reviewer, so
its bound is the work at its own rate plus the brief overhead:

```
Route:             delegate
Profile:           (cc-sonnet-xhigh, claude-code-workflow-subagent, anthropic, <model>, xhigh, workflow-subagent/structured-output@1)
Reservations:      $3.09 conservative all-in bound, estimate only (work $2.09 + review $0.00 + brief overhead $1.00)
Gate walk (per candidate):
  cc-fable-xhigh   direct    gate 5: direct unsuitable: 209000 tokens > direct-max-tokens 15000
  cc-fable-max     delegate  eligible, all-in $11.45
  cc-fable-high    delegate  eligible, all-in $11.45
  cc-fable-medium  delegate  gate 2: context: 209000 tokens not below headroom-tested 172000 on cc-fable-medium
  cc-opus-max      delegate  eligible, all-in $5.18
  cc-opus-xhigh    delegate  eligible, all-in $5.18
  cc-opus-high     delegate  eligible, all-in $5.18
  cc-opus-medium   delegate  gate 2: cc-opus-medium not qualified for review; context: 209000 tokens not below headroom-tested 154000 on cc-opus-medium
  cc-sonnet-xhigh  delegate  eligible, all-in $3.09
  cc-sonnet-high   delegate  gate 2: context: 209000 tokens not below headroom-tested 183000 on cc-sonnet-high
  cc-sonnet-medium delegate  gate 2: cc-sonnet-medium not qualified for review; context: 209000 tokens not below headroom-tested 128000 on cc-sonnet-medium
  cc-sonnet-low    delegate  gate 2: context: 209000 tokens not below headroom-tested 114000 on cc-sonnet-low
  cc-haiku-high    delegate  gate 2: cc-haiku-high not qualified for review
  cc-haiku-medium  delegate  gate 2: cc-haiku-medium not qualified for review; context: 209000 tokens not below headroom-tested 183000 on cc-haiku-medium
  cc-haiku-low     delegate  gate 2: cc-haiku-low not qualified for review; context: 209000 tokens not below headroom-tested 175000 on cc-haiku-low
```

Gate 5's reason: `cc-sonnet-xhigh` has the lowest all-in bound among the six eligible delegates, $3.09 (work 209000 x
the output rate / 1e6 = $2.09, overhead $1.00), against $5.18 for `cc-opus-high`, `cc-opus-xhigh` and `cc-opus-max`
and $11.45 for `cc-fable-high` and `cc-fable-max`. In host-policy-3 the same request went to `cc-opus-high` at $5.18.
A review estimated at 328000 tokens or more no longer fits `cc-sonnet-xhigh` (or `cc-opus-max`, 307k) and goes to `cc-opus-high` ($7.56 at 328000).

The stored build request (`hand-sr-host-build.json`, `build-ui`) still routes to `cc-opus-high`, at $9.41 instead of
the golden's $11.50: the same work ($6.32) and overhead ($1.00), with the review at `cc-sonnet-xhigh`. The usage
projection is unchanged (545000 tokens), because Gate 4 counts the review median's tokens, not the reviewer's price.
Restricted to their own candidates, the demoted, blocked and one-later-pass profiles route `blocked` at Gate 2: a
`review` limited to `cc-haiku-low`, `cc-haiku-medium`, `cc-haiku-high`, `cc-sonnet-medium` and `cc-opus-medium`; a
`fix` limited to `cc-haiku-low`; a `pin-tests` request limited to `cc-fable-medium`.

### How the tiers proposal was applied (host-policy-5)

Unit sr-policy-5 applied Holdshort's difficulty-tiers proposal (section 'Difficulty tiers') under the lead's
decisions, which bind where the proposal leaves a choice:

- **D1.** Tiering is explicit per policy: `"difficulty-tiers": "enforced"` turns it on, any other value is exit 2, and
  absent means untiered, which behaves exactly as before. The fixtures host-policy-1..4 stay untiered; revision 5 is
  enforced.
- **D2.** A `qualified-for` entry is `<category>` or `<category>@T1|T2|T3`; a bare entry reads `@T1`; one entry per
  category on a profile (bare and tiered, or two tiers, is exit 2). The grade entry gains the optional tier,
  `calibration-<n>: <category>[@T<k>] PASS|PARTIAL|FAIL (n=<k>)`, tierless read `@T1`. Both forms load under an
  untiered policy too: the form is checked, the tier ignored.
- **D3.** The request's optional `difficultyTier`, the mechanical floor (uncertainty high or more than three files:
  T3; exactly three: T2; docs-mechanical always T1), a declared tier below it exit 2, the undeclared default T3 for a
  high-risk category and T2 otherwise, raised to the floor; untiered: form only, and the not-enforced clause.
- **D4.** Gate 2 reads the tier, with the reason `<id> not qualified for <category>@<tier> (holds <category>@T<j>)`;
  nothing else in the gates changes; the empty set stays `blocked`, the existing outside-candidates hint names who
  would pass.
- **D5.** The required reviewer is walked at `review@T1`.
- **D6.** `DifficultyTier` printed after `Difficulty`; `difficulty-tier` on the decision, the Brief and the ledger
  decision record; the dispatch recheck round-trips it; no pending decision at the base commit.
- **D7.** `categoryMap()` returns the category and the tier per task (a decision without one: T1); `learn()` keys its
  streams by (profile, category, tier); the proposals and the stats keys carry `@T<k>`; untiered output unchanged.
  One step past the per-task wording, by the builder's choice: an outcome counts at the tier of the decision its
  dispatch was made under, so a failed T1 dispatch followed by a raised-tier decision of the same task stays a T1
  failure (policy finding 3 below).
- **D8.** `rate`: the CALIBRATION lines of runs 1-3 keep their format; a task carrying `tier` T2 or T3 counts and
  prints apart as `<category>@T<k>`. The split applies under any policy, untiered included (D8 is unconditional; D1's
  "exactly as before" holds for every committed observation, none of which carries a tier).
- **D9.** Revision 5 is revision 4 plus the key and the re-declaration table; calibration-derived entries stay bare;
  headroom, categories, economics, prices, usage windows, harness, authorization, isolation and accounting untouched.

### How the onboarding proposal was applied (host-policy-6)

Unit sr-policy-6 applied Item 1 of Holdshort's calibration-first onboarding proposal (section 'Calibration-first
evidence') under the lead's decisions, which bind where the proposal leaves a choice:

- **E1.** Two typed evidence forms: the grade entry (as before) and the typed production reference
  `outcome: <task-id> <category>[@T<k>] accepted <ISO date> (<path>)`, the path relative to the policy file's directory,
  never to `--trace` (the proposal names the `--trace` store; E1 overrides it). Checked for form from the policy alone,
  then resolved: exists, an Outcome of that task, `accepted`, recorded that day (the Outcome's `ts`, else its outcome
  record), decided in that category (`categoryMap()`), the tier equal to a tiered decision's, or any tier with
  `would be T<k> by the table` against a pre-tier decision. One check beyond E1's list, by the builder's choice: the
  Outcome's `owner-profile` must be the referencing profile (policy finding 4). One from fix round 1 (F2): the
  outcome record must be the latest of its dispatch, as `rate` counts it. Unresolvable: exit 2 naming the entry.
- **E2.** `"evidence": "typed"` adopts the supported-entry rule: every `qualified-for` entry needs a PASS grade entry
  or an accepted reference for its category at its tier or above (untiered: of its category); PARTIAL and FAIL support
  nothing; extra references are allowed. Absent, the old behaviour; the fixtures host-policy-1..5 load unchanged.
- **E3.** The lead-direct profile is exempt from E2 (not from E1).
- **E4.** Free text stays as prose and supports nothing; revision 6 rewrites production-derived entries into references
  where the store holds the outcome and drops them where it does not, the dropped entries' lines suffixed.
- **E5.** Revision 6 is revision 5 plus the key and the lead's table (section 'Calibration-first evidence'); nothing else
  changes. One addition by the builder's choice: `cc-haiku-low`'s mechanical-extraction line, the prose behind the
  dropped `docs-mechanical`, carries the dropped suffix too.
- **E6.** No delegate holds `build-core`, `build-tests`, `research-collect` or `docs-mechanical`; such a request above
  `direct-max-tokens` is blocked until run 4's T1 host-pack cells qualify a profile; `fix` at T1 and T2, `review` at T1,
  `build-ui` undeclared and `pin-tests` at T1 route as under revision 5 (asserted with `decide`).
- **E7.** `status`, `rate`, `decide` and `dispatch` (and `outcome`, `usage`) load the policy through `loadPolicy`, so
  they all validate; no new command or flag. A `qualify` proposal's `PROPOSAL` line now ends with
  `; typed evidence to paste: "<line>", ...`: one typed reference per accepted outcome behind it (the decision's tier
  when it declares one, else bare), JSON strings ready for the `evidence` array, resolvable as pasted; the stats file
  carries them as `references`. When the outcome store (`--trace`) is outside the policy file's directory, no
  reference to it could resolve (E1, F1), so the line ends instead with `; no typed evidence to paste: the outcome
  store <dir> is outside the policy file's directory <dir>, and a reference cannot leave it (E1)` and the proposal
  carries no `references`.

### The table (host-policy-6, generated from `host-policy.json`)

| Profile | Effort | Qualified for | Headroom tested | calibration-1 pin / fix / review | calibration-2 pin / fix / review | calibration-3 pin / fix / review | Typed references | Basis |
|---|---|---|---|---|---|---|---|---|
| `cc-fable-xhigh` | xhigh, **direct only** (the lead), up to 15k tokens | build-core@T3, build-ui@T3, build-tests@T3, review@T3, fix@T3, docs-mechanical@T3, research-collect@T3, pin-tests@T3 | 460k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | - | session runs (host-policy-1) + calibration-1, -2, -3; every entry @T3 (host-policy-5); exempt from the typed-evidence rule (E3: the lead's own inline work) |
| `cc-fable-max` | max | review | 230k | - / - / - | - / - / PASS | - / - / PASS | - | calibration-2 + calibration-3 review only: two passes |
| `cc-fable-high` | high | review@T1, fix, pin-tests | 352k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | gsi-u5-rereview4 review@T1 | calibration-1, -2, -3; host-policy-6: `fix@T2` dropped to bare `fix` (the U5 fix rounds have no outcome row), `review@T1` backed by the gsi-u5-rereview4 outcome and the calibration PASSes |
| `cc-fable-medium` | medium | review, fix | 172k | PASS / PASS / PASS | PASS / PASS / PASS | FAIL / PASS / PASS | - | calibration-1, -2, -3; `pin-tests` blocked by the run-3 pin FAIL until two later passes (rule 3) |
| `cc-opus-max` | max | review | 307k | - / - / - | - / - / PASS | - / - / PASS | - | calibration-2 + calibration-3 review only: two passes |
| `cc-opus-xhigh` | xhigh | review, fix, pin-tests | 246k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | - | calibration-1, -2, -3 |
| `cc-opus-high` | high | build-ui@T3, review@T1, fix@T2, pin-tests | 1492k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | sr-policy-2 build-ui@T3, sr-policy-3 build-ui@T3, sr-policy-4 build-ui@T3, sr-ci-item4 build-ui@T3, sr-policy-5 build-ui@T3, sr-host-review review@T1, sr-host-rereview1 review@T1, sr-host-rereview2 review@T1, sr-host-fix1 fix@T2, sr-host-fix2 fix@T2 | calibration-1, -2, -3; headroom from the accepted sr-policy-5 outcome (1029194 tokens); host-policy-6: `build-ui@T3`, `review@T1`, `fix@T2` backed by accepted outcomes; `build-core@T3`, `build-tests@T3`, `research-collect@T2` dropped (pre-adapter units, no outcome row) |
| `cc-opus-medium` | medium | fix, pin-tests | 154k | PASS / PASS / PASS | PASS / PASS / FAIL | PASS / PASS / PASS | - | calibration-1, -2, -3; review: PASS, FAIL, PASS - one of the two later passes rule 3 needs (G-1 recorded, not applied) |
| `cc-sonnet-xhigh` | xhigh | review | 328k | - / - / - | - / - / PASS | - / - / PASS | - | calibration-2 + calibration-3 review only: two passes |
| `cc-sonnet-high` | high | review, fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / PASS | PASS / PASS / PASS | - | calibration-1, -2, -3; review: FAIL, PASS, PASS - two passes after the fail |
| `cc-sonnet-medium` | medium | fix, pin-tests | 128k | PASS / PASS / PASS | PASS / PASS / FAIL | PASS / PASS / PASS | - | calibration-1, -2, -3; review: PASS, FAIL, PASS - one of the two later passes rule 3 needs |
| `cc-sonnet-low` | low | review, fix, pin-tests | 114k | PASS / PASS / PASS | PASS / PASS / PARTIAL | PASS / PASS / PASS | - | calibration-1, -2, -3; review: PASS, PARTIAL, PASS - two passes |
| `cc-haiku-high` | high, no vision | fix, pin-tests | 726k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | fix-x2-1 fix@T3 | calibration-1, -2, -3; headroom from the accepted fix-x2-1 outcome (725422 tokens); review: FAIL, FAIL, PASS - one of two later passes; the fix-x2-1 reference is one pass at T3, not a qualification |
| `cc-haiku-medium` | medium, no vision | fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | - | calibration-1, -2, -3; review: FAIL, FAIL, PASS - one of two later passes |
| `cc-haiku-low` | low, no vision | pin-tests | 175k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | - | calibration-1, -2, -3; `fix` demoted 2026-10-18 (two consecutive verification-failed outcomes); host-policy-6: `docs-mechanical` dropped (the mechanical extraction dispatch has no outcome row); review: FAIL, FAIL, PASS |

Every delegate entry above is backed by typed evidence: a PASS grade entry at its tier, or a typed reference (the
"Typed references" column, `<task> <category>@<tier>`). With the current prices and host-policy-6 the adapter routes,
at the request's declared tier, `build-ui` (any tier) to `cc-opus-high`, `review` at T1 to `cc-sonnet-xhigh`, `fix` at
T1 to `cc-haiku-high` and at T2 to `cc-opus-high` (its only holder at T2), and `pin-tests` at T1 to `cc-haiku-low`; a
`build-core`, `build-tests`, `research-collect` or `docs-mechanical` request above 15k tokens is blocked (no delegate
holds them; section 'Calibration-first evidence'), as are the T2 and T3 requests revision 5 blocked. Work of at most
15k tokens goes direct to the lead.

### The table (host-policy-5, history: the `trace/policies/host-policy-5.json` fixture)

Revision 5's table, kept as the record of what revision 6 rewrote or dropped (its test reads the fixture).

| Profile | Effort | Qualified for | Headroom tested | calibration-1 pin / fix / review | calibration-2 pin / fix / review | calibration-3 pin / fix / review | Basis |
|---|---|---|---|---|---|---|---|
| `cc-fable-xhigh` | xhigh, **direct only** (the lead), up to 15k tokens | build-core@T3, build-ui@T3, build-tests@T3, review@T3, fix@T3, docs-mechanical@T3, research-collect@T3, pin-tests@T3 | 460k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3; host-policy-5: every entry re-declared @T3 (the lead integrates every unit of every tier, direct only) |
| `cc-fable-max` | max | review | 230k | - / - / - | - / - / PASS | - / - / PASS | calibration-2 + calibration-3 review only: two passes (review new in host-policy-4) |
| `cc-fable-high` | high | review@T1, fix@T2, pin-tests | 352k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3; host-policy-5: fix @T2, review @T1 re-declared from the U5 rounds |
| `cc-fable-medium` | medium | review, fix | 172k | PASS / PASS / PASS | PASS / PASS / PASS | FAIL / PASS / PASS | calibration-1, -2, -3; `pin-tests` blocked by the run-3 pin FAIL until two later passes (rule 3) |
| `cc-opus-max` | max | review | 307k | - / - / - | - / - / PASS | - / - / PASS | calibration-2 + calibration-3 review only: two passes (review new in host-policy-4) |
| `cc-opus-xhigh` | xhigh | review, fix, pin-tests | 246k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | calibration-1, -2, -3 |
| `cc-opus-high` | high | build-core@T3, build-ui@T3, build-tests@T3, review@T1, fix@T2, research-collect@T2, pin-tests | 1030k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3; headroom from the accepted sr-policy-3 outcome (847844 tokens); host-policy-5: build-core, build-ui, build-tests @T3, fix and research-collect @T2, review @T1 re-declared from the production units |
| `cc-opus-medium` | medium | fix, pin-tests | 154k | PASS / PASS / PASS | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; review: PASS, FAIL, PASS - one of the two later passes rule 3 needs (G-1 recorded, not applied) |
| `cc-sonnet-xhigh` | xhigh | review | 328k | - / - / - | - / - / PASS | - / - / PASS | calibration-2 + calibration-3 review only: two passes (review new in host-policy-4) |
| `cc-sonnet-high` | high | review, fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / PASS | PASS / PASS / PASS | calibration-1, -2, -3; review: FAIL, PASS, PASS - two passes after the fail (review new in host-policy-4) |
| `cc-sonnet-medium` | medium | fix, pin-tests | 128k | PASS / PASS / PASS | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; review: PASS, FAIL, PASS - one of the two later passes rule 3 needs |
| `cc-sonnet-low` | low | review, fix, pin-tests | 114k | PASS / PASS / PASS | PASS / PASS / PARTIAL | PASS / PASS / PASS | calibration-1, -2, -3; review: PASS, PARTIAL, PASS - two passes (review new in host-policy-4) |
| `cc-haiku-high` | high, no vision | fix, pin-tests | 726k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; headroom from the accepted fix-x2-1 outcome (725422 tokens); review: FAIL, FAIL, PASS - one of two later passes; host-policy-5: fix-x2-1 recorded as one pass at T3, not a qualification |
| `cc-haiku-medium` | medium, no vision | fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; review: FAIL, FAIL, PASS - one of two later passes |
| `cc-haiku-low` | low, no vision | docs-mechanical, pin-tests | 175k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3; `fix` demoted 2026-10-18 (two consecutive verification-failed outcomes); review: FAIL, FAIL, PASS |

The session runs behind the host-policy-1 rows: `cc-fable-xhigh`, the lead's own direct fixes and integration units;
`cc-fable-high`, workflow runs `wf_1fcbe585-d1e` (U5 review 3, fix 3, re-review 3) and `wf_7f80ebc5-5a8` (U5 fix 4);
`cc-opus-high`, 302 completed dispatches (28 builds, 130 reviews, 39 fix rounds, 26 research runs), every unit at
ACCEPT within three fix rounds; `cc-haiku-low`, one mechanical extraction dispatch (91k tokens). Host-policy-3 adds
the four profiles the lead listed (`cc-opus-xhigh` and the review-only `cc-sonnet-xhigh`, `cc-opus-max`,
`cc-fable-max`), each with its siblings' config, tools, vision and context-tested. The exact model ids live in
`host-policy.json`. The `Profile:` line prints the full identity tuple
`(id, harness, provider, model, effort, config)`.

With the current prices, host-policy-5 (the fixture) routes, at the request's declared tier, `build-core`,
`build-ui`, `build-tests` (any tier) and `research-collect` (T1, T2) to `cc-opus-high` (no calibrated profile is
qualified for any of them), `review` at T1 to `cc-sonnet-xhigh` (`cc-sonnet-low` and `cc-sonnet-high` are qualified
but their headroom is below the 209000-token review median), `fix` at T1 to `cc-haiku-high` and at T2 to
`cc-opus-high`, and `docs-mechanical` and `pin-tests` at T1 to `cc-haiku-low`; a `review`, `pin-tests` or
`docs-mechanical` request at T2 or T3 and a `fix` or `research-collect` request at T3 are blocked (a
`docs-mechanical` request at T3 goes direct to the lead at 15k tokens or fewer; section 'Difficulty tiers'). Under host-policy-4 the same categories routed the same way without a tier. The required reviewer of every `build-*` and `fix` delegate is `cc-sonnet-xhigh` ($2.09 at the review
median; it was `cc-opus-high`, $4.18, through host-policy-3). Work of at most 15k tokens goes direct to the lead.

**`pin-tests` routes to the cheapest qualified profile, `cc-haiku-low`.** A pin declared T1 at the default size (120000 tokens) has an
output-rate bound of $0.06 there (120000 x the output rate / 1e6), plus $1.00 of brief overhead at the lead's rate:
$1.06 all-in. No reviewer is added, because `pin-tests` names no review: every pin is verified mechanically (red before
the fix, green with it, the guard-removal proof, lint) and the lead reads the diff. The three profiles of that model
share the $1.06 bound, so Gate 5 ranks equal bounds by the lower output rate, then the **lower effort**, then the id:
calibration-1 measured fewer tokens at the lower effort for every model on every task (12 model-task pairs).
`cc-sonnet-low` (114k) is qualified, but its headroom is below a default pin, so a pin that size fails it at Gate 2.

### The table (host-policy-4, history: the `trace/policies/host-policy-4.json` fixture)

Revision 4's table, untiered, kept as the record of what revision 5 re-declared (its test reads the fixture).

| Profile | Effort | Qualified for | Headroom tested | calibration-1 pin / fix / review | calibration-2 pin / fix / review | calibration-3 pin / fix / review | Basis |
|---|---|---|---|---|---|---|---|
| `cc-fable-xhigh` | xhigh, **direct only** (the lead), up to 15k tokens | build-core, build-ui, build-tests, review, fix, docs-mechanical, research-collect, pin-tests | 460k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3 |
| `cc-fable-max` | max | review | 230k | - / - / - | - / - / PASS | - / - / PASS | calibration-2 + calibration-3 review only: two passes (review new in host-policy-4) |
| `cc-fable-high` | high | review, fix, pin-tests | 352k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3 |
| `cc-fable-medium` | medium | review, fix | 172k | PASS / PASS / PASS | PASS / PASS / PASS | FAIL / PASS / PASS | calibration-1, -2, -3; `pin-tests` blocked by the run-3 pin FAIL until two later passes (rule 3) |
| `cc-opus-max` | max | review | 307k | - / - / - | - / - / PASS | - / - / PASS | calibration-2 + calibration-3 review only: two passes (review new in host-policy-4) |
| `cc-opus-xhigh` | xhigh | review, fix, pin-tests | 246k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | calibration-1, -2, -3 |
| `cc-opus-high` | high | build-core, build-ui, build-tests, review, fix, research-collect, pin-tests | 848k | PASS / PASS / PASS | PASS / PASS / PASS | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3; headroom from the accepted sr-policy-3 outcome (847844 tokens) |
| `cc-opus-medium` | medium | fix, pin-tests | 154k | PASS / PASS / PASS | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; review: PASS, FAIL, PASS - one of the two later passes rule 3 needs (G-1 recorded, not applied) |
| `cc-sonnet-xhigh` | xhigh | review | 328k | - / - / - | - / - / PASS | - / - / PASS | calibration-2 + calibration-3 review only: two passes (review new in host-policy-4) |
| `cc-sonnet-high` | high | review, fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / PASS | PASS / PASS / PASS | calibration-1, -2, -3; review: FAIL, PASS, PASS - two passes after the fail (review new in host-policy-4) |
| `cc-sonnet-medium` | medium | fix, pin-tests | 128k | PASS / PASS / PASS | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; review: PASS, FAIL, PASS - one of the two later passes rule 3 needs |
| `cc-sonnet-low` | low | review, fix, pin-tests | 114k | PASS / PASS / PASS | PASS / PASS / PARTIAL | PASS / PASS / PASS | calibration-1, -2, -3; review: PASS, PARTIAL, PASS - two passes (review new in host-policy-4) |
| `cc-haiku-high` | high, no vision | fix, pin-tests | 726k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; headroom from the accepted fix-x2-1 outcome (725422 tokens); review: FAIL, FAIL, PASS - one of two later passes |
| `cc-haiku-medium` | medium, no vision | fix, pin-tests | 183k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | calibration-1, -2, -3; review: FAIL, FAIL, PASS - one of two later passes |
| `cc-haiku-low` | low, no vision | docs-mechanical, pin-tests | 175k | PASS / PASS / FAIL | PASS / PASS / FAIL | PASS / PASS / PASS | session runs (host-policy-1) + calibration-1, -2, -3; `fix` demoted 2026-10-18 (two consecutive verification-failed outcomes); review: FAIL, FAIL, PASS |

### How to add evidence

1. A qualification run cannot go through `dispatch`: a profile not qualified for the category fails Gate 2, and
   `dispatch` refuses it even with `--deviation`. Running an unqualified profile on real work is a host policy
   that Holdshort does not sanction (spec-v2 §12: "No dispatch on unknown ... capability"). The path this host
   uses is a **calibration run** outside Holdshort routing: the same graded tasks for every profile, on past work
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
   `qualified-for` (under host-policy-5 at its tier, `<category>@T<k>`; bare reads `@T1`), append the run ids and the
   `calibration-<n>: <category>[@T<k>] PASS|PARTIAL|FAIL (n=<k>)` entries to `evidence` (under host-policy-6 a
   production outcome goes in as a typed reference, `outcome: <task-id> <category>[@T<k>] accepted <YYYY-MM-DD>
   (trace/outcomes/<task>-<seq>.json)`, the line `rate` prints with a qualify proposal; free text supports nothing,
   section 'Calibration-first evidence'), set `qualified-at` to the ratification date, and set `expires` (at most three months out). Bump
   `policy-revision`. The decision files bind every decision to the policy digest, so old decisions stay readable.
   A decision not yet dispatched is rechecked against the edited policy at `dispatch`, so a demotion or a
   revocation takes effect on pending decisions too. When a revision changes what the goldens or the base tests
   assume, freeze the previous policy as `trace/policies/host-policy-<n>.json` and keep them on it (never in
   `trace/decisions/`, whose file names belong to decisions). A policy with typed references loads from
   `trace/policies/` too: a fixture under `<root>/trace/policies/` resolves its references against `<root>`, the
   directory holding that trace (`policyRoot`, the lead's integration fix of policy finding 5 of host-policy-6); the
   two directory names are the rule, and a copy anywhere else resolves against its own directory.
4. A profile with `qualified-at: null` or a past `expires` fails Gate 2 until this is done.

## The learning loop

`outcome` records go in, `rate` turns them into proposals, and the lead edits the policy. The adapter never
writes the policy.

- `rate` aggregates outcomes per (profile, category), and under an enforced policy (host-policy-5) per (profile,
  category, tier), the stats keys and proposals reading `<category>@T<k>` (section 'Difficulty tiers'): accepted, verification-failed, partial, cost-overrun,
  cancelled, blocked, escalated, plus how many came from host deviations. It counts **one outcome per dispatch**:
  a later outcome record for the same dispatch supersedes the earlier one (spec-v2 §10.5, decision-trace.md §4),
  so recording a correction never double-counts. It writes `trace/qualification-stats.json`
  (`outcomes-counted` after supersession, `outcome-records` before), which is byte-identical when regenerated from
  the same ledger.
- It proposes **demotion** of a profile from a category after two consecutive `verification-failed` outcomes there
  since its `qualified-at`, or after any `cost-overrun`.
- It proposes **qualification** after three `accepted` outcomes in a category the profile is not qualified for.
  `dispatch` refuses such runs, so these outcomes can only come from runs the lead recorded by hand (see 'How to
  add evidence'). The `PROPOSAL` line ends with the typed references the lead would paste, one per accepted outcome
  (host-policy-6, E7):
  `PROPOSAL qualify <id> for <category>[@T<k>]: 3 accepted while unqualified (host deviations: ...); not applied — the lead ratifies by editing host-policy.json; typed evidence to paste: "outcome: <task> <category>[@T<k>] accepted <YYYY-MM-DD> (<path>)", ...`.
  With `--trace` outside the policy file's directory there is nothing to paste: the line ends with
  `; no typed evidence to paste: the outcome store <dir> is outside the policy file's directory <dir>, and a reference cannot leave it (E1)`.
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

## Policy findings (host-policy-6)

Found while building revision 6 (unit sr-policy-6). The lead decides.

1. **The proposal was not at the path the brief names.** `/home/user/smartrouter` is still checked out at `5bd473a`
   (PR #98), where `docs/proposals/calibration-first-onboarding.md` does not exist. It was read from Holdshort main as
   merged (`7f7fc75`, which contains PR #102's merge `bb3fa6c`), through the read-only main worktree of that repository
   (`git show origin/main:` gives the same bytes); nothing was copied but the passages this README quotes.
2. **The proposal still says hosts MUST NOT emit or require its form.** Its status line (quoted in section
   'Calibration-first evidence') is unchanged by the merge, and its review record ends with `pending delta review`, as
   the tiers proposal's did (host-policy-5 policy finding 7, friction item 22). Host-policy-6 requires the typed form
   on the operator's merge of PR #102 and the lead's E1-E7. The exposure is bounded the same way: the rule applies only
   under `"evidence": "typed"`, and deleting that key returns the host to free-text evidence with no code change (the
   `outcome:` lines would still be checked and resolved, E1 being unconditional; they all resolve).
3. **The lead-direct exemption has no clause upstream** (E3, friction item 23). Without it `cc-fable-xhigh`'s eight
   `@T3` entries, held on the lead's integration record and T1 calibration grades, would be refused, and `direct`
   would become unroutable for every bounded task.
4. **One check beyond E1: the Outcome's `owner-profile` must be the referencing profile.** E1 lists the task, the
   outcome, the date and the category; without the owner a profile could cite another profile's accepted outcome as
   its own capability evidence. Every reference of the lead's table satisfies it. The lead may drop the check.
5. **A host-policy-6 fixture will not load from `trace/policies/`.** Each revision so far froze its predecessor as
   `trace/policies/host-policy-<n>.json` and decided the old assertions on it. Under E1 the references resolve against
   the policy file's directory, so `trace/policies/host-policy-6.json` would look for
   `trace/policies/trace/outcomes/...` and be refused (exit 2). The revision that freezes host-policy-6 has to write the
   fixture's test derivatives beside a copy of the store, as these tests do for the live policy (`LIVE_OFF_DIR`), or
   the lead decides another resolution base for fixtures. Nothing in this revision needs it. **Resolved at
   integration (lead):** `policyRoot` resolves a policy under `<root>/trace/policies/` against `<root>`; the test
   "E1 (fixture root)" pins it, so the revision that freezes host-policy-6 pins its assertions as every revision did.
6. **Four categories have no delegate** (E6). `build-core`, `build-tests`, `research-collect` and `docs-mechanical`
   requests above 15000 tokens are blocked until run 4's host-pack cells qualify a profile; the github-sign-in run's
   remaining build units in those categories are affected (the RUN.md consequence is the lead's).
7. **The references depend on the ledger beside the outcomes.** This host's Outcomes carry no `ts` (§10.3 has none),
   so a reference's day is its outcome record's, read from `ledger.jsonl` next to `outcomes/`; an outcome file copied
   without its ledger is unresolvable. The day is the UTC day of the record's `ts`.
8. **A pre-tier reference's tier is the host's word.** Every reference in the table points at a decision made before
   revision 5, so E1 accepts any declared tier there with the "would be" note: `build-ui@T3` rests on the lead's reading
   of five- to nine-file units, not on a recorded tier. A reference against a tiered decision is checked.
9. **The notes count permitted files.** The "would be" notes give each decision's `permittedEffects` count; the
   brief's table says "five and nine files", but `sr-policy-5`'s request named six (its outcome touched five).
10. **The policy's `_comment` still describes evidence as run ids or calibration grade entries.** E5 defines revision
    6 as revision 5 plus the key and the table, so the comment was left as it was; it does not mention the typed
    reference.

## Policy findings (host-policy-5)

Found while building revision 5 (unit sr-policy-5). The lead decides.

1. **The proposal was not at the path the brief names.** `/home/user/smartrouter` is checked out at `5bd473a` (PR #98),
   where `docs/proposals/difficulty-tiers.md` does not exist. The proposal was read from Holdshort main as merged
   (`7f7fc75`, which contains PR #100, `2e30291`), with `git show` in that same repository; nothing was copied but the
   passages the brief asks to quote.
2. **The undeclared default blocks two categories outright.** D3's default reads T2 for every normal- and low-risk
   category, and every `pin-tests` and `docs-mechanical` holder is bare (T1), so an undeclared pin or docs request is
   `blocked`; so is an undeclared `review` or `fix` (T3), which only the lead-direct profile holds. Declared T1 they
   route as before. This is the rule as written (the proposal's default is "conservative because a tier the host did
   not think about is the case the Context describes"), but it makes the declaration mandatory in practice for four
   of eight categories.
3. **The learning loop reads the tier of the dispatch's own decision.** D7 says per task; Item 3 has the lead raise a
   tier and decide the same task again after a `verification-failed` outcome, and a per-task tier would then count the
   first, failed dispatch at the raised tier, hiding a demotion of the lower one. `learn()` reads the dispatch's
   `decision-seq` and that decision file's tier, falling back to the task's for a dispatch recorded without one (the
   hand-walked records). Pinned by a test; the lead may revert to the per-task reading.
4. **Every pre-revision outcome counts at T1.** By D7 a decision without a tier counts at T1, so `rate` on the
   committed ledger under host-policy-5 shows `cc-opus-high build-ui@T1`, `fix@T1`, `review@T1` (15 outcomes, no
   proposals), while the re-declaration reads those units as T2 or T3. Under rule 5 a fail at T1 is a fail at every
   tier, so the T1 label is the stricter reading of old failures. The three re-declared profiles' `qualified-at`
   moved to 2026-10-18, so their earlier outcomes no longer enter their learning streams.
5. **The `cc-fable-xhigh` lines carry no "would be T<k> by the table".** The table gives that line whole; the lead's
   integration work is not tiered unit by unit. It includes `docs-mechanical@T3`, which Item 1 says is "never" T3; a
   declared T3 above the floor is accepted (D3), so the entry routes such a request to the lead below
   `direct-max-tokens`.
6. **A review above T1 has no delegate.** No calibrated profile holds `review@T2` or above, and the production
   reviews re-declared are T1. Every T2 or T3 review request the lead dispatches is blocked until run 4 (or a later
   run) qualifies one; the required reviewer of a unit is unaffected (D5).
7. **The proposal says hosts MUST NOT emit or require its fields until a delta review accepts it; host-policy-5 emits and requires them.**
   The merged text (Holdshort `7f7fc75`; the file is unchanged since PR #100's merge commit `2e30291`, and the same
   on `origin/main`) opens:

   > Status: **draft proposal, not normative; revision 2 after the independent review of 2026-10-18 (Request Changes
   > on 987a4e3).** Nothing in `skills/` is amended by this document. If accepted after independent review (plan
   > §15), the items below would become one additional Gate 2 rule, an additive host-policy qualification form,
   > additive §9/§10 fields under the §13 "additive unknown fields remain ignorable" rule, and one
   > calibration-protocol change for the host under `hosts/claude-code/`; until then hosts MUST NOT emit or require
   > them.

   Its review record ends with the row `| 1-5 (revision 2) | pending delta review | — | — |`, and no later commit
   changes the status. Under D6 host-policy-5 emits `DifficultyTier` and `difficulty-tier` (the decision, the §10.1
   Brief, the §10.5 ledger decision record), and under D3 and D4 it requires the tier (the floor refusal, Gate 2 by
   tier). The basis is a decision, not the text: the operator chose on 2026-10-18 to merge PR #100 (with #101 and
   #102) into main without the delta review (the github-sign-in run ledger, `RUN.md`, commit `b8e1a1d`, as relayed by
   the originating session), and the lead's brief for this unit adopts the merged text as the specification with
   D1-D9 binding where it leaves a choice. Two things limit the exposure. The fields are additive under §13, so a
   reader that ignores unknown fields is not broken. And the rules apply only under `"difficulty-tiers": "enforced"`:
   deleting that key from `host-policy.json` returns the host to per-category routing with no code change (D1, D2:
   the tiered entries still load). With the key removed, a default `fix`, `review`, `pin-tests` and
   `docs-mechanical`, a `build-ui` at 250000 and a `fix` declared T2 route as host-policy-4 routes them (probed in
   fix round 1). A decision taken under the enforced revision would then be refused at dispatch (`the route changed` where the untiered route picks another profile, as for a fix declared T2; `changed: difficulty-tier` where it picks the same one), the mirror of the pending-decision note. Until the delta review is recorded, host-policy-5 runs
   ahead of the specification it cites. Whether to keep the key on until then is the lead's call.

## Policy findings (host-policy-4)

Found while building revision 4 (unit sr-policy-4). The lead decides.

1. **The required reviewer moved with the table.** The brief names the fix and review defaults; it does not name the
   reviewer. With `cc-sonnet-xhigh` review-qualified, the reviewer of every `build-*` and `fix` delegate is
   `cc-sonnet-xhigh`, not `cc-opus-high`: the review bound falls from $4.18 to $2.09, a default fix from $5.28 to
   $3.19, and the stored build request from $11.50 to $9.41. This is the existing reviewer rule applied to the
   table, not a new rule. In practice, a review that used to go to the profile with 130 production reviews now goes
   to one with two calibration passes on one task. A lead who wants a stronger reviewer would pass `candidates`, or
   qualify review per risk (the difficulty-tiers proposal upstream).
2. **The review-only run-id entry** says `review graded ...; a review-only profile in that run (no pin or fix cell)`
   rather than the brief's `pin, fix and review graded`, which is not true of `cc-sonnet-xhigh`, `cc-opus-max` and
   `cc-fable-max` in run 3. Revision 3 made the same call (its finding 4).
3. **`cc-sonnet-low` and `cc-sonnet-high` are review-qualified but take no default review.** Gate 2 compares the
   work estimate alone with `headroom-tested` (209000 against 114000 and 183000); the brief's "209000 + overhead"
   overstates what Gate 2 counts, and the outcome is the same. A smaller review with an explicit `estimatedTokens`
   below their headroom can route to `cc-sonnet-low`, the cheaper of the two.
4. **"lead-notes N-1".** The block entry cites `lead-notes N-1`, as the brief words it. `trace/calibration-3/lead-notes.md`
   has no N-1 label: the pin FAIL is its section "pin:fable-medium FAIL — an over-specified pin". The entry is kept
   verbatim; the README cites the section.
5. **One test moved that the brief did not list by name.** `committed policy (ii)` ends by comparing the stored build
   request's bound with the hand-walked golden's ($11.50, review at `cc-opus-high`). Under revision 4 that bound is
   $9.41, so the test runs on the host-policy-3 fixture, and the live policy has its own assertion
   (`host-policy-4 routing: the stored build request ...`). `committed policy (i)` (no reading: Gate 4 fails closed)
   and P2-4 are unchanged under revision 4 and stay on the live policy.
6. **A frozen policy is judged against the ledger it was frozen with.** The host-policy-3 table test's headroom rule
   reads accepted outcomes up to 2026-10-18T09:07:43Z, the last record at the unit's base commit, so a later
   outcome can never redden the fixture's tests. The host-policy-4 test reads the whole ledger, as the live test did
   in revision 3: an accepted outcome above a headroom figure reddens it until the lead ratifies `rate`'s proposal.
7. **The `cc-opus-high` row's basis was stale.** The host-policy-3 table said the 848k headroom came from the accepted
   sr-policy-2 outcome (770527 tokens). It came from sr-policy-3 (847844 tokens, ratified in `9698427`). The
   revision-4 row says so.

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

## Friction log for Holdshort upstream

Every point where the spec was ambiguous or did not fit a subscription host. Citations are to
`StepenkoAnatoli/Holdshort@fbe7bca`.

1. **No cash accounting in subscription hosts.** gates.md Gate 4: "Strict caps additionally require a reliable
   conservative billable bound and reliable host accounting". A subscription with weekly token limits has neither
   per-call USD nor a cap to enforce. Yet spec-v2 §10.5 types `counters.cash-spent` and `cash-cap` as numbers, and
   §10.3 types `evidence.actual-spend` as a number. This host writes `null` for all three and reports cash as an
   estimate on every Uncertainty line. Upstream could add an `accounting: estimate-only` mode that types these
   fields as `number | null` and names the resource that *is* finite here (weekly tokens).
   **Closed** for the cash fields: Holdshort accepted Item 4 of `docs/proposals/usage-windows-gate4.md` on
   2026-10-18 (upstream unit sr-ci-item4). A `null` is conformant beside `counters["cash-basis"]: "estimate-only"`
   (§10.5) or `evidence["actual-spend-basis"]: "estimate-only"` (§10.3), and the adapter writes both markers
   (section 'Enforced vs advisory'). Records written before that stay unmarked. The finite resource (the usage
   windows) is still untyped upstream (item 16).
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
   decorative)", but `tests/holdshort_decisions.py` models `Profile.tools: bool`, and no §10 object carries a
   profile's tool list. Policy finding 2 above follows from this.
6. **The direct bound is not specified.** gates.md Gate 5 says to compare "against the full direct bound". This
   host's builder brief sets the direct bound to the lead's rate on the tokens, without the required review that a
   delegate carries. That favours direct, which Holdshort prefers anyway, but the asymmetry is the host's choice,
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
    tier to avoid blocking"), and fixture E01's first leg in `tests/holdshort_decisions.py` (only C is a
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
19. **The workflow harness relays the operator's latest chat message into every worker as the request that "wins"
    over the computed task** (amendment A-1 upstream; `trace/calibration-3/lead-notes.md` 'A-1'). The harness
    prepends a user turn stating that the relayed request "is the only user voice in this task" and that "where the
    computed task conflicts with this request, this request wins". In calibration run 3 the message was the operator's
    chat at launch ("focus on smartrouter for now"); two cells halted on it and were voided and re-run. The spec's
    route table (spec-v2 §5) says a delegate is "one isolated Worker that becomes the sole owner of the brief", and
    §10.1 requires a Brief for every delegate; nothing in the spec states that the brief is a worker's only input,
    and that gap is this item. A host whose harness
    injects operator chat cannot guarantee that the brief is the whole input, so a worker's behaviour is a function
    of the brief and of whatever the operator last typed. The calibration kit must record the relayed text before
    the launch (the kit rule run 3 adopted), and a host should record it in the dispatch, as the launch of this unit
    did: its computed task quoted the relayed message ("i asked him to re-review it. wait", about pull-request
    reviews upstream) and said it did not ask the worker to wait. Upstream could name operator-chat injection as an
    isolation input the Brief must declare, or forbid it for delegated workers.
20. **The three-lens adjudication's output schema has no `forbidden` prong** (G-2, `trace/calibration-3/lead-notes.md`).
    Run 3's classification has three prongs: the behaviour holds at HEAD, it is reachable through the public API with
    admissible input, and the spec or the module's promise forbids it. The lens schema carries `holds` and `reachable`
    only, and a lens counts as a 'real' vote when `holds && reachable !== 'no'`, so the majority counts on two prongs.
    For clusters C-4 and C-5 the lenses' prose says the spec permits the behaviour, while the votes read REAL (2/3).
    The preregistered score stands and no qualification changes (host-policy-4), but under the full definition two
    reviews would be FAIL. The adjudication schema needs `forbidden`, with a real vote only on all three prongs (run 4
    adds it).
21. **The proposal's Item 3 "names it" clause is the existing `eligible-outside-candidates` hint, and the reviewer-tier question (D5) is not addressed by the proposal.**
    Item 3 asks for the reason `no profile qualified for
    <category>@<tier>` and, when a profile qualified at a higher tier exists, `cheapest profile qualified at
    <category>@<tier+k>: <id>`. This host already names a profile outside the candidates that would pass all five
    gates (`not among candidates: ...`, the decision's `eligible-outside-candidates`), so it keeps that hint and adds
    no reason text (D4); inside the candidates a higher-tier holder is eligible and simply routed. The proposal is
    silent on the required reviewer of a tiered unit: Gate 3's reviewer is drawn at the review median, and nothing
    says at which tier. This host walks it at `review@T1` (D5), because the review is its own request when the lead
    dispatches it. Upstream could state the reviewer's tier, and say whether "names it" means a profile outside the
    candidates, a higher-tier profile inside them, or both.
22. **A merged proposal still says hosts MUST NOT emit or require its fields.** PR #100 put
    `docs/proposals/difficulty-tiers.md` on main with its status line unchanged ("draft proposal, not normative; ...
    until then hosts MUST NOT emit or require them") and its review record ending in
    `| 1-5 (revision 2) | pending delta review | — | — |`. A merge is the operator's act, but the text has no state
    between "draft, not normative" and "accepted", so a host that adopts a merged proposal on the operator's word (this
    one, host-policy-5, policy finding 7) contradicts the text it cites, and nothing in Holdshort tells a reader
    that the merge was a decision to adopt. Upstream could update the status line when a proposal is merged or
    reviewed, or say that a merged but unreviewed proposal may be adopted by a host behind a policy switch.
23. **The proposal has no clause for the lead's own profile.** Item 1.1 says "a profile may enter a host policy
    with any `qualified-for`, but every category it names MUST be supported by an evidence entry", with no exception.
    The lead-direct profile's qualifications are not a capability claim about a delegate: they are the operator's
    authorization of the lead's inline work, routed only below `direct-max-tokens`. A host that applies the rule to
    that profile either fabricates evidence or makes `direct` unroutable. This host exempts it (E3, policy finding 3
    of host-policy-6). Upstream could add an exemption clause for the lead-direct profile, or give the lead's direct
    route its own rule (an authorization entry instead of a qualification).
24. **The proposal's `outcome:` form carries no tier.** Item 1.1 (b) is `outcome: <task-id> <category> accepted
    <ISO date> (<outcome store path>)`. The difficulty-tiers proposal (Item 2.2, rule 2.3) makes qualification per
    (category, tier) and counts "an accepted production outcome whose request carried that tier", which a tierless
    reference cannot express. This host added `[@T<k>]` to the form, the same optional suffix the grade entry gained,
    checked against the decision's `difficulty-tier` when it has one and accepted with a "would be T<k> by the table"
    note when it does not. Upstream could state the tier in the form (and say whether a pre-tier outcome may carry a
    declared tier).
25. **Where the outcome store is, relative to a policy copy.** Item 1.1 resolves references against "the outcome store
    (the `--trace` directory the adapter already takes)", and lets a validation run without a store check form only.
    This host resolves against the policy file's directory instead (E1): a test's temporary `--trace` must not change
    whether a policy is valid, and an upstream copy of the policy beside its trace resolves as it does here. The cost is
    finding 5 above (a frozen fixture moves away from its store). Upstream could say which base a reference's path is
    relative to, and whether "form only" is allowed when a store exists but is not given.
