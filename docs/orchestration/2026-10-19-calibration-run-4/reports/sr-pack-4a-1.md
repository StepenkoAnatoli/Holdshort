# sr-pack-4a, report 1: the host pack moonaliza-x2-1 (calibration run 4, stage 4a, fix@T3, X2-1)

Verdict: DONE. One commit on `build/sr-pack-4a` (from main `0a6d341`), not pushed. The commit is the branch head the
structured return names.

## What was built

- `tools/calibration/subject-pack/host/moonaliza-x2-1/` (new, all files LF, `.gitattributes` `* -text`):
  - `manifest.json`: `kind: host`, `pack: moonaliza-x2-1`, `pack_version: "1"`, one case `fix` at T3, the pass rule
    verbatim, the paths as briefed, the commands as briefed except one flag (finding 5), `source_hashes` of the five other pack files, the isolation statement,
    and `_cases` saying why there is no pin and no review case. The cause names the reconcile deleting every
    unreferenced staged entry during the start that cannot read the account file. Commit ids: `base0` 09fe935e94d4,
    `accepted0` 0793f9d377f0 (full ids in the manifest).
  - `make-repo.sh <clone> <target>`: a bare repository with two root commits (fixed identity, dates, messages):
    `base0` = MoonAliza 16f637f's tree, `accepted0` = 01a8604's tree plus `tests/zz_accepted_x2_1.test.ts`; refs
    `base`, `accepted`, `base0`, `accepted0`. It checks the built ids against a manifest beside it (exit 1 on a
    mismatch, 2 on a bad argument or an existing target). Nothing is written to the clone.
  - `zz_accepted_x2_1.test.ts`: the accepted journey test, 13 rows: 8 journey rows (first sign-in before commit 1,
    sign-in before commit 3, refresh before commits 3 and 4, each with EACCES and EBUSY at the next start) and 5 guard
    rows (tombstone, orphan, ENOENT, app-changed, vault-default). Each start is a new `Vault` and store on the crash's
    data directory, the store's `open()`, then the startup lines of the candidate's own `src/main/index.ts` (between the
    `vault.references` line and the `supervisor.attach(` line), transpiled with esbuild and run with the start's vault,
    store and references. An unreadable file fails every read of that one path (`lstat`, `stat`, `open`, `readFile`
    and their sync forms) for the whole start. Each row has its own 120 s timeout (finding 5). It names none of the accepted fix's names (`unreadAtOpen`,
    `keepStaged`; checked against the full list of identifiers 01a8604 adds under `src/main`).
  - `WRONG-FIXES.md`: 12 rows (the lead's a-h, with b and h split into W-b/W-b2 and W-h1/W-h2, plus W-i and W-j),
    each with the wrong idea, the pin row that catches it and the grade `grade.sh fix` returned.
  - `README.md`: the journey; how a host builds the repository, the dependencies (a writable node_modules) and the
    checkouts with `--link node_modules=<installed outside the pack>`; the names the test assumes and why; what the
    pack does not discriminate; why there is no pin and no review case.
- `tools/test_calibration_kit.py`: class `HostPackX21` (11 tests) and the helpers before it (`X21_WRONG`,
  `X21_ALTERNATIVE`, `X21_TEST_EDITS`, `X21_CANDIDATE_TEST`, `x21_candidate`, `x21_shell_modules`, ...).
- `tools/calibration/subject-pack/README.md`: one paragraph (a host pack example lives beside the shared one).
- `CHANGELOG.md`: one Unreleased line, `- **Host subject pack moonaliza-x2-1**`.

## Red/green proofs

| test | red | green |
|---|---|---|
| accepted journey test | at base0 (MoonAliza 16f637f): the 8 journey rows fail (the pair-states check after the unread start), the 5 guard rows pass | at accepted0: 13 of 13 |
| `HostPackX21` clone tests | before the pack existed (UNSUPPORTED without the clone, never a pass) | 11 of 11 with `MOONALIZA_CLONE`, grades one at a time (75 min) |
| `HostPackX21` no-clone tests | the manifest shape test was red on the first cause wording (it lacked "unreferenced staged"); fixed | 6 of 6 without the clone, 5 skipped as UNSUPPORTED |

The grades (`grade.sh fix` on the pack built from the clone, one at a time):

| candidate | acceptedPin red of 13 | candidateGreen, guardRed, scopeOk, lint | PASS |
|---|---|---|---|
| W-a retry the read once | 8 (journey rows) | true, true, true, ok | false |
| W-b skip the whole reconcile on an unread start | 1 (tombstone) | true, true, true, ok | false |
| W-b2 the flag spares tombstones too | 1 (tombstone) | true, true, true, ok | false |
| W-c keep every unreferenced staged entry always | 4 (orphan, ENOENT, app-changed, vault-default) | true, true, true, ok | false |
| W-d `references()` returns staged refs while unread | 9 (journey rows, orphan) | true, true, true, ok | false |
| W-e commit unreferenced staged entries while unread | 9 (journey rows, orphan) | true, true, true, ok | false |
| W-f keep the entries, unlink their files | 8 (journey rows) | true, true, true, ok | false |
| W-g keep only while no committed entry exists | 6 (the six replace journey rows) | true, true, true, ok | false |
| W-h1 flag from unread or `openedAppChanged()` | 1 (app-changed) | true, true, true, ok | false |
| W-h2 flag from "no account read" (ENOENT too) | 1 (ENOENT) | true, true, true, ok | false |
| W-i `index.ts` left unchanged | 8 (journey rows) | true, true, true, ok | false |
| W-j kept entries held forever | 1 (orphan) | true, true, true, ok | false |
| the accepted change (01a8604's files) | 0 | true, true, true, ok | true |
| the alternative (`fileUnreadable()`, positional vault parameter) | 0 | true, true, true, ok | true |

The test asserts each wrong fix's `acceptedPin.failed` against the count its `WRONG-FIXES.md` row states, so the
counts above are the grades, not predictions. Before grading, each candidate's own tests were run green in a scratch
checkout (95 passed; W-c 93, the two dropped rows), and the accepted journey test was run against each scratch
candidate with the same failing rows as above; the alternative passed it 13 of 13.

## Guard-removal proofs

- make-repo's id check: a manifest whose `accepted_fix` is changed makes `make-repo.sh` exit 1 and name the field
  (verified in a scratch copy).
- `test_wrong_fixes_lists_every_wrong_fix_the_tests_grade`: an extra key in `X21_WRONG` turns it red (verified).
- `test_the_source_hashes_cover_every_pack_file`: an edited `WRONG-FIXES.md` and an unlisted extra file each turn it
  red (verified on a scratch copy of the pack).
- The journey test's whole-start read failure: W-a (retry the read once) passes its own tests and fails 8 journey rows.
- The wiring read from the candidate's `index.ts`: W-i (store and vault fixed, `index.ts` unchanged) fails 8 journey
  rows.
- The hygiene exemption is scoped to `subject-pack/host/`: the first wording of the new `subject-pack/README.md`
  paragraph named the pack directory and turned `Hygiene.test_the_kit_has_no_host_path_session_id_key_or_provider_call`
  red; reworded.
- The grade-count assertion: each wrong fix's `acceptedPin.failed` must equal the count its `WRONG-FIXES.md` row
  states (13 total), so a stale row is red.

## Checks run

- `python tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` set, on the final files: 11 tests OK
  (4469 s). An earlier whole-file run with the clone: 91 tests, 90 OK and the one checkout timeout of finding 6.
- `python tools/test_calibration_kit.py` without `MOONALIZA_CLONE` (the whole file, as the gate runs it): 91 tests OK,
  6 skipped (the 5 UNSUPPORTED and one existing symlink skip of `Scripts`), before the last timeout edits; the gate
  reruns it on the commit.
- `python tools/test_calibration_kit.py HostPackX21 Docs Hygiene Gate` without `MOONALIZA_CLONE`: 25 tests, OK, 5
  skipped (UNSUPPORTED).
- eslint on the accepted journey test in a base checkout: clean.
- The regression gate through the pre-commit hook on the commit: see the commit (it lands only if green).

## Deviations and findings for the lead

1. **The kit shows the cause to the candidate.** `run.template.js`'s fix prompt includes `Cause: ${f.cause}`. The
   brief's "the candidate never sees the cause" therefore needs a kit change (leave `cause` out of the fix prompt, or
   add a manifest flag for it). Not made: kit files are outside this unit. The manifest's cause says where the loss
   happens, never how to fix it, and the pack README says so. Not a stop trigger: `grade.sh` grades the pack as is.
2. **Edits to existing kit tests** (in the permitted `tools/test_calibration_kit.py`): the hygiene scan became a
   module function `hygiene_scan(root)` that drops the "a MoonAliza name" rule for files under
   `subject-pack/host/` only; `Docs.test_readme_lists_every_kit_file` exempts the host pack's files (its own README
   lists them); `test_changelog_and_readme_name_the_kit` now expects the three kit lines, the third naming the host
   pack's directory.
