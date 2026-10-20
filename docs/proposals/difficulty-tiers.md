# Proposal: difficulty tiers — qualify a profile per (category, tier), not per category

Status: **draft proposal, not normative; revision 2 after the independent
review of 2026-10-18 (Request Changes on 987a4e3).** Nothing in `skills/` is
amended by this document. If accepted after independent review (plan §15),
the items below would become one additional Gate 2 rule, an additive
host-policy qualification form, additive §9/§10 fields under the §13
"additive unknown fields remain ignorable" rule, and one
calibration-protocol change for the host under `hosts/claude-code/`; until
then hosts MUST NOT emit or require them.

## Context

- Qualification is per **category**. A profile's `qualified-for` lists
  categories (`fix`, `review`, `pin-tests`, ...), and a category is qualified on
  graded calibration cells plus production outcomes: two independent passes
  for a high-risk category, one for a normal-risk one
  (`hosts/claude-code/README.md`, "Qualification rules" 1-3).
- Every calibration cell of a category is **one difficulty**. Runs 1-3 grade
  `fix` on a single S3 defect of one function in a 16 KB module whose cause the
  finding names, `pin-tests` on a two-row pin for one rule, and `review` on a
  module carrying two S3 defects
  (`docs/evidence/2026-10-18/claude-code-calibration-3/protocol.json`, `cases`;
  its `limits` say "two ground-truth defects, one run per profile"). A `fix`
  PASS therefore says "can fix a bounded, cause-named S3 defect", and the
  policy reads it as "qualified for `fix`".
- Gate 5 then picks the cheapest eligible profile for every request of the
  category, whatever the request's difficulty, because nothing in the request,
  the policy or the gates carries one. The §9 `Difficulty` line is derived, not
  declared: the Claude Code adapter sets it from the category's risk and the
  request's `uncertainty` flag (`hosts/claude-code/route.mjs`, the
  `difficulty` constant in `decide`), prints and records it, and no gate reads
  it. `estimatedTokens` and `headroom-tested` bound a request's **size** and
  `uncertainty` flags ambiguity; none of the three says how hard the work is.
- The cost of that gap is one observation on the host's ledger, described
  here from the request record this repository holds
  (`hosts/claude-code/trace/decisions/fix-u7-r3-2.json`): the unit
  `fix-u7-r3` was a **tests-only** fix round for two S3 review findings (U7-R9,
  a test-side hook that records every `atomicJson` value; U7-R10, a static
  guard against `child_process`, `worker_threads` and the spawn family), with
  `permittedEffects` of one test file and the fixtures directory and an
  estimate of 170,000 tokens. It routed to `cc-haiku-low` as the cheapest
  `fix`-qualified profile. Its outcome row (seq 4, `verification-failed`,
  1,012,799 harness tokens after two review rounds that found the same
  harness-bypass class each time; the lead finished it inline) is **host-local**
  until the next adapter refresh, and is cited as such: the in-repo ledger
  holds seq 1-3 and the 399,000 figure on them is the reservation, not the
  spend. The `cc-haiku-low` **fix** cells that qualified the profile ran at
  109,688, 139,679 and 116,605 tokens (runs 1-3 `scores.json`), so the unit
  cost 7.3-9.2 fix cells. By the table in Item 1 this unit **would have been
  T2** (two files, a harness to extend, the cause named): its difficulty was a
  harness mechanic the structural fields do not see. That is the point, not an
  embarrassment for the proposal: a difficulty signal has to be *declared* by
  the host that knows the unit, with a structural floor underneath it, and
  whether tiers would have routed this unit elsewhere is exactly what the
  proposal cannot claim and the record in Item 5 will measure.
- The reverse waste (a bounded fix sent to an expensive profile out of
  caution, recorded as an accepted outcome that says nothing about whether a
  cheap profile would have done) is a hypothesis: no unit on the ledger shows
  it, and the record in Item 5 is where it would show.

