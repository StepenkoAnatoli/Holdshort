# Proposal: difficulty tiers — qualify a profile per (category, tier), not per category

Status: **draft proposal, not normative.** Nothing in `skills/` is amended by
this document. If accepted after independent review (plan §15), the items
below would become one additional Gate 2 rule, an additive host-policy
qualification form, additive §9/§10 fields under the §13 "additive unknown
fields remain ignorable" rule, and one calibration-protocol change for the
host under `hosts/claude-code/`; until then hosts MUST NOT emit or require
them.

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
  it.
- The cost of that gap is on the host's ledger. On 2026-10-18 the unit
  `fix-u7-r3` (a fix round on seven review findings across a main-process
  module, its wiring and its tests) routed to `cc-haiku-low` as the cheapest
  `fix`-qualified profile, used 1,012,799 tokens, and ended
  `verification-failed` after two review rounds; the lead fixed the residue
  inline (`hosts/claude-code/trace/ledger.jsonl`, `fix-u7-r3` seq 2 and 4,
  when the adapter copy is next refreshed; the MoonAliza run ledger
  `docs/orchestration/2026-10-16-github-sign-in/RUN.md` carries the unit).
  The calibration `fix` cells that qualified the same profile ran at
  113,230-174,821 tokens (`host-policy.json`, `cc-haiku-low` evidence). One
  mis-tiered dispatch cost six to nine calibration fixes and still needed a
  stronger profile afterwards. That is one observation, not a rate; the
  proposal exists so the rate can be measured.
- The reverse waste is invisible on the ledger: a bounded fix sent to
  `cc-opus-high` because the lead did not trust the cheap profile is recorded
  as an accepted outcome, and nothing says a `cc-haiku-low` would have done.

The efficiency a difficulty axis buys is therefore two-sided: cheap profiles
keep the bounded work they are proven on, and open-ended work goes to the
cheapest profile proven on open-ended work instead of failing once first.

## Item 1 — the tier scale, declared from observable request facts

Three tiers, the same for every category. A tier is a property of the
**request**, declared by the host from facts the request already carries, and
recorded. It is not an estimate of tokens (that is `median-tokens` and
`headroom-tested`) and not a price.

| Tier | Name | Declared when ALL hold | Examples (this host) |
|------|------|------------------------|----------------------|
| T1 | bounded | the edit set (`permitted-effects` minus tests and the architecture map) is one file; the cause, or the rule, is named in the request; the acceptance checks run on an existing harness | the calibration `fix` and `pin-tests` cells; a one-finding fix round |
| T2 | local | the edit set is two or three files inside one module or seam; the cause is named or one hypothesis is given; new tests may be needed but the harness exists | a fix round of several findings on one module and its test file |
| T3 | open | any of: the edit set spans more than three files or more than one seam; the cause is unknown; the request names concurrency, persistence, credentials or an external service as the subject; the acceptance checks need a new harness; `uncertainty` is `high` | `fix-u7-r3`; a policy revision across the adapter, its tests and its goldens |

Rules (proposed):

