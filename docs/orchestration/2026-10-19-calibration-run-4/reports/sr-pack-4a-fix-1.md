# sr-pack-4a, fix round 1: the findings of review 1 on the host pack moonaliza-x2-1

Verdict: DONE. One commit on `build/sr-pack-4a` on top of the review (9d02f61), not pushed; the structured return names
the head. F1, F3, F7 and F8 are fixed red-first; F2 stays with the lead (it needs a kit change or a decision, outside
this unit's permitted paths); F4, F5 and F6 are ratifications or owner actions and change nothing here.

## What changed

| finding | change | files |
|---|---|---|
| F1 (S2) | `wiring()` binds every name `src/main/index.ts` imports from `./github-account-store` or `./vault` (named, renamed with `as`, or a namespace; `type` imports skipped) to the candidate's own export, passed to the transpiled startup lines as extra parameters. A second alternative correct fix, `X21_ALTERNATIVE_HELPER` (a helper `startupReconcileOptions(store)` exported by the store's module and imported into `index.ts`, an options object `spareStaged`), must grade PASS. The remaining limit (any other name of `index.ts` in the startup lines) is named in the case `instructions`, which the candidate sees, and in the README's non-discrimination list | `zz_accepted_x2_1.test.ts`, `manifest.json` (`instructions`), `README.md`, `tools/test_calibration_kit.py` |
| F3 (S3) | The journey rows and the orphan row move the wall clock a month on (`vi.useFakeTimers({ toFake: ['Date'] })`, `vi.setSystemTime`; timers stay real, `afterEach` restores) between the crash and the unread start. New wrong fix W-k (keep an unreferenced staged entry only while it is less than a day old) | `zz_accepted_x2_1.test.ts`, `WRONG-FIXES.md`, `X21_WRONG` |
| F7 (S4) | The journey rows run with EIO as a third errno code (12 journey rows, 17 rows in all). New wrong fix W-l (keep only on EACCES or EBUSY) | `zz_accepted_x2_1.test.ts`, `WRONG-FIXES.md`, `X21_WRONG` |
| F8 (S4) | `make-repo.sh` sets an EXIT trap right before `git init` (TARGET did not exist, checked earlier) that removes TARGET on any failure, the id mismatch included, and clears it on success. New test `test_make_repo_removes_its_target_when_the_ids_differ` | `make-repo.sh`, `README.md`, `tools/test_calibration_kit.py` |

Consequences: the accepted commit holds the new journey test, so `accepted0` is now
`f39d775b20f0d08616c49c11664e22ac4a643981` (was 0793f9d3); `base0` is unchanged (09fe935e). The manifest's
`accepted_fix` (both places) and `source_hashes` follow. `WRONG-FIXES.md` counts out of 17; every row's count is the
measured one (below). The kit tests now expect 12 journey rows and 17 in all, grade three correct fixes, and check
statically that the journey test binds the imports, runs EIO and moves the clock in both rows, and that the README names
the remaining wiring limit. The CHANGELOG line says fourteen wrong fixes.

## Red first

Probes on a scratch checkout of MoonAliza 16f637f's tree (node_modules through a directory of symlinks to the clone's,
so the clone stays untouched), the candidate edits applied with `x21_edit` from the kit test, the journey test run with
vitest:

