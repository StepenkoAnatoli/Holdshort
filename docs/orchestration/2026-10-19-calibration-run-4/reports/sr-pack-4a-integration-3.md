# sr-pack-4a, lead integration round 3: the real cause hidden by the kit key, the parsed startup slice, F5 at its root

Branch `build/sr-pack-4a`, rebased onto `build/sr-kit-cases` (09b476d), then one commit for this round (its sha is in
the structured return; this file is part of it). The integration check's findings (`sr-pack-4a-integration-check.md`):
IC-1 and IC-4 settled by decision 2, IC-2 by decision 3, IC-3 by decision 4, IC-5 by decision 5; the owner's F5 by
decision 6. Every run had TEMP and TMP on the gittoken `.tmp-gate` folder; the MoonAliza clone was only read.

**This round was continued after a stop.** The first fixer of round 3 was stopped for the owner's PC shutdown
(2026-10-25 10:08Z) after the rebase and its edits, before its guard proofs, the kit suite and its commit. A second
fixer took its uncommitted worktree as an untrusted draft, checked decisions 1-7 against it, and re-ran every
validation itself; no log from before the stop is cited below. What the continuation changed in the draft:

- The README's journey section held the cause and the next sentence as two unwrapped lines (254 and 174 characters,
  against the file's 120): rewrapped, and the cause test now compares the README whitespace-normalised, so the wrapped
  cause is still pinned word for word. `source_hashes["README.md"]` updated.
- This report: the old-sha -> new-sha table had wrong labels for three commits; the rebase is described as the
  command that ran; the guard tables, decision 7 and the "what I got wrong" list now hold the continuation's own runs.
- Re-verified and kept as drafted: the manifest (real cause, `cause_in_prompt: false`, instructions, commands), the
  journey test, the probes, the F5 tests and every README/CHANGELOG change but the rewrap.

## Decision 1: the rebase

