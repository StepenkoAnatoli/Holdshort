# Builder brief: the SmartRouter host adapter for the MoonAliza build process

You build `docs/orchestration/smartrouter/route.mjs` (plus its tests and README) in the worktree
`/home/user/task5-handoff/wt/sr-host` (branch `build/sr-host`). Work only there; never push.
Commit identity: `git -c user.name=StepenkoAnatoli -c user.email=318295322+StepenkoAnatoli@users.noreply.github.com commit`.
Every commit message ends with the two lines `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
`Claude-Session: https://claude.ai/code/session_01VdJ51CTnHT4Zet6eScsBBh`. No model names anywhere else in committed files.
Node 24 is at `/versions/node/v24.21.0/bin` (export it on PATH). No dependencies: Node built-ins only, `node:test` for tests.

## What it is

The lead of this repository's build runs (a Claude Code session) must apply SmartRouter's routing policy before every
sub-agent dispatch: which route (direct / delegate / speculative / recommend-escalation / blocked), which profile
(model + effort), which isolation, and emit the machine-readable Brief. SmartRouter is advisory and stateless; the host
(this adapter plus the lead) collects the inputs, enforces the decision, and keeps the Outcome Ledger.

Read, in this order, from the read-only SmartRouter clone at `/home/user/stepenkoanatoli/smartrouter` (at `fbe7bca`):
1. `skills/smart-router/SKILL.md` (whole file)
2. `skills/smart-router/references/gates.md` (normative gate semantics)
3. `skills/smart-router/references/spec-v2.md` sections 5-12 and 14 (routes, isolation, §10.1 Brief, §10.3 Outcome, §10.5 LedgerRecord, host duties, prohibitions, compliance)
4. `skills/smart-router/references/brief-and-result.md`, `decision-trace.md`, `defaults.md`, `gate4-affordability.md`, `gate5-economics.md`
5. `tests/smart_router_decisions.py` lines 36-215: the fixture-pinned gate runner (`run_gates`, `choose_route`) and the terminal classifier. Your gate order and reasons must match its semantics.
Then read `docs/orchestration/smartrouter/host-policy.json` here: the host's inputs (harness, authorization, accounting mode, prices, categories, profiles with qualification evidence, economics constants, opt-ins). Never change the policy file; if it is inconsistent with the spec, say so in the report.

## The adapter

`route.mjs` is an ES module with a CLI and named exports.

CLI:
- `node route.mjs decide <request.json>`: prints SmartRouter's **Required output format** block (SKILL.md) followed by the Brief JSON (§10.1) when the route is `delegate`; writes `trace/decisions/<task-id>-<seq>.json` (the full decision: inputs digest, per-candidate gate walkthrough with deterministic reasons, chosen profile, estimates vs accounting) and appends a `decision` LedgerRecord (§10.5) to `trace/ledger.jsonl`. Exit 0 for any decided route including `blocked`; exit 2 on an invalid request.
- `node route.mjs dispatch <task-id> <profile-id>`: appends a `dispatch` record (slot reservation before sending) and refuses (exit 3) when the task's call slots or same-profile repairs are exhausted.
- `node route.mjs outcome <outcome.json>`: validates a §10.3 Outcome, appends an `outcome` record, exit 0.
- `node route.mjs status <task-id>`: prints the task's counters from the ledger.
- `node route.mjs rate [--trace <dir>]`: the learning step. Reads every `outcome` record, aggregates per (profile, category): accepted, verification-failed, partial, cost-overrun, cancelled, blocked, escalated; writes `trace/qualification-stats.json` (derived, regenerated, never hand-edited) and prints **proposals** the lead ratifies by editing `host-policy.json`: demote a profile from a category after two consecutive `verification-failed` outcomes in it or any `cost-overrun`; propose qualification for a category once a profile has three `accepted` outcomes in it while unqualified (such outcomes can only come from host deviations, which the ledger marks); flag a profile whose `expires` is within 14 days. Proposals are never applied by the adapter: SmartRouter's qualification is declared by the host, never inferred (gates.md 'Qualification, freshness and pre-dispatch binding'). A `decide` call after an outcome that demotion rules would catch must still be computed from the policy file as it stands, and the Uncertainty line must name any pending proposal for the chosen profile.
Paths default to the adapter's own `trace/` directory; `--trace <dir>` overrides them (tests use a temp dir).