3. **The clone was written to.** My first vitest runs linked the clone's `node_modules` directly, and vitest created
   its caches `node_modules/.vite` and `node_modules/.vite-temp` there (git-ignored). Deleting them was denied by the
   auto-mode classifier; I did not retry. The owner may delete those two directories. Since then every checkout links
   a node_modules of its own whose entries link to the clone's (`x21_shell_modules`, skipping `.vite` and
   `.vite-temp`), and nothing else was written to the clone.
4. **W-c changes a shipped test.** Keeping every unreferenced staged entry contradicts one shipped crash-window row
   ("after staging, before the file write", whose orphan pair the next start deletes); the W-c candidate drops that
   row (`X21_TEST_EDITS`), as a candidate holding the idea would, so its own tests are green and the grade turns on the
   accepted journey test.
5. **Deviation from the brief: `commands.test` adds `--testTimeout=60000`.** It reads
   `npx vitest run {files} --testTimeout=60000 --reporter=json --outputFile={report}`; the brief has it without the
   flag. MoonAliza's vitest config sets `testTimeout: 15000`, and on this host its long tests (the "retired list stays
   within 8 refs" and "sign-in's rollback keeps retiredRefs within 8" groups) run close to that. Measured: with six
   vitest runs side by side, two or three of them timed out per run; with three grades side by side the alternative
   fix graded `candidateGreen: false` (94 of 95) once and `acceptedPinGreen: false` (12 of 13) once, and PASS when
   graded alone; and with the grades one at a time, before the flag, W-a's own tests went 94 of 95 in the first grade
   of the run (a cold vitest cache), where every earlier run of them was 95 of 95. A grade that fails a correct fix by
   chance would misqualify a profile, so the grade command raises the timeout; `commands.run_one`, which the
   candidate is told to run, stays the subject's own. The accepted journey test also gives each row 120 s itself (a
   `describe` option, checked with a 17 s probe row). The clone tests grade one cell at a time, and the pack README
   tells a host to do the same. To undo: drop the flag from `commands.test` and from the manifest-shape test.
6. **The host-pack checkouts take over a minute** (72 s measured idle): `checkout()` in the kit test gained a
   `timeout` parameter (default 120 s, as before), and `HostPackX21` passes 900 s; the first clone run errored on a
   checkout that passed 120 s.

## What I got wrong and fixed

- The journey test's call counters used `hooks.beforeCommit?.(++commits)`, which skips the increment while the hook
  is unset; the crash points were then off. Fixed to count first, then call.
- vitest wrote caches into the read-only clone (finding 3).
- `historyless-checkout.sh` refused a checkout inside `--pack`; scratch checkouts now sit beside the repository.
- WRONG-FIXES.md was first written with predicted counts; W-c was predicted 3 and grades 4 (the ENOENT and
  app-changed rows also catch it), W-d and W-e also fail the orphan row. The rows now state the measured counts, and a
  test checks them against the grades.
- The first W-c test edit was written with a literal newline inside a Python string; fixed before any run.
- I first graded the wrong fixes three at a time to save time; that is what exposed finding 5. The grades now run one
  at a time.
