# Unit sr-policy-2: host policy revision 2 from calibration run 1

Worktree and branch: created by the lead from the integration head after the usage-windows unit lands
(named in the launch prompt). Work only under `docs/orchestration/smartrouter/`. Node 24 at
`/versions/node/v24.21.0/bin`; suite `node --test docs/orchestration/smartrouter/route.test.mjs`. Commit
identity and trailer lines as in `briefs/router-builder.md`; never --no-verify; no push; never edit
`trace/ledger.jsonl` or `trace/decisions/hand-*.json` by hand.

## Why

Calibration run 1 (`trace/calibration-1/`, run `wf_052c5f34-973`) measured twelve profiles on three graded
tasks. Qualification is declared by the host from evidence (SmartRouter: declared, never inferred), so the
evidence changes the policy, through the lead's rules below, and `rate` keeps learning from outcomes.

## The lead's qualification rules (write them into the README's qualification section)

1. A profile is qualified for a category only on evidence from a task representative of that category: a
   calibration cell whose task matches the category, or a recorded production outcome in it.
2. High-risk categories (`build-core`, `review`, `fix`) need two independent passes (two calibration runs,
   or one plus an accepted production outcome); normal-risk categories need one.
3. A calibration fail in a category is recorded as such and blocks qualification for that category until two
   later passes; the learning loop's demotion rule stays as it is.
4. The pin task (a bounded red-first pin, no source change) represents a new normal-risk category
   `pin-tests` (median 120000 tokens; verification: lint, the new tests green, guard-removal proof, the lead
   reads the diff), not `build-tests` (U7-sized units are 250000-token engine journeys the pin does not
   represent).

## Deliverables

A. `host-policy.json` becomes `policy-revision: host-policy-2`: the `pin-tests` category; profiles
   `cc-sonnet-low`, `cc-sonnet-medium`, `cc-sonnet-high`, `cc-opus-medium`, `cc-haiku-low`,
   `cc-haiku-medium`, `cc-haiku-high`, `cc-fable-medium` present with `qualified-for` per the rules and the
   calibration table (`trace/calibration-1/results-table.md`): every profile with a pin PASS gets
   `pin-tests`; `review`/`fix` stay unqualified for the profiles with one pass (rule 2) and are recorded
   under a new per-profile `evidence` entry `calibration-1: review PASS (n=1)` etc.; `cc-opus-high` and
   `cc-fable-high` keep their existing qualifications (production evidence) and gain the calibration entries;
   the review FAILs (haiku-low, haiku-medium, haiku-high, sonnet-high) are recorded as fails. `qualified-at`
   2026-10-17, `expires` 2027-01-15, reviewer "host-declared (lead) from calibration-1 grades" for the new
   entries. Keep `cc-fable-xhigh` as the lead-direct profile.
B. The goldens: the three `hand-*.json` decisions were walked under host-policy-1 with five profiles. Copy
   the pre-revision policy to `trace/decisions/host-policy-1.json` (a fixture, never edited) and make the
   golden tests decide against that fixture (`--policy`), so they keep reproducing exactly; add one new
   golden-style assertion that the same three requests under host-policy-2 still route to the same
   profiles (the new profiles are not qualified for build-core/review/fix), with the candidates block now
   listing the new profiles as ineligible at Gate 2.
C. `rate`'s stats must count calibration evidence separately from outcomes: do NOT write calibration cells
   into the ledger; `rate` reads `trace/calibration-1/observations.json` if present and prints a
   `CALIBRATION` line per profile and category (pass/fail counts) next to the outcome stats; proposals
   stay outcome-based.
D. README: the qualification table regenerated from the policy; the rules above; a note that economics now
   routes `pin-tests` to the cheapest qualified profile (haiku-low at the output-rate bound $0.06 for a
   120000-token pin) and that every pin is verified mechanically (red/green) plus the lead's diff read.
E. Tests red-first: policy validation of the new fields; the fixture goldens; the host-policy-2 routing
   assertions (a `pin-tests` request routes to cc-haiku-low; a `review` request still to cc-opus-high; a
   `fix` request still to cc-opus-high); `rate` printing the CALIBRATION lines and ignoring them for
   proposals; guard proofs for each.

## Non-goals and stop triggers

No change to gate order or reason texts; no qualification beyond the rules above (a cheaper profile does
not get a high-risk category on one pass however good its run looked); stop and report if a golden cannot
be kept exact under its fixture.
