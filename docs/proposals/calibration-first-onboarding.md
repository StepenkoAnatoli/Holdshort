# Proposal: calibration-first onboarding — a new model or effort enters a host policy only through the kit, and its results go upstream as a pull request

Status: **draft proposal, not normative; revision 2 after the independent
review of 2026-10-18 (Request Changes on c53cd77).** Nothing in `skills/` is
amended by this document. If accepted after independent review (plan §15), the items
below would become one additional host-policy validation rule, one new tools
path holding the calibration kit, one evidence-folder contract with a CI
check, and an additive host-policy field; until then hosts MUST NOT emit or
require them.

## Context

- Gate 2 passes a profile only on a declared, fresh qualification; labels,
  price tier and self-confidence are not capability proof
  (`skills/holdshort/references/spec-v2.md` §4). The Claude Code host
  declares qualifications from graded calibration runs and production outcomes
  under its own rules: two independent passes for a high-risk category, one
  for a normal-risk one, a fail blocking the category until two later passes
  (`hosts/claude-code/README.md`, "Qualification rules").
- The adapter checks only the **form** of a qualification's evidence entries;
  it does not count passes, and nothing stops a host from writing
  `qualified-for: ["fix"]` on a profile with no evidence at all. Today that
  restraint is the lead's, not the policy's.
- Three calibration runs exist (`docs/evidence/2026-10-17/claude-code-calibration/`,
  `.../claude-code-calibration-2/`, `docs/evidence/2026-10-18/claude-code-calibration-3/`),
  each an improvement on the last: a preregistered protocol with source
  hashes, history-less checkouts, a reachability-defined classification, a
  preregistered three-lens adjudication. The method is reproducible in
  principle and **not portable in practice**: the workflow script, the graders'
  prompts, the observation builder, the ground truth and the finding text live
  in one host's session scratchpad; per run, `grade.sh` and
  `historyless-checkout.sh` are copied into the evidence folder, `protocol.json`
  is written there, and the script, the builder, the ground truth and the
  prompts are recorded by hash only. A second host, or a new model on this
  host, starts from a copy of the last run and a lead's memory.
- The runs also found what a kit must guard against: the grader instruction
  ambiguity of run 2 (G-1), the lens schema missing the third prong of its own
  classification in run 3 (G-2), and the host harness relaying the operator's
  chat into every worker as the request that "wins" (A-1, two cells void).
  Each was caught after the run, by reading outputs, and each is a rule a kit
  can carry so that the next host does not rediscover it.
- Cost: run 2 used 7,872,276 harness tokens over 54 agents (39 cells and 15
  graders, the graders 1,713,036 or 21.8%; its cross-candidate adjudication
  was post hoc and is not in that total); run 3 used 8,531,566 over 70 agents
  plus 456,376 in a supplementary run, of which graders, clustering and lenses
  were 38-39% (`#101`, `scores.json` `totals.tokens`). The preregistered
  adjudication step roughly doubled the judging share. A model added without calibration costs
  nothing to add and an unknown amount later. This host has no such case:
  every profile in its policy was calibrated or carries a production-derived
  qualification marked as not independent; the ledger case cited by the
  difficulty-tiers proposal is a mis-tiered dispatch of a calibrated profile,
  which is that proposal's subject, not this one's.

The request behind this proposal, from the operator of the Claude Code host:
every new model or effort level runs the calibration first, and the operator
is asked to push the results upstream.

## Item 1 — calibration-first: no hand-declared qualification

