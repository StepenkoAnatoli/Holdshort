# sr-pack-4a, lead integration: the decisions that close F2, R3 and RR2-1 on the host pack moonaliza-x2-1

Verdict: DONE. One commit on `build/sr-pack-4a` on top of b1af660, not pushed; the structured return names the head. The
unit's two fix rounds were spent, so the lead closed what re-review 2 left open with three decisions, recorded here.
The same commit carries re-review 2's report (`sr-pack-4a-rereview-2.md`) exactly as it was written. No kit file changed
(`run.template.js`, `grade.sh`, `historyless-checkout.sh` and `observations.py` are as on b1af660).

## Decisions

| id | finding | decision | why |
|---|---|---|---|
| D-F2 | F2 (S2): the kit's fix prompt prints `Cause: ${f.cause}` (`tools/calibration/run.template.js:159`) | **The kit stays as it is.** The manifest's `findings[].cause` now names no mechanism, location or module: it says the cause is withheld (the candidate's fix prompt at T3 carries the field, and the case is graded mechanically) and that the ground truth is in the pack's README.md, section The journey. The full mechanism stays in that README for human readers. A static test pins it | For a fix-only pack the fix prompt is the only reader of `cause`. Line 176 reads it only for a review case's ground truth (`cases.review.findings`), and this pack has none. `grade.sh` and `observations.py` never read it. So the reworded field loses nothing the grade uses, and the kit change (and the unit it would need) is not worth it. This **overrides brief H3's** "the cause names the reconcile's deletion of unreferenced staged entries during an unread start". H3's premise was "the candidate never sees it", and that premise does not hold with this kit. `cause_rule` keeps the mechanism: the fix prompt does not print it (only the review judging's `truthText` does) |
| D-R3 | R3 (S4): `cases.fix.instructions` pointed at the fix: "the vault reconcile" in the startup order, and "The grade runs the startup lines ..." | The sentence is reworded as a description of how **every** start is driven, "whichever files your change touches". "The vault reconcile" and the finishStartup list are dropped. The F1 limit is still disclosed: the store's `open()`, then the startup lines from the engine-references line up to `supervisor.attach()`, run on their own, with only `vault`, `references`, `collectorSettings`, `githubStore` and what `index.ts` imports from `./github-account-store` or `./vault` in scope. Any other name of `index.ts` there fails the check | It is true: `start()` in the journey test runs a new vault and store, `open()`, then `wiring()` on every start. Without the limit, a correct fix whose wiring uses another name of `index.ts` would fail with no warning (F1). The order itself is in `index.ts`, which the candidate reads anyway |
| D-RR2-1 | RR2-1 (S4): two shapes of a correct fix failed 17 of 18 (a wrapped engine call, and a `/* */` comment whose inner line names the anchor) | Fixed (a correct fix graded FAIL corrupts the calibration). `wiring()` now matches both anchors on `codeOnly(source)`: every comment (line, block or trailing) is blanked to spaces and strings are kept. The slice starts after the end of the statement that holds the engine call: the first code line at or after it that ends with `;` | The remedy re-review 2 named. Disclosed limit (README, "What the pack does not discriminate"): regex literals are not parsed, so a regex literal above the anchors that holds a quote or a comment opener could hide an anchor. The base's `index.ts` has no regex literal |

That the pack files never reach a candidate is confirmed from the kit. `historyless-checkout.sh` copies only the given
commit's tree (base0 = MoonAliza 16f637f's tree) as git objects into a target outside the pack. Its `--pack` refuses a
target inside the pack or a pack inside the target (lines 91-92), and `--link` refuses a dependency directory inside
the pack. `run.template.js:73` refuses a `checkout_root` or `adjudication_checkout` that shares a path with `pack_dir`.
`grade.sh:60` refuses such a checkout. `grade.sh` places the accepted journey test (`paths.accepted_test`) only when it
grades. The candidate's prompt names no pack path, make-repo, zz_accepted, WRONG-FIXES or commit id. The launch test
asserts this, and now also that the prompt carries the new cause verbatim.

## What changed

| file | change |
|---|---|
| `manifest.json` | `findings[0].cause` reworded (D-F2). `cases.fix.instructions` reworded (D-R3). `accepted_fix` (both places) `1cf7ceb6…` to `27860d2cf07a847a16b3a239d570161b14961f05`: accepted0 holds the journey test, which changed. `source_hashes` of `README.md` and `zz_accepted_x2_1.test.ts` |
| `zz_accepted_x2_1.test.ts` | `codeOnly()` added. `wiring()` anchors on it, and `from` advances to the end of the engine call's statement (D-RR2-1). The doc comment says so |
| `README.md` | Files: `cause` withholds the cause. The journey: an explicit **The cause** sentence (the ground truth). Names the test assumes: the new anchor rule. Limits: the regex-literal bullet. Last section: D-F2 and the isolation facts |
| `tools/test_calibration_kit.py` | `X21_CAUSE_WITHHELD`, `X21_ENGINE_CALL`, `X21_LAST_FINISH`, `X21_SLICE_PROBES`. New tests: `test_the_cause_names_no_mechanism_and_the_readme_keeps_it`, `test_the_instructions_state_the_grade_limit_without_pointing_at_the_fix`, `test_the_accepted_fix_reshaped_in_index_ts_stays_green` (clone; added to the UNSUPPORTED list). The cause's old `assertIn("unreferenced staged"/"reconcile")` are removed. The static anchor checks now pin `codeOnly`, block-comment handling and the statement end, and pin that `isCode` is gone. The launch test asserts `Cause: <cause>.` in the prompt |
| `reports/sr-pack-4a-rereview-2.md` | committed as written (untracked until now) |