1. The host declares `difficulty-tier` on the request. SmartRouter computes a
   **floor** from the mechanical parts it can see (the size of the edit set,
   the `uncertainty` flag, the category's risk subject list) and refuses a
   declared tier below the floor; a declared tier above it is accepted as
   given (the host may know the task is harder than it looks, never easier).
2. A request without a declared tier is treated as **T3** for a high-risk
   category and **T2** otherwise. The default is conservative because a tier
   the host did not think about is the case the ledger row above describes.
3. The tier is printed in the decision as a new line `DifficultyTier: <T1 |
   T2 | T3>` after the existing `Difficulty` line, which is unchanged (its
   enum stays `trivial | moderate | high-or-ambiguous`; a changed enum would
   not be additive), and recorded as `difficulty-tier` on the §10.1 Brief and
   the §10.5 LedgerRecord.

## Item 2 — qualification per (category, tier)

A `qualified-for` entry may carry a tier: `fix@T1`, `review@T3`. Rules:

1. A qualification at tier k covers every lower tier of the same category
   (a profile proven on open work is proven on bounded work).
2. A bare entry (`fix`) reads as `fix@T1`. That is the honest reading of every
   calibration-derived qualification in the current policy: the cells that
   produced them are T1 by the table above. Production-derived
   qualifications (`cc-opus-high`, `cc-fable-high`, `cc-fable-xhigh`, from
   accepted units) are re-declared by the lead at the tier of the units that
   produced them, with the unit ids as evidence; a unit's tier is read from
   its request as Item 1 would have declared it.
3. The two-pass rule applies per (category, tier): a high-risk category needs
   two independent passes **at that tier** (calibration cells of that tier,
   or an accepted production outcome whose request carried that tier).
4. A calibration FAIL or a `verification-failed` outcome at tier k is a fail
   for tier k and every higher tier of the category, and blocks them until two
   later passes at that tier; lower tiers keep their standing. The learning
   loop's demotion proposal (two consecutive `verification-failed` outcomes)
   moves from (profile, category) to (profile, category, tier).
5. The grade-entry form gains the tier: `calibration-<n>: <category>@<tier>
   PASS|PARTIAL|FAIL (n=<k>)`. A tierless entry is read as `@T1`, so every
   existing entry keeps its meaning and the adapter's form check stays
   backward compatible.

## Item 3 — Gate 2 reads the tier

Gate 2 ("task qualification") passes a profile for a request only when the
profile holds the request's category at the request's tier or above. Gates 1,
3, 4 and 5 are unchanged: Gate 5 still takes the cheapest eligible profile,
so a T1 request keeps routing to the cheapest T1-qualified profile, and a T3
request reaches the cheapest T3-qualified one without a failed cheap attempt
first. An empty eligible set at the request's tier is `blocked` with the
reason `no profile qualified for <category>@<tier>` (or
`recommend-escalation` naming the cheapest profile qualified at a higher
tier, where one exists and the host opted in to escalation advice).

Re-routing after an outcome (§8.5): a fresh decision after a
`verification-failed` outcome at tier k on a profile MUST NOT choose the same
(profile, tier) pair again; either the tier was declared too low, and the host
raises it, or the profile is not up to it, and the fail in rule 2.4 removes it
from the eligible set. Either way the second dispatch does not repeat the
first.

## Item 4 — calibration per tier, staged by cost

Calibration run 4 for the Claude Code host adds one **T3 cell** per category,
preregistered as runs 2 and 3 were (frozen protocol with source hashes,
history-less checkouts, a defined classification, cross-candidate
adjudication for review). T2 is not calibrated in run 4: with T1 and T3
measured, a T2 request routes to the cheapest profile qualified at T3 until a
later run fills the middle, which costs more on T2 work than a wrong guess
would save.

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

Scope and cost, so this is decided and not drifted into: only profiles
already holding the category at T1 after run 3 are run at T3 (today `fix`: nine
profiles; `review`: four to six, pending run 3's grades), one run each, which
is about 15-20 cells. Run 2's 39 cells and graders used 7,872,276 tokens and
moved the five-hour window 0.27 (`docs/evidence/2026-10-17/claude-code-calibration-2/`).
At the T3 cells' larger size (a production T3 fix ran 1.0M tokens on
`cc-haiku-low` and 575k-848k on `cc-opus-high`) the run is budgeted at 8-12M
tokens and scheduled against the windows under the host's stop rule, not
alongside other delegated work.

Pass rules per cell are preregistered at freeze, before the launch, as in run
3; the tier of each cell is declared in the protocol by the Item 1 table, so
the run cannot retro-label a cell's tier from its results.

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

- Tiers do not replace `median-tokens` or `headroom-tested`; a T3 request can
  be small in tokens and a T1 request large.
- Tiers are not inferred from a model's self-assessment, the brief's prose, or
  a price; the floor in Item 1 uses only structural fields of the request.
- No automatic re-tiering of a request after the fact: a request whose tier
  turned out wrong is a lesson for the host's declaration rubric, recorded in
  the lead's notes, not an edit to the ledger.

## Review record (Items 1-5 pending)

| Item | Decision | Reviewer | Date |
|------|----------|----------|------|
| 1-5 | pending | — | — |