The efficiency a difficulty axis buys is therefore two-sided and, so far,
unmeasured: cheap profiles keep the bounded work they are proven on, and
open-ended work goes to the cheapest profile proven on open-ended work instead
of failing once first.

## Item 1 — the tier scale, declared from observable request facts

Three tiers, the same names for every category, with **predicates per
category**: "edit set" is meaningful for the building categories only, so each
category defines its own T1 and T3 tests and T2 is what is neither. A tier is
a property of the **request**, declared by the host and recorded. It is not an
estimate of tokens and not a price.

| Category | T1 (all hold) | T3 (any holds) |
|----------|---------------|----------------|
| `fix`, `build-core`, `build-ui`, `build-tests` | the edit set (`permitted-effects` minus the architecture map) is at most two files in one module; the cause, or the rule, is named in the request; the acceptance checks run on an existing harness | the edit set spans more than three files or more than one seam; the cause is unknown; the acceptance checks need a new harness; the edit set includes the code that handles credentials, persistence, concurrency or an external service (the data class alone does not trigger it); `uncertainty` is `high` |
| `pin-tests` | one rule, one existing harness, one test file | the rule spans two modules, or the harness does not exist (a fake, a recorder, a process boundary) |
| `review` | one module against its own specification section, with the shipped tests as the harness for reproductions | two or more modules and their seam, where a finding can exist only in the interaction; or no shipped harness for reproductions; or the specification is incomplete and the review must say what it would have to say |
| `research-collect` | the unknowns are enumerated and each names its owning page; the budget is under ten pages | an unknown with no known owning page; a contradiction between primary sources to resolve; a budget over thirty pages |
| `docs-mechanical` | always T1 | never |

T2 is a request that is neither T1 nor T3 in its category.

Rules (proposed):

1. The host declares `difficulty-tier` on the request. Holdshort computes a
   **floor** from the mechanical parts of the predicates it can see (the size of
   the edit set, the `uncertainty` flag, the category) and refuses a declared
   tier below the floor; a declared tier above it is accepted as given (the
   host may know the task is harder than it looks, never easier).
2. A request without a declared tier is treated as **T3** for a high-risk
   category and **T2** otherwise. The default is conservative because a tier
   the host did not think about is the case the Context describes.
3. The tier is printed in the decision as a new line `DifficultyTier: <T1 |
   T2 | T3>` after the existing `Difficulty` line, which is unchanged (its
   enum stays `trivial | moderate | high-or-ambiguous`; a changed enum would
   not be additive), and recorded as `difficulty-tier` on the §10.1 Brief and
   the §10.5 LedgerRecord.

## Item 2 — qualification per (category, tier)

A `qualified-for` entry may carry a tier: `fix@T1`, `review@T3`. Rules:

1. A qualification at tier k covers every lower tier of the same category.
   This is a rule, not an observation: it rests on the predicates being
   nested (a T3 request contains a T1 request's demands), and a profile that
   passes T3 cells and fails a T1 cell would contradict it and be recorded as a
   fail at T1, which blocks T1 and above under rule 4. No run has tested it
   yet; run 4 (Item 4) tests it on the profiles it covers.
2. A bare entry (`fix`) reads as `fix@T1`. For calibration-derived
   qualifications that is the honest reading: the cells that produced them
   are T1 by the table above. For the **production-derived** qualifications
   (`cc-opus-high`, `cc-fable-high`, `cc-fable-xhigh` on this host) the bare
   reading would narrow them, so the revision that adopts tiers re-declares
   each of them, in the same revision, at the tier of the units that produced
   it, with the unit ids as evidence and the reviewer line `host-declared
   (lead), not independent`; a unit's tier is read from its request as Item 1
   would have declared it, and the README names them as "would be T<k> by the
   table" because they were not declared at the time. Nothing narrows
   silently: the revision is reviewed as every policy revision is.
3. The two-pass rule applies per (category, tier): a high-risk category needs
   two independent passes **at that tier** (calibration cells of that tier, or
   an accepted production outcome whose request carried that tier).
4. A calibration FAIL or a `verification-failed` outcome at tier k is a fail
   for tier k and every higher tier of the category, and blocks them until two
   later passes at that tier; lower tiers keep their standing. The learning
   loop's demotion proposal (two consecutive `verification-failed` outcomes)
   moves from (profile, category) to (profile, category, tier).
5. The return path after a block is **calibration, never production**: the
   two later passes come from kit cells at that tier (or an accepted outcome
   at that tier on another host policy that still routes there). Production
   routing on this host cannot grant them, because Gate 2 no longer routes the
   pair; so there is no deadlock, only a cost: a blocked pair stays blocked
   until a calibration run includes it. The host's one same-profile repair
   (R01-R03) is unaffected: it runs under the original allowance before any
   outcome is recorded and is not a fresh decision.
6. The grade-entry form gains the tier: `calibration-<n>: <category>@<tier>
   PASS|PARTIAL|FAIL (n=<k>)`. A tierless entry is read as `@T1`, so every
   existing entry keeps its meaning and the adapter's form check stays
   backward compatible.

## Item 3 — Gate 2 reads the tier; the route set is unchanged

Gate 2 ("task qualification") passes a profile for a request only when the
profile holds the request's category at the request's tier or above. Gates 1,
3, 4 and 5 are unchanged and so is the route set: a T1 request keeps routing
to the cheapest T1-qualified profile, and a T3 request reaches the cheapest
T3-qualified one without a failed cheap attempt first. An empty eligible set
at the request's tier is `blocked` with the reason
`no profile qualified for <category>@<tier>`; when a profile qualified at a
higher tier exists, the reason names it (`cheapest profile qualified at
<category>@<tier+k>: <id>`) as information in the reason text. No
`recommend-escalation` route is introduced: this host's adapter never emits
it (`hosts/claude-code/README.md`, friction item 13), the policy has no order
of strength between profiles, and a route-set change would not leave Gate 5
unchanged.

Re-routing after an outcome (§8.5): a fresh decision after a
`verification-failed` outcome at tier k on a profile does not choose the same
(profile, tier) pair again. That follows from rule 2.4 alone (the pair is no
longer eligible at Gate 2) and needs no separate rule; the same-profile
repair under the original allowance happens before the outcome and is
exempt, as rule 2.5 says. The host either raises the tier (it was declared
too low) or routes to another profile; the second dispatch does not repeat
the first.

## Item 4 — calibration per tier, staged by cost

Calibration run 4 for the Claude Code host adds **T3 cells**, preregistered as
runs 2 and 3 were (frozen protocol with source hashes, history-less checkouts,
a defined classification with the `forbidden` prong in the lens schema,
cross-candidate adjudication for review). T2 is not calibrated in run 4: with
T1 and T3 measured, a T2 request routes to the cheapest profile qualified at
T3 until a later run fills the middle. No existing production unit is given a
tier for qualification evidence; the units named in the Context and in Item
2.2 are "would be T<k> by the table" and are sizing information only. The run
cannot label a cell's tier from its results: each cell's tier is declared in
the protocol by the Item 1 table before the launch.

Candidate T3 tasks, all on material the host already holds and can grade
mechanically:

- `fix@T3`: a defect whose cause is not named, reachable only through two
  functions and their caller (the wire module and the sign-in state machine
  that polls it), with a required behaviour stated as a journey rather than a
  line; graded like the T1 cell (candidate tests green at its head, red with
  the sources restored, the accepted pin green against the candidate's
  source, scope and lint), plus the accepted journey test green.
- `review@T3`: a review of two modules and their seam, where the ground truth
  is a defect that exists only in the interaction (each module is correct
  against its own spec), graded by the run-3 grader with the reachability
  classification and the adjudication step.
- `pin-tests@T3`: a pin that needs a new harness (a fake the shipped tests do
  not have), graded mechanically as the T1 pin is.

**Cell list and bottom-up budget, on the live policy (host-policy-3).** "One
T3 cell per category" means one cell per (category, profile) for every profile
qualified for that category at T1 today:

| Stage | Cells | Per-cell assumption (harness tokens) | Cells total | Judging | Stage total |
|-------|-------|--------------------------------------|-------------|---------|-------------|
| 4a `fix@T3` | the 12 `fix`-qualified profiles: cc-haiku-low, -medium, -high; cc-sonnet-low, -medium, -high; cc-opus-medium, -high, -xhigh; cc-fable-medium, -high, -xhigh | 400k-800k each (the two accepted T3-shaped production units on cc-opus-high ran 575k and 848k with their reviews; a T1 fix cell runs 90k-170k; a cell is graded mechanically, so no grader) | 4.8M-9.6M | mechanical | **4.8M-9.6M** |
| 4b `review@T3` | the 5 `review`-qualified profiles: cc-opus-high, cc-opus-xhigh, cc-fable-medium, cc-fable-high, cc-fable-xhigh | 200k-350k each (run 3 T1 reviews ran 109k-266k) | 1.0M-1.75M | grader 5 x ~110k, clustering ~80k, lenses 3 per cluster x ~100k for an expected 3-6 clusters: 1.5M-2.5M | **2.5M-4.3M** |
| 4c `pin-tests@T3` | the 12 `pin-tests`-qualified profiles | 150k-250k each (T1 pins ran 99k-140k) | 1.8M-3.0M | mechanical | **1.8M-3.0M** |

Total if all three stages run: 9.1M-16.9M harness tokens, 29 cells. Run 2's
39 cells and graders used 7,872,276 tokens and moved the five-hour window
0.27; run 3's 70 agents used 8,531,566. Each stage is a separate preregistered
run, scheduled against the windows under the host's stop rule and never
alongside other delegated work; 4a first, because `fix` is where the ledger
row in the Context sits. The counts above change with the host's policy
revision in force at the freeze (a revision 4 is in preparation on the host),
and the protocol records the revision it was sized on.

Pass rules per cell are preregistered at freeze, before the launch, as in run
3.

## Item 5 — what is measured, and what is not claimed

- The tier of every production request and its outcome are recorded, so the
  learning loop can report, per (profile, category, tier): accepted,
  verification-failed, partial, cost-overrun, and tokens.
- The efficiency claim is made only from that record: tokens per accepted
  outcome at each tier before and after the tiers were enforced, on the same
  host. Until there are at least ten tiered outcomes per category, the host's
  reports say so and claim nothing.
- No model ranking follows: a profile proven at T3 of `fix` is not thereby
  proven at T3 of `review` (run 2 already shows the two do not move together:
  twelve `fix` passes against nine `review` passes).

## Non-goals

- Tiers do not replace `estimatedTokens`, `median-tokens` or
  `headroom-tested`; those bound size, and a T3 request can be small in tokens
  and a T1 request large. `uncertainty` stays as it is and feeds the floor.
- Tiers are not inferred from a model's self-assessment, the brief's prose, or
  a price; the floor in Item 1 uses only structural fields of the request.
- No automatic re-tiering of a request after the fact: a request whose tier
  turned out wrong is a lesson for the host's declaration rubric, recorded in
  the lead's notes, not an edit to the ledger.
- No new route.

## Review record (Items 1-5 pending)

| Item | Decision | Reviewer | Date |
|------|----------|----------|------|
| 1-5 (revision 1, 987a4e3) | Request Changes: seven blocking findings (the fix-u7-r3 description; predicates for non-edit categories; retro-labelling; the re-route rule and the repair rule; the token range; the run-4 count and budget; `recommend-escalation`) and seven non-blocking notes | independent agent session, read-only | 2026-10-18 |
| 1-5 (revision 2) | pending delta review | — | — |
