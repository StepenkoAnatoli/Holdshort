# Calibration run 4: the lead's plan (prepared 2026-10-19 03:xx UTC, before the seven-day reset)

Moved on 2026-10-19 from MoonAliza `build/github-sign-in` (`docs/orchestration/smartrouter/briefs/`, commit 46113d9)
into this Holdshort run folder, on the operator's instruction that Holdshort work lives in Holdshort. The
decisions are unchanged. What changed: the paths, the facts PRs #106-#109 settled (the kit, pack and check are on main),
and where the adapter runs: Holdshort `hosts/claude-code/` now records the run (decisions, dispatches, outcomes,
readings). MoonAliza is read only, for the subject trees the packs export.

The tiers proposal Item 4 (Holdshort `docs/proposals/difficulty-tiers.md`, merged as #100) stages run 4 by cost:
4a `fix@T3`, 4b `review@T3`, 4c `pin-tests@T3`. Host-policy-6 (E6) adds a fourth need of its own: one T1 host-pack
cell for each of `build-core`, `build-tests`, `research-collect` and `docs-mechanical`, the categories that lost
every delegate for want of outcome rows. This plan covers 4a and the T1 cells; 4b and 4c wait for their subjects.

## Why nothing launches before 2026-10-24 18:00 UTC

Reading 2026-10-19T03:01:34Z: five_hour 0.05, seven_day 0.80. Gate 4 admits a dispatch only while the projection
stays within stop-at minus lead-reserve, 0.90 - 0.10 = 0.80 for seven_day; at 0.80 every projection exceeds it. So
the units below, and the runs, are dispatched after the seven-day reset (resets-at 2026-10-24T18:00:00Z), from a
fresh reading. Preparation is lead-only work: this plan, the briefs, the request files, the ledger entry.

## Decisions (R4-1 .. R4-9; the alternative set aside is named)

- **R4-1. Stage 4a subject: X2-1 (calibration-2 cluster C-B), base `16f637f`, accepted `01a8604`.** An accepted
  production fix (fix-x2-1, cc-haiku-high, outcome seq 3 accepted 2026-10-18) whose edit set spans three source
  modules and two seams (the account store, the vault's reconcile, the startup wiring), in persistence code, with the
  cause unnamed in the journey: T3 by every predicate of the Item 1 table. The required behaviour is a journey ("a
  sign-in that crashes after the file write and before the commit, followed by a start whose account file cannot be
  read, followed by a readable start, ends with that pair committed and live"), never a line. Set aside: run 3's
  clusters C-1..C-3 (the wire module's body phase never observes the timeout signal; cancel unbounded), the subject
  the proposal sketches. It is not fixed yet, so it has no accepted tree; once its fix lands it is the natural
  subject for 4b `review@T3` (a defect at the seam of the wire module and the state machine that polls it).
- **R4-2. 4a cells and budget.** One `fix@T3` cell for each of the 12 fix-qualified profiles of the proposal's table
  (cc-haiku-low, -medium, -high; cc-sonnet-low, -medium, -high; cc-opus-medium, -high, -xhigh; cc-fable-medium,
  -high, -xhigh): under host-policy-6 the bare `fix` holders are cc-haiku-medium/-high, cc-sonnet-low/-medium/-high,
  cc-opus-medium/-xhigh, cc-fable-medium/-high, plus cc-opus-high at `fix@T2`; cc-haiku-low and cc-fable-xhigh are
  run as well (cc-haiku-low was demoted from `fix` on two verification-failed outcomes, and the cell measures whether
  the demotion holds at T3; cc-fable-xhigh is the lead-direct profile, measured for the record). 400k-800k tokens a
  cell, 4.8M-9.6M in all, mechanical grading, no grader. Projected movement: five_hour 0.24-0.48 (0.05 per Mtok),
  seven_day 0.07-0.14. Launched alone, from a clean reading below five_hour 0.30, never alongside other delegated
  work (Item 3.5 and the readings rule).
- **R4-3. The pack's discriminating power is its accepted pin, and the wrong-fix matrix is written first.** sr-pack's
  four review rounds each found a wrong fix the previous pin let through. The 4a pack brief therefore asks for the
  matrix of wrong fixes before the pin: every plausible wrong fix the lead and the builder can name, each shown to
  grade FAIL on the accepted pin alone, and the accepted fix plus one alternative correct fix PASS.
- **R4-4. The T1 cells need the kit to carry a category and a gate-graded case.** The kit's manifest keys cases
  `pin | fix | review` and the adapter's `rate` maps them to `pin-tests | fix | review` by position
  (`CALIBRATION_TASKS`). A `build-core` cell is fix-shaped on persistence code; a `build-tests` cell is pin-shaped
  against mutants; `research-collect` and `docs-mechanical` cells are graded by a command's exit code with hash
  invariants. So: one kit unit (`sr-kit-cases`, Holdshort, from main) adds `category` on the task object,
  `mutants` for a pin case, and a `gate` case kind; one adapter unit (`sr-policy-7`, host-policy-7) reads the task
  object's `category` when present and the `gate` task. Set aside: four fix-shaped cells all labelled `fix` and a
  hand-written mapping at ratification (the evidence check, rule e, would refuse a category the observations do not
  carry, and the table would print them as `fix`).
- **R4-5. T1 subjects, all on MoonAliza `build/github-sign-in`, each an accepted change with an existing harness.**
  `build-core`: U2-R7 (`18a6d21`, one source file, one test file, the account store's not-durable clear; the rule
  named, persistence code) framed as "implement the stated rule", fix-shaped. `build-tests`: tests for three stated
  rules of the wire module `src/main/github-oauth.ts` at its accepted tree, graded green at head and red at each of
  three single-rule mutants (pin-shaped with `mutants`). `research-collect`: `docs/research/2026-10-03-electron-fuses`
  (6 pages, 7 unknowns, brief present) with its closure removed as the base, graded by preflight and handoff exit 0
  with the ledger and every capture byte-identical (gate-graded; a builder machine cannot collect, which is the point:
  the cell closes from the cached corpus and spends nothing). `docs-mechanical`: the five-part commit report of a
  given commit written from its diff and test log against the protocol's checklist, graded by a checker the pack
  ships (gate-graded). The builder may propose a better subject in its report; it builds the one named.
- **R4-6. T1 profiles: cc-haiku-high, cc-sonnet-high, cc-opus-high per category**, 12 cells, about 2.7M tokens
  (316k, 250k, 232k, 92k medians x 3). `build-core` needs two passes (rule 2): the second comes from a later run or an
  accepted production outcome; one run qualifies the normal-risk three.
- **R4-7. Order after the reset.** (1) `sr-pack-4a` and `sr-kit-cases` in parallel (independent; the 4a pack is
  fix-shaped and needs no kit change). (2) `sr-policy-7` and `sr-packs-t1` after `sr-kit-cases` lands (both read the
  new manifest keys). (3) Freeze and launch 4a from a clean reading. (4) Freeze and launch the four T1 runs, one
  launch each, in the next five-hour window. (5) Ratify: host-policy-8 with the grade entries. Units about 1.0-1.5M
  tokens each (sr-pack and sr-evidence ran 1.1M and 1.5M): about 5M, plus the runs 7.5M-12.3M; 0.19-0.26 of the new
  week in all.
- **R4-8. Protocol for 4a.** `protocol.template.json` filled: kind `host`, pack `moonaliza-x2-1`, the fix case at
  `T3` (its tier declared by the table before the launch, as Item 4 requires), no pin and no review case,
  `judging_profile` filled with cc-opus-high and its `review@T1` typed reference and the note that no cell uses it
  (the launch step requires one), `relayed_operator_text` recorded at the launch from the operator's latest chat
  message (A-1: the harness relays it; the candidate preamble reconciles it), both readings taken with nothing in
  flight, `revision` the Holdshort commit the kit is read from (Holdshort main, 311c36f or the head the
  launch reads). The freeze commit goes into Holdshort `docs/evidence/<date>/claude-code-calibration-4a/`; the host
  trace gets `trace/calibration-4/` when the results come back (the adapter reads `calibration-<n>`, so the four T1
  runs are `calibration-5` to `calibration-8` in the trace and named by category in their evidence folders).
- **R4-9. What is not claimed.** No ordering between profiles, no T2 claim (Item 4: a T2 request routes to the
  cheapest profile qualified at T3), and the T1 cells qualify a profile for the host's own categories only.

## Dispatch commands (after the reset; the request files are beside this plan)

```
cd <Holdshort checkout>/hosts/claude-code
RQ=../../docs/orchestration/2026-10-19-calibration-run-4/briefs/requests
node route.mjs usage <reading.json>          # a reading under 30 minutes old, nothing in flight
node route.mjs decide $RQ/sr-pack-4a.json    # then dispatch, as for sr-pack
node route.mjs decide $RQ/sr-kit-cases.json
# after sr-kit-cases lands: sr-policy-7.json, sr-packs-t1.json
```

Each request declares `difficultyTier` (T3: edit sets above three files, new harness parts). Worktrees: every unit from
Holdshort (the kit units from main; sr-policy-7 and sr-packs-t1 from the branch carrying sr-kit-cases); MoonAliza
is read from a clone, never written.

## Follow-ups recorded from the re-review of 2026-10-19

- Kit hardening after run 4 (reviewer's R-2 decision): `historyless-checkout.sh` and the launch step refuse a TARGET or
  checkout root that can realpath-reach the kit's own `subject-pack/*/trees/accepted/`, so a host checking out inside
  the kit tree is caught by the kit rather than by its README. Not before run 4: it needs the kit to know its install
  root.
- The four dropped entries stay dropped until the T1 host-pack cells qualify a profile (the operator's decision).