Request (host → router), JSON: `taskId`, `objective`, `category` (one of the policy's categories), `unit` (name),
`permittedEffects` (paths), `sources` (paths), `nonGoals` (strings), `acceptanceChecks` ([{command, expect}]),
`estimatedTokens` (optional; default the category median), `requiredTools` (optional; default the category's),
`needsVision` (bool), `dataClasses` (subset of permitted or forbidden classes), `projectStop` ({redSuite, gateOff, researchGateFailing}),
`previousResult` (§10.3 Outcome or null), `deadline` (ISO-8601), `now` (ISO-8601, injected for determinism),
`candidates` (optional list of profile ids; default every policy profile), `allowDirect` (bool, default true),
`hostOptIns` (optional override of the policy's).

Gates, per candidate, in order, deterministic reasons (strings a reader can act on):
1. Permissions / privacy / workflow: unknown category or profile → deny; a forbidden data class → deny before anything else; any project stop rule set → deny ("project stop: ..."); isolation the host cannot provide → deny.
2. Capabilities: profile must list the category in `qualified-for` (declared, never inferred from price or label); required tools present; vision when needed; a profile with `qualified-at: null` or an expired qualification (`expires` < now) fails with "missing or stale capability fingerprint"; context: estimated tokens must be below the profile's `headroom-tested`.
3. Verification: the category's verification checks must be present in `acceptanceChecks` (names matched case-insensitively against the category's list); missing → blocked before start ("verification prerequisite missing: ...").
4. Affordability: the strict parts are call slots (`calls-used + 1 <= calls-per-task`), repairs (`previousResult` present and same profile → repairs-used + 1 <= allowed; a different profile after a failed outcome is a fresh decision, not a repair), and deadline (`now` strictly before `deadline`, equality expires). Cash is estimate-only in this host: compute the conservative bound (`tokens x output_rate / 1e6`) for work plus the required review (the `review` category's median at the cheapest review-qualified profile; only for categories whose verification list names a review or re-review: build-core, build-ui, build-tests, fix) and record it, but never block on it; the Uncertainty line must say "cash: estimate only, no host accounting (subscription); not a strict cap".
5. Economics: among eligible candidates compare all-in bounds. The direct candidate is the policy's `lead-direct-profile`, eligible only when `allowDirect` and `estimatedTokens <= direct-max-tokens`; its bound is its own rate on the tokens. A delegate candidate's bound = worker bound + review bound + `delegate-overhead-tokens` at the lead's rates. Choose the lowest bound; ties go to the lower output rate, then alphabetical id. If no delegate candidate is eligible but a stronger profile would be qualified except for an authorization or availability reason, output `recommend-escalation` naming it; if no candidate at all, `blocked` with the first failing gate and reason of each candidate. `speculative` only when `hostOptIns.speculative` is true and the request sets `uncertainty: "high"`; otherwise never.

Output: the Required output format block verbatim (Difficulty, Route, Profile as the exact identity tuple `(id, harness, provider=anthropic, model, effort, config)`, Isolation, IsolationReason, Owner, HumanGate, NestedAllowed, MaxNestingDepth, Reservations, Calls, Deadline, Uncertainty), then `Advisory: recommendation only — no dispatch performed or claimed` always (this adapter never dispatches), then the Brief JSON with `branch-hint` in the host convention and `allowance.cash` as the estimate with `cash-basis: "estimate-only"` added as an extra field (additive fields are allowed by §13).

Ledger: §10.5 records, append-only, `seq` per task from 1, counters are task totals after the event, `brief-fingerprint` = sha256 of the canonical Brief JSON. A `dispatch` record precedes any send; `outcome` records reference the dispatch. Never rewrite a line. No secrets, prompts or bodies in the ledger (decision-trace.md §3).

## Tests (red first, every one)

`route.test.mjs` with `node:test`. For each test: write it, show it red (the assertion fails against a stub or the previous state), then make it green. Keep a proof log in your report: command, red output, green output. Minimum cases, each named after the SmartRouter fixture it mirrors:
- S03: a request with data class `local-only` → every cloud profile denied at Gate 1 before anything else; route blocked.
- S09: `projectStop.redSuite` → blocked, reason names the project stop.
- S04/S05: `needsVision` with a profile lacking vision → Gate 2 reason lists it; the expensive label does not cure it.
- Fresh fingerprint: `cc-sonnet-high` (no qualification) → Gate 2 "missing or stale capability fingerprint"; an expired `expires` in a candidate copy → the same.
- S10/S15c: a request missing a required verification check → blocked at Gate 3 before start.
- S08-shaped: call slots exhausted (ledger with `calls-per-task` dispatches) → Gate 4 blocks; deadline equality expires; cash never blocks.
- R01-R03: a second same-profile repair for the same task → refused by `dispatch` (exit 3) and by Gate 4 in `decide` with `previousResult` of that profile; a different profile is a fresh decision.
- S02/D01: economics chooses the lowest all-in bound; direct wins for a tiny task (≤ direct-max-tokens); delegation wins above it; with the policy's prices, a `build-core` request routes to `cc-opus-high`, a `review` request to `cc-opus-high` (cheaper than `cc-fable-high`), a `docs-mechanical` request to `cc-haiku-low`.
- E01: when the only qualified profile for a category is absent from `candidates` → `recommend-escalation` names it.
- S24: output always carries the Advisory line; the adapter never claims a dispatch.
- Ledger: `seq` monotonic per task, counters correct after decision + dispatch + outcome, `brief-fingerprint` stable for the same Brief and different for a changed objective; an outcome with an unknown task id is refused.
- Learning: two `verification-failed` outcomes for (cc-opus-high, fix) produce a demotion proposal and no policy change; the next `decide` for a fix still routes by the unchanged policy and names the pending proposal in Uncertainty; `qualification-stats.json` is regenerated identically from the same ledger.
- Golden: the three hand-walked decisions in `trace/decisions/hand-*.json` (written by the lead before this adapter existed) must be reproduced exactly by `decide` on their stored requests: same route, same profile id, same first-failing-gate per rejected candidate.
Also a guard-removal proof per gate: remove the gate's check in a scratch copy of route.mjs and show which tests go red (each gate must have at least one).

## README.md (`docs/orchestration/smartrouter/README.md`)

What the adapter is, the lead's per-dispatch procedure (decide → put the Brief in the builder prompt → dispatch record → launch → outcome record), what is enforced vs advisory in this host (calls, repairs, deadline, isolation enforced; cash advisory), the qualification table with its honest status ("host-declared from run history, reviewer: lead, expires 2027-01-15"), how to add evidence, the learning loop (outcome -> rate -> proposal -> the lead edits the policy; MoonAliza the product gets the same loop later through its Phase 6 advisory UI, out of scope here), and a "Friction log for SmartRouter upstream" section listing every point where the spec was ambiguous or did not fit a subscription host (start with: no cash accounting in subscription hosts; what counts as one 'original task' across iterative review rounds; the README's dead link to docs/HANDOFF_RESEARCH_KIT.md; anything you hit).

## Commits

Three commits, each with the five-part report (what changed; why; what it touched; what you verified with verified/untested/expected; what you got wrong and fixed, or "nothing to report"):
1. `docs(smartrouter): host policy and the lead's hand-walked decisions` is already staged by the lead (do not touch those files).
2. `feat(smartrouter): route.mjs - the five gates, the Brief and the ledger, with tests` (route.mjs + route.test.mjs).
3. `docs(smartrouter): README - procedure, qualification table, friction log`.
`docs/ARCHITECTURE.md` is not owed: nothing under src/ changes. Run `npx eslint docs/orchestration/smartrouter/*.mjs` (exit 0 or say why the config excludes docs) and `node --test docs/orchestration/smartrouter/route.test.mjs` as the checks.

## Report (your final answer, JSON per the schema you are given)

Commits with shas; every test with its red/green proof; every guard-removal proof; the checks; what you judged wrong in the policy or the spec with evidence; what you got wrong and fixed.