| candidate | old journey test (c43b04c) | new journey test |
|---|---|---|
| the accepted change (01a8604's three source files) | 0 of 13 failed | 0 of 17 failed |
| `X21_ALTERNATIVE` | (passed before, review) | 0 of 17 failed |
| `X21_ALTERNATIVE_HELPER` (F1) | **12 of 13 failed, `ReferenceError: startupReconcileOptions is not defined`** (the review's probe, reproduced) | 0 of 17 failed |
| W-k, day-old limit (F3) | **0 of 13 failed** (the review's probe, reproduced) | 12 of 17 failed (every journey row, at the pair-state check after the unread start) |
| W-l, EACCES/EBUSY allowlist (F7) | **0 of 13 failed** | 4 of 17 failed (the four EIO rows) |
| base (16f637f) | 8 of 13 failed (review) | 12 of 17 failed: every journey row, at the pair-state check; the 5 guard rows pass |

An extra probe: the helper reached through a namespace import (`import * as accountStore from './github-account-store'`)
and a multi-line named import with a `type` specifier passes 17 of 17.

F8: the old `make-repo.sh` (c43b04c) with `accepted_fix` set to forty zeros: exit 1, TARGET left in place. The new one:
exit 1, `make-repo: failed; removed <target>`, TARGET gone. Without a manifest beside it: exit 0, the two ids.

## Guard-removal proofs

| guard removed (scratch copy) | result |
|---|---|
| the import binding (`const extra = new Map()` instead of `imported(source)`) | `X21_ALTERNATIVE_HELPER`: 16 of 17 failed, ReferenceError |
| the clock move (`later()` a no-op) | W-k: 0 of 17 failed |
| the EIO code | W-l: 0 of 13 failed |
| the EXIT trap in `make-repo.sh` (the c43b04c script) | target left behind: `test_make_repo_removes_its_target_when_the_ids_differ` asserts it gone |

## Checks

| check | result |
|---|---|
| `python tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (every wrong fix through `grade.sh fix`, one at a time; the three correct fixes; make-repo ids and cleanup; the launch refusals) | 12 tests OK in 1884 s, exit 0 (verified). Every wrong fix grades FAIL with candidateGreen, guardRed, scopeOk true and lint ok, and with exactly the `acceptedPin` count `WRONG-FIXES.md` states (the test asserts each): W-a 12, W-b 1, W-b2 1, W-c 4, W-d 13, W-e 13, W-f 12, W-g 9, W-h1 1, W-h2 1, W-i 12, W-j 1, W-k 12, W-l 4, of 17. The accepted change, `X21_ALTERNATIVE` and `X21_ALTERNATIVE_HELPER` grade PASS. make-repo builds base0 09fe935e… and accepted0 f39d775b… twice, equal to the manifest |
| `python tools/test_calibration_kit.py HostPackX21 Docs Hygiene` without the clone | 25 tests OK, 6 skipped with the UNSUPPORTED reason (verified) |
| `npx eslint` on the journey test and the three source files (helper alternative applied) | exit 0 (verified) |
| `npx tsc --noEmit -p .` on the subject with the new journey test (helper alternative applied) | exit 0, no errors (verified, after the fix below) |
| `python tools/check_secrets.py` | clean, 0 hits (verified) |
| The MoonAliza clone | `git status` clean; `node_modules/.vite` and `.vite-temp` timestamps unchanged from 2026-10-24 (verified) |
| The regression gate through the pre-commit hook | verified by the commit landing (TEMP and TMP on drive C, the host fault noted in the launch prompt) |
| Changed files against the permitted effects | the pack directory, `tools/test_calibration_kit.py`, `CHANGELOG.md` (the existing line), this report: all within `sr-pack-4a.json` (verified) |

## F2, F4, F5, F6: for the lead

- **F2 (S2), open, lead decision.** `tools/calibration/run.template.js` puts `Cause: ${f.cause}` into the fix prompt, so a
  candidate sees the cause, against the brief and R4-1's T3 premise. The kit file is outside this unit's permitted
  effects, and rewording `cause` so it no longer names the mechanism departs from H3's wording, so this round changes
  neither. Options: (1) a kit unit that leaves `cause` out of the fix prompt (or adds a manifest flag for it); (2) a
  recorded decision to reword this manifest's `cause`; (3) accept the tier with the cause shown and record it. The pack
  README discloses the current state. Stage 4a should not launch as briefed until one of these is decided.
- **F4 (S4).** `commands.test` keeps `--testTimeout=60000` (measured reason in report 1, finding 5); the lead ratifies or
  drops it.
- **F5 (S4).** The clone's `node_modules/.vite` and `.vite-temp` from the builder's first runs stay; deleting them is a write
  to the read-only clone, so the owner may do it. This round wrote nothing to the clone (its node_modules is reached only
  through a symlink shell, and `.vite` / `.vite-temp` are left out of it).
- **F6 (S4).** No change: K3's MoonAliza-name rule stops at `subject-pack/host/`, as disclosed in report 1.

## What I got wrong and fixed

- The first version of the import parser destructured regex matches directly; `npx tsc --noEmit` on the subject (which
  has `noUncheckedIndexedAccess`) reported six errors in the journey test. Rewritten with explicit fallbacks; tsc exit 0.
- `WRONG-FIXES.md`'s "journey rows (all 8)" occurs five times, not four; my edit script's count assertion caught it
  before any write.