The rebase ran as `git rebase` of the seven commits of this unit onto `build/sr-kit-cases` (09b476d); both branches
start at origin/main 0a6d341, so it is the `git rebase --onto build/sr-kit-cases 0a6d341 build/sr-pack-4a` the lead
named (reflog: `rebase (start): checkout build/sr-kit-cases`). Only `CHANGELOG.md` conflicted (at commits 1, 3 and 5,
the ones that touch the pack's line): both lines kept as separate lines, the kit's `- **Calibration kit: run 4 case
keys** ...` line above the pack's. `tools/test_calibration_kit.py` and `tools/calibration/subject-pack/README.md`
merged without a conflict. Checked by the continuation: `git range-diff 0a6d341..d154326 09b476d..HEAD` shows only
the CHANGELOG context lines changed (four commits `=`, three `!` with that context alone); every rebased commit holds
exactly one kit line and one pack line and no conflict marker; `git diff 0a6d341 d154326` and `git diff 09b476d
4795b53` have the same stat (17 files, +2313 -19); no kit file is changed by the unit beyond the pack paragraph in
`tools/calibration/subject-pack/README.md` that commit 1 has always carried.

| old | new | commit |
|---|---|---|
| c43b04c | 3981310 | feat: host subject pack moonaliza-x2-1 |
| 9d02f61 | 10bfbd2 | docs: review 1 (FIX) |
| ad5138f | fe0a8e6 | fix: review 1 findings F1, F3, F7, F8 |
| 12d3e3e | ffe6454 | docs: re-review 1 (FIX) |
| b1af660 | a70c639 | fix: re-review 1 findings R1, R2, R4 |
| 19aeda2 | 3cba2f0 | fix: lead integration D-F2, D-R3, D-RR2-1 |
| d154326 | 4795b53 | docs: integration check (FIX) |

**The rebased intermediate commits were not re-gated**: the rebase rewrote them without running the pre-commit hook on
each. This round's commit runs the full regression gate through the hook on the whole tip (the kit's commits plus all
of this unit's), and that is the gate that stands for the branch.

Set aside: `git merge` of the kit branch (keeps the old shas but puts a merge commit into a stacked branch the lead
wants linear); re-gating every rebased commit (7 x 36-50 min, and only the tip is what merges).

## Decision 2: the real cause, hidden by `cases.fix.cause_in_prompt: false`

- `findings[].cause` is the real cause again, word for word the text of c43b04c / ad5138f / b1af660 (checked against
  base `index.ts` 193-198 and `vault.ts` `reconcile`): "during the start that cannot read the account file the store
  names no references, and the vault reconcile that start runs deletes every unreferenced staged entry, so it deletes
  the new pair the unread file still names". `cases.fix.cause_in_prompt` is `false`; `isolation` says so.
- N-1 (summary, required behaviour and instructions are printed verbatim): read each against the cause.
  - `summary`: the journey and its symptom ("the readable start finds the refs the file names gone"), no mechanism.
    Unchanged.
  - `required_behaviour`: "leaves the new pair in the vault as the crash left it" and "an unreferenced staged entry is
    deleted by the next start that reads the file" come closest. Both are the brief's own required behaviour (finding
    section and H3: "an unreferenced staged entry is deleted on the next readable start"), so they stay; they state
    what must hold, not why it fails. Unchanged. (The subject's `promise` carries the same clause.)
  - `instructions`: reworded for decision 3 only. It describes how the check drives a start (the store's `open()`, then
    the startup statements) and its limits; it names no reconcile, no staged entry, no reference set.
- The round-1 cause tests (a hand list of mechanism words) are replaced by
  `test_the_fix_prompt_carries_the_finding_but_not_its_cause`. It renders the fix prompt through the kit's own
  `run.template.js` (stub harness, the same `x21_launch_config` the launch test now uses) and asserts:
  `cause_in_prompt` is `False`; the prompt holds `THE FINDING (X2-1, S3): <summary>. Required behaviour: <rb>.` and
  the instructions; no `Cause:`; neither the cause nor any of six phrases taken verbatim from it
  (`X21_CAUSE_PHRASES`), compared word-normalised; no pack path, no `subject-pack`, no pack file name; and the pack
  README states the manifest's cause. The phrases are tied to the cause, not chosen by hand: the test asserts each is
  in the cause, and that every word of the cause the summary lacks is in one of the phrases.
- Red first (continuation's run): with the real cause and no key, the test fails (`None is not False`); the kit's
  template, run on the manifest without the key, renders `Cause: <the real cause>.` into the prompt beside the summary
  and the required behaviour, and with the key `false` renders neither the clause nor the cause. Green with the key.
- Guard proofs (continuation's run; each a scratch copy of the pack under `.tmp-gate`, `X21` pointed at it, the test
  alone): control (unchanged copy): green. C1 key removed: red (`None is not False`); C1b key `true`: red; C2 "because
  the vault reconcile that start runs drops it" added to the summary: red (the phrase found in the prompt); C3 "At that
  start the store names no references." added to the instructions: red; C3b "it deletes every unreferenced staged
  entry today" added to the required behaviour: red; C4 `WRONG-FIXES.md` named in the instructions: red; C5 the
  README's cause reworded: red; C6 the manifest's cause reworded so a phrase is gone: red (the phrase is no longer in
  the cause).
- Limit (disclosed here): the phrase check is textual. A paraphrase of the cause in the summary or instructions
  ("the store knows no refs there") would pass it; the reviewer reads those three texts.

Set aside: keeping the withheld text (IC-1: it pointed at the answer key); "not stated for this case" (loses the ground
truth the kit's grader prompt would read for a review case, and the lead decided for the real cause); a hand list of
mechanism words (IC-4: a blocklist).

## Decision 3: IC-2, the slice made robust by parsing `index.ts`

The journey test now parses the candidate's `src/main/index.ts` with TypeScript (`ts.createSourceFile`; typescript
5.9.3 is a devDependency of the subject, like esbuild) instead of matching lines:

- the statement holding the engine call (a call whose object argument has `method: 'vault.references'`), climbed to
  the statement whose parent is a block or the file;
- `to`: the first later statement of that block that contains `supervisor.attach()`;
- `from`: that statement, or, if it does not declare `references` and a later one before `to` does (the call split
  into two statements), that later one;
- body: the source from the end of `from` to the start of `to`; the imports are read from the AST too (named,
  renamed, default, namespace; type-only binds nothing). `codeOnly`, the regex anchors and the regex imports are gone.

Probes added to `X21_SLICE_PROBES` (each eslint-checked by the probe test now, and the files it touches reset from
`accepted0` between probes; before, only `index.ts` was reset and lint was not run):

| probe | old test (3cba2f0's) | new test |
|---|---|---|
| the engine call without its semicolon (IC-2a) | RED 17 of 18 | green |
| the engine call split over two statements (IC-2b) | RED 17 of 18 | green |
| no semicolon on any startup line | RED 17 of 18 | green |
| a statement after the engine call on its line | RED 17 of 18 | green |
| the last startup statement on the line of supervisor.attach() | RED 10 of 18 | green |
| a regex literal holding a comment opener above the engine call | RED 17 of 18 | green |
| an imported helper whose import carries comments between its names | RED 17 of 18 | green |
| a string holding a comment opener above the engine call (IC-3) | green | green |
| the engine call continued on the next line (`.then`) | green | green |
| a string holding a bracket between the anchors | green | green |
| wrapped engine call, block comments, line comments (earlier rounds) | green | green |

All 13 probes lint clean with the subject's eslint (asserted by the probe test, in the full run of decision 7). The
"old test" column is the continuation's run R1: the class built from the real pack, then 3cba2f0's journey test as it
is written into the checkout, the ten new probes run (`guard_driver.py late`, outside the repository): the seven
probes marked RED failed at exactly those counts, the three marked green passed.

Hunt for other eslint-clean correct-fix shapes the check would misgrade, and what was done:

- handled by the parser: missing `;`, statements sharing a line with either anchor, comments or strings or regex
  literals anywhere, multi-line or commented imports, a default import from the modules in scope, a quoted `'method'`
  key or a template-literal method string, `await supervisor.attach()`, `supervisor?.attach()`, a `try` or `if` block
  around the reconcile between the anchors (it is one statement of the block, so it is in the body);
- not handled, disclosed in the instructions and the README ("What the pack does not discriminate"): the engine call or
  `supervisor.attach()` moved into another block (a `try` block, a helper function), the method given through a
  constant instead of the `method: 'vault.references'` literal, renaming `vault`, `references`, `githubStore` or
  `collectorSettings`, and any other name of `index.ts` used in the startup statements (`engine`, `z`, a local
  helper). These change the wiring the brief fixes as required behaviour (the startup order), so they stay out of
  scope rather than being guessed at. None of the disclosures names the reconcile, staged entries or references sets.

Guard proofs (continuation's runs, 12:03-12:08Z; scratch pack copies; the class builds its repository from the real pack, then the probe test writes the
scratch journey test into the checkout):

| guard removed | probes run | result |
|---|---|---|
| G1 the declaration rule (`from = call`) | split over two statements | RED 17 of 18 |
| G2 statement slicing replaced by whole-line slicing | statement after the engine call on its line; last statement on the attach line | RED 17 of 18; RED 10 of 18 |
| G3 AST imports replaced by round 2's regex imports | imported helper with comments in its import | RED 17 of 18 |

Checked by the continuation on a scratch tree of 01a8604 (`git archive` of the clone into `.tmp-gate`, its
`node_modules` a folder of symlinks to the clone's entries): `npx --no-install eslint tests/zz_accepted_x2_1.test.ts`
exit 0, `npx --no-install tsc --noEmit -p .` exit 0; the journey test 18 of 18 green at accepted and on every probe
(the full run, decision 7).

Set aside: anchoring `from` on the call's closing `)` plus an optional `;` (the integration check's cheaper option: it
fixes (a) but not (b), and not same-line statements); disclosing (a) and (b) only (the lead asked for the shapes to
pass); esbuild's parser (it gives no AST to the caller).

## Decision 4: IC-3

`a string holding a comment opener above the engine call` (`const _glob = 'logs/*.json'; void _glob;`) is in
`X21_SLICE_PROBES`. With the parser there is no string-keeping branch left to remove, so the proof is made against the
test it was found in: G4, 3cba2f0's journey test with `codeOnly()`'s string branch removed: RED 17 of 18. With 3cba2f0's
test as it is the probe is green, and with the new test green.

## Decision 5: IC-5

The pack README's Files entry and last section now say that the manifest keeps the cause and
`cases.fix.cause_in_prompt: false` hides it from the candidate; the reworded-cause and kit follow-up text is gone. The
journey section states the cause as `**The cause** (`findings[].cause`): ...`, which the cause test pins.

## Decision 6: F5, no run writes into the clone

How the writes reached the clone: a checkout's `node_modules` is a link (`historyless-checkout.sh --link`), and the
builder's first runs linked the clone's own `node_modules` (sr-pack-4a-1.md item 3). Read in the installed packages
and confirmed on a scratch checkout (`.tmp-gate/x21-probe`, a `git archive` of 16f637f whose `node_modules` links a
folder of symlinks to the clone's entries):

- vite 8.3.0 (`dist/node/chunks/node.js`): `cacheDir` defaults to `<nearest package.json dir>/node_modules/.vite`
  (37039-37046) and only config sets it; the default `bundle` config loader writes
  `<nearest node_modules>/.vite-temp/vitest.config.ts.timestamp-*.mjs` (`loadConfigFromBundledFile`, 37482); the
  `runner` loader (`runnerImport`, 36537) writes no file.
- vitest 5.0.1: the results cache is `ResultsCache.writeToCache` to `<cacheDir>/vitest/<hash>/results.json`; with
  `--no-cache` its path is null and nothing is written. The CLI refuses `--cacheDir` (unknown option) and
  `--cache.dir` (deprecated, throws), so the cache cannot be pointed elsewhere from the command line;
  `--configLoader <loader>` is a CLI option.
- Measured: defaults wrote `node_modules/.vite/vitest/da39a3ee.../results.json` and `node_modules/.vite-temp` into the
  link folder; `--configLoader runner` alone, no `.vite-temp`; with `--no-cache` as well, nothing new.

Root fix: `commands.test` and `commands.run_one` carry `--no-cache --configLoader runner`, and `HostPackX21.vitest()`
now runs the manifest's `commands.test` itself. Without the results cache a grade does not depend on an earlier run
(the cache only orders test files). New guards:

- `test_a_grade_and_run_one_write_nothing_into_the_node_modules_a_checkout_links`: a fresh link folder, a grade of the
  accepted change, `run_one`, and the class's `vitest()`; asserts the link folder (every entry, mtime and size) and the
  clone (`git status --porcelain --ignored` without optional locks, `node_modules/.vite*`, every entry's mtime and size)
  are unchanged. Red at the old commands (the link folder gained `.vite`, `.vite/vitest/da39a3ee.../results.json` and
  `.vite-temp`), green now.
- `tearDownClass` compares the clone with its state at `setUpClass` and checks that the class's link folder holds no
  `.vite*`, so every test of the class together is held to F5. Red at the old commands (`a run wrote ['.vite',
  '.vite-temp'] into the node_modules the checkouts link`; the first fixer's run, not repeated by the continuation,
  whose G5 and G6 prove the same flags through the F5 test), green now (the full run of decision 7 ends with it).
- Guard proofs (continuation's runs; a scratch pack whose commands lack one flag, `X21` pointed at it from the start):
  G5 `--no-cache` removed from both commands: the F5 test RED (the link folder gained `.vite`, `.vite/vitest`,
  `.vite/vitest/da39a3ee.../results.json`); G6 `--configLoader runner` removed: RED (the link folder gained
  `.vite-temp`). The clone stayed unchanged in both: the writes landed in the test's own link folder.

The class still links a folder of symlinks rather than the clone's `node_modules` itself (defence in depth: a future
command that writes would hit that folder, and the tests above would fail, before it could reach the clone). The
fallback (deleting what a run created) was not needed and nothing in the clone was deleted.

Set aside: a pack-side vitest config with its own `cacheDir` (a pack file would have to reach the checkout, which the
isolation rule forbids, and `--config` would replace the subject's own config); `VITE_*` environment variables (vite
reads none for `cacheDir`); deleting `.vite*` after each run (the fallback, and it would delete in a read-only clone).

## Decision 7: the full run and the checks

All by the continuation, on the final pack files (the docstring of `x21_shell_modules` was reworded after the kit suite
ran; the fast part of the class and the commit's gate ran after that), TEMP and TMP on `.tmp-gate`:

- `MOONALIZA_CLONE=<the clone> python -m unittest -v tools.test_calibration_kit.HostPackX21`, 11:19-11:59Z: 16 tests OK
  (2408 s), `tearDownClass` included (the clone and the class's link folder unchanged). In it: make-repo yields the
  manifest ids (accepted `8ddd4f4`, which changes with the journey test the accepted commit carries); the journey test
  red at base and 18 of 18 green at accepted; every WRONG-FIXES row grades FAIL, with the candidate green, the guard
  red, scope and lint ok and the accepted journey test failing at exactly the row's stated count; the accepted fix and
  both alternative correct fixes grade PASS; all 13 slice probes lint clean and 18 of 18 green; the F5 test green; the
  launch refusals hold and the prompt has no `Cause:`.
- Guards R1, G1-G6 (above), 11:59-12:12Z; cause guards C1-C6 and the control (decision 2).
- `python -W error::SyntaxWarning tools/test_calibration_kit.py` (no clone, as the gate runs it): 132 tests OK, 9
  skipped (the clone tests, UNSUPPORTED). `python -m unittest tools/test_check_calibration_evidence.py`: 51 OK.
  `python tools/check_calibration_evidence.py`: 3 folders, 0 failures, 14 limitations. `qualification_table.py --check`
  exit 0; `check_secrets.py` clean.
- The clone: `git --no-optional-locks -C <clone> status --porcelain --ignored` and the listing of `node_modules/.vite*`
  taken before the full run and after the last guard are identical (`!! node_modules/`, `!! research/raw/.diagnostics.jsonl`;
  no `.vite*`). The lint and tsc check of decision 3 ran in between on a `git archive` outside the clone.
- No manifest hash needed a change beyond the README's (the rewrap): `test_the_source_hashes_cover_every_pack_file` and
  make-repo's ids hold.

## What I got wrong and fixed

Continuation:

- The draft left the README's cause paragraph unwrapped, because the cause test matched the README line for line;
  the test now compares whitespace-normalised and the paragraph is wrapped (see the top).
- The draft's old -> new table labelled three commits wrongly ("fix 1" for review 1's report, among them); corrected.
- The first fixer's guard run had `git status` of the clone fail once in `tearDownClass` with exit 0xC0000142
  (STATUS_DLL_INIT_FAILED) while the host was shutting down; it did not recur in any of the continuation's nine class
  runs, so it is read as the shutdown, not as a defect of the check.

First fixer (draft):

- A Bash heredoc of Python collapsed `\\n` to `\n`, so the string anchors did not match; nothing was written. Edits with
  backslashes went through files or the Edit tool from then on.
- The "no semicolon" probe first assumed the engine call and the reconcile are adjacent; accepted `index.ts` has two
  comment lines between them, so it became per-line edits.
- `Path.write_text` on Windows wrote the test file with CRLF line ends (a 6000-line diff); converted back to LF and
  every later write went through `write_bytes`.
- The README test still pinned round 2's `const extra = imported(source);`; replaced by the new pin.
- A first scratch tree for eslint/tsc linked the folder above the link folder's `node_modules`, so `npx` fetched an
  eslint from the registry into the npm cache (outside the clone and the worktree); relinked, and `--no-install` used
  from then on.