1. A profile may enter a host policy with any `qualified-for`, but every
   category it names MUST be supported by an evidence entry of one of two
   typed forms. (a) A grade entry in the kit's form, `calibration-<n>:
   <category> PASS|PARTIAL|FAIL (n=<k>)`, with the run id entry beside it;
   the adapter's policy validator reads it from the policy alone, as today.
   (b) A **typed production reference**, `outcome: <task-id> <category>
   accepted <ISO date> (<outcome store path>)`, which the validator checks
   for form from the policy alone and, when it is given the outcome store
   (the `--trace` directory the adapter already takes), checks against the
   store: the referenced outcome must exist, be `accepted`, and carry the
   same category as the entry; a reference that cannot be resolved against a
   store the validator was given is refused, and a validation run without a
   store says that production references were checked for form only. The
   free-text production evidence the host policy carries today ("302
   completed dispatches ...", "sr-policy-2 outcome accepted ...") stays as
   prose but no longer supports a `qualified-for` entry on its own; the
   adopting revision rewrites each into form (b) or drops the qualification.
   The validator still does not count passes (the host's rules do); it refuses
   an entry with nothing typed behind it.
2. A new profile with no evidence is valid only as `qualified-for: []`, which
   Gate 2 already refuses to route to. That is the onboarding state: present,
   priced, unroutable.
3. The onboarding run is the kit's T1 cells of every category the host uses
   (pin-tests, fix, review today), under the host's pass rule; a profile
   becomes routable for a category exactly when the host's qualification
   rules say so, and the policy edit that grants it names the runs.
4. The exception that exists today stays visible: a qualification carried from
   before this rule (the Claude Code host's production-derived `cc-opus-high`,
   `cc-fable-high`, `cc-fable-xhigh`) keeps the reviewer line `host-declared
   (lead), not independent`, is rewritten into typed production references in
   the adopting revision (and, if the difficulty-tiers proposal is adopted,
   re-declared at its tier in that same revision, as its Item 2.2 says: the
   two revisions are one when both proposals land), and is re-qualified by
   the kit at its next expiry, never silently extended.

## Item 2 — the kit, under one path, host-independent in method

A new path, `tools/calibration/` (one directory; the exact name is the
reviewer's call), holding what every run so far rebuilt by hand:

| File | What it is | Lineage |
|------|------------|---------|
| `protocol.template.json` | the preregistration form: subject, sources with hash convention, cases with pass rules, metrics, accounting, timing, privacy, limits, amendments; frozen before the launch with the run id recorded | run 3 `protocol.json` |
| `classification.md` | the three-prong definition of a true other finding (holds at HEAD; reachable through the public API with admissible input; forbidden by the spec or the module's promise) and the rule that a contract hole no admissible input reaches is at most S4 | run 3 (G-1 closed) |
| `grader.prompt.md`, `lens.prompt.md`, `cluster.prompt.md` | the grader, lens and clustering prompts with their output schemas; the lens schema carries `forbidden`, and a lens votes real only on all three prongs | run 3 (G-2 closed) |
| `historyless-checkout.sh` | one root commit per cell, so the accepted answer is unreachable | run 3 |
| `grade.sh` | mechanical grading of pin and fix cells against the subject pack's base and accepted trees | runs 1-3 |
| `observations.py` | builds `observations.json` (the flat profile map the adapter's `rate` reads), `scores.json`, `results-table.md`, `clusters.md`, `tokens-and-estimates.md` from the harness journal and run file | run 3 |
| `run.template.js` | the workflow script: items per profile and task, pipelined grading, clustering and adjudication, with the preamble that reconciles a relayed operator request | run 3 (A-1) |
| `subject-pack/README.md` | the format of a subject pack: base tree, accepted fix, ground-truth findings with severities, the required behaviour stated without the fix, pass rules per case, source hashes | runs 1-3 |

Two kinds of subject pack:

- **Shared pack** (shipped in the kit): a small self-contained module with two
  seeded defects of the same shape the runs used (a rejection that breaks a
  "nothing rejects" promise; a bound skipped on an unexpected input), with its
  spec, its tests and its accepted fix. Every host runs it, so its cells are
  **comparable across hosts**. It is synthetic on purpose: no host's private
  code travels, and the pack can be rewritten when it leaks into training
  data (the kit records the pack's version in the protocol).
- **Host pack** (the host's own): a real accepted defect pair from the host's
  repository, as runs 1-3 used. Its cells qualify the profile for the host's
  own categories and are not comparable across hosts. A host may run both;
  onboarding requires the shared pack at least.

**Isolation of the answer.** A candidate's checkout is a history-less tree of
the pack's base state only (`historyless-checkout.sh`); the pack's accepted
fix, ground truth and grader material live outside every candidate's
permitted paths, the candidate prompt names only its checkout, and the kit's
launch step refuses a run whose candidate checkouts share a filesystem path
with the pack directory. A shared pack is also small by construction, and the
kit says so: it discriminates the bounded T1 shape only, and a host that needs
more runs its own pack; pack versions can grow.

The kit contains no provider calls: the host's harness runs the agents, the
kit supplies the prompts, the checkouts, the graders and the builders.

## Item 3 — the run protocol the kit enforces

1. **Preregistration before launch**: the frozen protocol with source hashes
   and the run id recorded before any agent starts; a cell whose prompt or
   checkout differs from the frozen hash is void (run 3 A-1 shows the form).
2. **No operator chat in the workers**: the kit's launch step checks what the
   harness will prepend to each worker; a harness that relays operator chat
   must either suppress it for the run or record the relayed text verbatim in
   the protocol before the launch. A cell that halts on relayed text is void
   and re-run once, never graded as capability.
3. **Judging by a qualified reviewer**: the grader, the clustering agent and
   the lenses run on a profile the host policy qualifies for `review`; a host
   onboarding its first model has no such profile and says so in the protocol
   (the bootstrap case: the first grader is host-declared; the run's README
   names the reviewer of that declaration and carries the limitation line
   "judging profile not independently qualified", and the results carry it
   into the qualification table's caveat column).
4. **One run per profile and task**, retry limit 0, harness retries recorded
   as such (run 2 H-1); the two-pass rule needs two runs, so onboarding is at
   least two runs or one run plus accepted production outcomes.
5. **Readings with nothing in flight** before and after, so the run also
   measures the host's usage-window coefficients (Gate 4 on subscription
   hosts); run 3 could not, and says so.

## Item 4 — results go upstream as a pull request the operator opens

1. The kit writes `docs/evidence/<date>/<host>-calibration-<n>/` in the layout
   runs 2 and 3 use: `protocol.json` (frozen, then amended), `observations.json`
   (flat map), `void-cells.json`, `adjudication.json`, `scores.json`,
   `results-table.md`, `clusters.md`, `grade.sh` and `historyless-checkout.sh`
   as run, and `README.md` with the frozen sections above the results.
2. The kit then prints the request: the branch name, the files, and a pull
   request body in this repository's template (Problem and resulting
   behavior; Related issue; Validation; Remaining limits or risks), filled
   from the protocol and scores, and **asks the operator to open the pull
   request**. The kit never pushes and never opens it: the operator's push is
   the operator's consent that the evidence may be shared, which no agent
   gives for them. It is consent, not acceptance: the pull request is then
   reviewed under plan §15 like any other, by a reviewer who did not run it.
3. What a results pull request must carry to be merged: the frozen protocol
   with the run id recorded before launch; `scores.json` derivable from
   `observations.json` by the kit's builder; every grade entry in the
   adapter's form; the judging profile named with its own qualification; the
   relayed-chat statement from Item 3.2; no secrets, prompts bodies or model
   output beyond the structured returns (`tools/check_secrets.py` already runs
   in the gate). A CI check (provisionally `tools/check_calibration_evidence.py`;
   the name follows the kit layout once settled) runs in the regression gate
   and refuses with a named reason when any of these fails: the frozen
   protocol declares the classification's prongs and the adjudication record
   declares the prongs its lens schema carried, and the two sets are equal;
   `scores.json` derives from `observations.json` by the kit's builder **under
   the declared prongs**, so a review PASS that holds only because a prong is
   missing is not a PASS the check accepts (it must be recorded as
   `would_fail_under_<full definition>` with the preregistered score kept
   beside it, as #101 now does, and such a row is excluded from the table's
   pass count); the pin case's category mapping is the host's (`pin-tests`,
   not the protocol's label); every grade entry is in the adapter's form; the
   judging profile is named with its qualification or the bootstrap
   limitation; the relayed-chat statement from Item 3.2 is present. "Derivable"
   is necessary and not sufficient: the rule the check enforces is the intended
   rule, not the one the run happened to run.
4. A merged results pull request updates one generated table,
   `docs/evidence/qualification-table.md`: host, profile (model, effort,
   config), category, pass/partial/fail per run, run ids, **the adjudication
   schema version and prongs each run's review grade rests on, and a caveat
   column**. A PASS obtained under fewer prongs than the classification
   defines is shown as `PASS (2-prong, would fail)` and excluded from the pass
   count, never as an ordinary PASS; #101's `haiku-medium` and `haiku-high`
   review cells are the first two such rows. The table will be read as a
   ranking whatever it says, so it states what it does not support: no
   ordering between models, no cross-host comparison outside the shared pack's
   cells, and no claim about tiers it did not run.

## Item 5 — relation to the difficulty-tiers proposal

If `docs/proposals/difficulty-tiers.md` is accepted, the onboarding run is the
T1 cells; T3 cells are run only for profiles qualified at T1 and on a host
pack, since a shared pack's T3 task would need a realistic multi-module
subject that a synthetic pack does not carry well. Nothing in this proposal
depends on that one.

## Non-goals

- No model ranking and no cross-host claim beyond the shared pack's cells.
- The kit does not call providers, hold keys, or run outside the host's own
  harness and permissions.
- No automatic qualification: the kit grades; the host's rules qualify; the
  policy edit is the host's, named and dated as today.
- No retroactive void of existing qualifications; Item 1.4 says how they age
  out.

## Review record (Items 1-5 pending)

| Item | Decision | Reviewer | Date |
|------|----------|----------|------|
| 1-5 (revision 1, c53cd77) | Request Changes: five blocking findings (the validator cannot enforce free-text production evidence; the CI check must enforce the intended rule, not a derivable one; the table would erase the G-2 caveat; the uncalibrated-model case mis-cited; the judging figure run-3-only) and eight non-blocking notes | independent agent session, read-only | 2026-10-18 |
| 1-5 (revision 2) | pending delta review | — | — |