`CHANGELOG.md` and `WRONG-FIXES.md` are unchanged. The CHANGELOG line is still accurate. Every wrong fix keeps the base's
one-line engine call, so the slice it gets is the same, and the counts are re-verified below.

## Red first

| test | before the change | after |
|---|---|---|
| `test_the_cause_names_no_mechanism_and_the_readme_keeps_it` | FAIL: `'reconcile' unexpectedly found in 'during the start that cannot read the account file ...'` | OK |
| `test_the_instructions_state_the_grade_limit_without_pointing_at_the_fix` | FAIL: `'the vault reconcile' unexpectedly found in "Drive the journey through ..."` | OK |
| `test_the_accepted_fix_reshaped_in_index_ts_stays_green` (clone, journey test at b1af660) | [wrapped engine call] FAIL `(17, 18) != (0, 18)`. [block comments] FAIL `(17, 18) != (0, 18)`. [line comments] ok. 73 s | OK, all three probes 0 of 18 failed (79 s) |

The failing rows in both red probes were the 17 rows that run a start. The vault-default row runs none, and it passed.

## Guard-removal proofs

| guard removed (scratch copy) | result |
|---|---|
| The old cause and the old instructions put back (in memory, `x21_manifest` patched) | both static tests FAIL with the messages above |
| The statement end: `from` set back to the engine call's own line (driver over a copied pack, the repository built from the real one) | [wrapped engine call] FAIL `(17, 18) != (0, 18)`; the other probes ok |
| Block-comment state: `codeOnly` blanks `//` comments only | [block comments] FAIL `(17, 18) != (0, 18)`; the other probes ok |

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (TEMP and TMP on drive C) | 15 tests OK in 2072 s, exit 0 (verified). Every wrong fix W-a..W-n grades FAIL through `grade.sh fix`, with candidateGreen, guardRed, scopeOk true, lint ok, and the `acceptedPin` count out of 18 that `WRONG-FIXES.md` states. The accepted change, `X21_ALTERNATIVE` and `X21_ALTERNATIVE_HELPER` grade PASS. The journey test fails all 12 journey rows at the base, and the 6 other rows pass there. It is green at accepted. make-repo builds the manifest's ids and removes its target on a mismatch. The launch refusals hold, and the prompt carries the new cause. The three reshaped-fix probes are green |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py HostPackX21 Docs Hygiene` without the clone | 28 tests OK, 7 skipped with the UNSUPPORTED reason (verified) |
| `make-repo.sh` on a scratch copy | base0 09fe935e94d43d787d00268fa2a8e67015891668 (unchanged), accepted0 27860d2cf07a847a16b3a239d570161b14961f05. Before the manifest update it exited 1 and named both mismatches, as designed (verified) |
| `npx eslint tests/zz_accepted_x2_1.test.ts` and `npx tsc --noEmit -p .` on a scratch tree of 01a8604 with the new journey test | exit 0 both (verified) |
| `python tools/check_secrets.py` | clean, 0 hits (verified) |
| The MoonAliza clone | `git status` clean. The `node_modules/.vite` and `.vite-temp` timestamps are unchanged (2026-10-24 21:33 and 21:43 +0300). Every run reached `node_modules` through the symlink shell, and the clone was only read (`git archive`, `git show`, make-repo's `cat-file`/`pack-objects`) (verified) |
| Changed files against the permitted paths | the pack directory, `tools/test_calibration_kit.py` and the two reports only (verified) |
| The regression gate through the pre-commit hook | verified by the commit landing (TEMP and TMP on drive C) |

## Still open (unchanged, not this round's)

F4 (`--testTimeout=60000`, ratification), F5 (the clone's old `.vite` / `.vite-temp`, the owner's to delete), and F6
(K3's MoonAliza-name rule stops at `subject-pack/host/`, ratification). Stage 4a's protocol should record
`manifest_sha256` of the new manifest.

## What I got wrong and fixed

- My first `wiring()` edit named the comment-blanked lines `code`, which clashed with `const { code } = transformSync(...)`
  further down (the same clash fix round 2 hit). I renamed it to `codeLines` before any run.
- My first comment-end expression was convoluted (`indexOf(...) + 2` compared with a per-kind floor). I replaced it with
  a plain `end < 0 ? length : ...` before any run. The Python I used for that edit first failed its own anchor
  assertion (escape sequences in a plain string) and changed nothing.
