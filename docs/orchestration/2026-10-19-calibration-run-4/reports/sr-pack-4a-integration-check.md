# sr-pack-4a, integration check: refute-first check of the lead's D-F2, D-R3 and D-RR2-1 on the host pack moonaliza-x2-1

Verdict: **FIX**, for one S3 (IC-1). Checked `build/sr-pack-4a` at 19aeda2 (the lead's integration commit on top of
b1af660) against the integration report (`sr-pack-4a-integration.md`), re-review 2 (`sr-pack-4a-rereview-2.md`), the
brief `run4-pack-4a-builder.md` and `conventions.md`. Fresh context; I wrote none of the change. This report is the only
file this round adds.

D-R3 and D-RR2-1 hold: the instructions no longer point at the fix, the two shapes re-review 2 named now pass, every
wrong fix still grades FAIL with WRONG-FIXES.md's counts, and the accepted fix and both alternatives grade PASS. D-F2
removes the mechanism from `cause`, but the new text puts a pointer to the answer key into the candidate's prompt
(IC-1). Two more eslint-clean shapes of a correct fix still fail 17 of 18 (IC-2), and one guard of the new `codeOnly()`
has no test (IC-3).

## Findings

| id | severity | finding |
|---|---|---|
| IC-1 | S3 | The new `cause` sends the candidate to the pack's ground truth. The kit prints it as `Cause: ${f.cause}.` in the fix prompt (`run.template.js:159`; the launch test now asserts it is there). It reads: "withheld: the candidate's fix prompt at T3 carries this field and the case is graded mechanically, so it states no cause; the ground truth of the cause is in the pack's README.md (section The journey), which no candidate checkout holds". The kit's pack format says the opposite: "the candidate prompt names only the checkout, never the pack" (`tools/calibration/subject-pack/README.md`, isolation paragraph), and the launch test's own comment says the same ("Item 2: the prompt names only the checkout"). The text names a file outside the checkout, says it holds the cause, and names its section. A candidate that goes looking for it skews the measurement. Also, the checkout has its own `README.md` at its root (MoonAliza's), which has no section The journey, so the pointer can mislead a candidate that follows the rules. The guards do not catch this. `test_the_cause_names_no_mechanism_and_the_readme_keeps_it` *requires* `README.md` in the cause, and the launch test's secret list (pack path, make-repo, zz_accepted, WRONG-FIXES, the two ids) has no "pack", "README" or "ground truth". **Fix:** make `cause` name nothing outside the checkout (for example "not stated for this case"). Keep the pointer to the README in the README (it already says this in its last section). Have the cause test assert that the cause names no pack, README or ground truth, and add those words to the launch test's secret list |
| IC-2 | S4 | Two more eslint-clean shapes of a correct fix still fail 17 of 18 (probes below). (a) **The engine call without its `;`** (the subject's eslint has no `semi` rule). `from` moves on to the next code line that ends with `;`, which is the reconcile, so the slice drops the reconcile. Failure: `expected [] to deeply equal [ (2) ]`. (b) **The engine call split into two statements** (`const raw = await engine.control(...)`, then `const references = ....parse(raw)`). The slice starts at the second statement, which re-declares `references`. Failure: `Transform failed ... The symbol "references" has already been declared`. Both are unlikely, because a fix has no reason to touch that line and the subject writes semicolons. For (b), the instructions' "from the line that reads the engine's references" half warns the candidate. Nothing warns about (a): the README states the `;` rule, but the candidate never sees the README. Disclose both in "What the pack does not discriminate", or anchor `from` on the statement's closing `)` plus an optional `;` |
| IC-3 | S4 | No test catches the removal of the string-keeping branch of `codeOnly()`. With that branch turned off, all three committed `X21_SLICE_PROBES` stay 0 of 18, and so do base and accepted: no string above the anchors in `index.ts` holds `//` or `/*`. A probe with `const _glob = 'logs/*.json'; void _glob;` above the engine call is 0 of 18 with the real test and 17 of 18 with the branch removed (`the startup lines of src/main/index.ts were not found`). conventions.md: "A guard no test catches is a missing test". **Fix:** add that probe to `X21_SLICE_PROBES` |
| IC-4 | S4 | The cause test is a word blocklist. A cause such as "the start that cannot read the file lets the vault delete the new pair; see README.md" (it names the mechanism and the location) passes both static tests, and so does a cause that names the pack's full repository path. This fits with IC-1's fix: pin the exact cause text, or check positively that it names nothing |
| IC-5 | S4 | The kit's format still says `findings[].cause` is "where it comes from (the condition, the location)" and that the fix case gives the candidate "its summary, cause and required behaviour" (`subject-pack/README.md`). This pack's cause now deviates from that format. The pack README explains the deviation, but the kit README does not mention it. A kit change is out of this unit's scope, so record it for the kit unit that settles F2 for good |

Still open and not this round's: F4, F5 and F6, unchanged. F5: the clone's `.vite` (2026-10-24 21:33:46 +0300) and
`.vite-temp` (21:43:58 +0300) are unchanged after my runs.

## Does the cause or the instruction still leak the mechanism or the location?

- **Cause (D-F2):** no mechanism, module or code location. "reconcile", "staged", "unreferenced", "references",
  "vault", "index.ts" and "keepStaged" are all absent (verified by reading it and by the static test). But it does give
  away where the ground truth is kept (IC-1).
- **Instructions (D-R3):** "the vault reconcile" and "finishStartup" are gone, and so is the phrasing that read as "the
  grade runs here". What remains names the region of `index.ts` the check runs, from the engine-references line to
  `supervisor.attach()`, and the names in scope there. That is the F1 limit, and dropping it would bring F1 back. The
  region is visible in `index.ts`, which the candidate reads anyway, and the text says nothing about what goes wrong or
  what to change. At most S4, and the trade-off is accepted as the lead decided. Not a finding.
- **required_behaviour** (checked, not a finding): "leaves the new pair in the vault as the crash left it" and "an
  unreferenced staged entry is deleted by the next start that reads the file" come close to the mechanism. The brief
  (finding section, H2 and H3) puts exactly these into the required behaviour, so they are in scope by design.

## Probes: a correct fix in other shapes (the accepted fix plus one edit to `src/main/index.ts`)

The probes ran through a scratch driver (not committed). It subclasses `HostPackX21`, so it reuses `setUpClass`, `at()`,
`vitest()`, `x21_edit` and `x21_shell_modules`. It takes a history-less checkout of `accepted0` from a pack repository
that make-repo built from the clone, places the journey test or a scratch variant of it, edits `index.ts`, runs
`npx eslint src/main/index.ts`, then runs `npx vitest run tests/zz_accepted_x2_1.test.ts --reporter=json`. TEMP and TMP
were on drive C.

| shape | eslint | journey test at 19aeda2 |
|---|---|---|
| committed probe: wrapped engine call | exit 0 | 0 of 18 failed |
| committed probe: block comments naming both anchors | exit 0 | 0 of 18 failed |
| committed probe: line comments naming both anchors | exit 0 | 0 of 18 failed |
| S1: full prettier-style wrap over 7 lines, `"vault.references"` in double quotes, trailing `// the engine's references` after the `;` | exit 0 | 0 of 18 failed |
| S4: `const _glob = 'logs/*.json'; void _glob;` above the engine call (a string holding a comment opener) | exit 0 | 0 of 18 failed |
| S5: `})); /* refs; see spec 4.4 */` (a trailing block comment after the `;`) | exit 0 | 0 of 18 failed |
| S6: a two-line block comment between the anchors with an apostrophe, a lone quote and `supervisor.attach(` | exit 0 | 0 of 18 failed |
| **S2: the engine call without its `;`** | exit 0 | **17 of 18 failed** (IC-2a) |
| **S3: the engine call split into two statements** | exit 0 | **17 of 18 failed** (IC-2b) |

In every failing case, the row that passes is the vault-default row, which runs no start.

## Guard-removal proofs, re-run

| guard removed (scratch variant) | result | integration report |
|---|---|---|
| old cause (b1af660's) put back, `x21_manifest` patched in memory | `test_the_cause_names_no_mechanism_and_the_readme_keeps_it` FAIL: `'reconcile' unexpectedly found in 'during the start that cannot read ...'`. The instructions test OK | same |
| old instructions put back | `test_the_instructions_state_the_grade_limit_without_pointing_at_the_fix` FAIL: `'the vault reconcile' unexpectedly found in "Drive the journey through ..."`. The cause test OK | same |
| statement end dropped (`const from = call;`) | wrapped engine call: 17 of 18 failed (`Transform failed ... Unexpected ")"`). S1: 17 of 18 failed | 17 of 18 |
| block comments not blanked (`next === '/'` only) | block comments probe: 17 of 18 failed (`Expected "*/" to terminate multi-line comment`). S6: 17 of 18 failed | 17 of 18 |
| **strings not kept** (string branch off) | all three committed probes 0 of 18 (**no test goes red**). S4: 17 of 18 failed (`the startup lines of src/main/index.ts were not found`) | not run (IC-3) |
| cause replaced with one that names the mechanism in other words, or with the pack's repository path | both static tests OK (**no test goes red**) | not run (IC-4) |

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (TEMP and TMP on drive C) | 15 tests OK in 2238 s, exit 0 (verified). The run includes `test_every_wrong_fix_grades_fail_on_the_accepted_journey_test_alone`: every W-a..W-n grades FAIL through `grade.sh fix`, with candidateGreen, guardRed, scopeOk true, lint ok, and `acceptedPin` failed equal to WRONG-FIXES.md's count out of 18. It includes `test_the_accepted_and_two_alternative_fixes_grade_pass` (accepted, `X21_ALTERNATIVE`, `X21_ALTERNATIVE_HELPER` PASS), the base red 12 of 18 and green at accepted, make-repo's ids, the launch refusals with the new cause in the prompt, and the three reshaped-fix probes |
| No kit file changed b1af660..19aeda2 | `git diff --name-only`: the three pack files, `tools/test_calibration_kit.py` and the two reports only (verified) |
| The MoonAliza clone | `git status` clean, `.vite` and `.vite-temp` timestamps unchanged. Every run reached `node_modules` through the kit's symlink shell, and the clone was only read (verified) |
| The regression gate through the pre-commit hook on this report's commit | verified by the commit landing |

## For the lead

1. IC-1 (S3): reword `cause` so it names nothing outside the checkout, and tighten the cause test and the launch
   test's secret list. This is a manifest and test change in the unit's paths. `accepted0` does not move, because the
   manifest is not in the pack repository.
2. IC-2, IC-3 and IC-4 (S4): cheap to do in the same round: two probes and a disclosure, or the closing-paren anchor.
3. IC-5: note it for the kit unit that settles F2 for good.

## What I got wrong and fixed

Nothing to report.
