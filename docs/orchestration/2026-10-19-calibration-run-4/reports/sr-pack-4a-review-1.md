# sr-pack-4a, review 1: refute-first review of the host pack moonaliza-x2-1

Verdict: **FIX**. Reviewed `build/sr-pack-4a` at c43b04c (base main 0a6d341) against the brief
`run4-pack-4a-builder.md` (H1-H5), `conventions.md`, `run4-plan.md` and the request `sr-pack-4a.json` (permitted
effects, non-goals, acceptance checks). Fresh context; I did not write the change. Nothing in the source was edited by
this review; this report is the only file it adds.

Two S2 findings and one S3 stay open: a correct fix whose wiring uses any name other than the four the test binds is
graded FAIL (F1, shown by a probe), the kit's fix prompt shows the candidate the cause that the brief says it never
sees (F2, which the builder reported itself; this unit's paths cannot settle it, the lead decides), and a wrong fix
that keeps only recent staged entries passes all 13 rows (F3, shown by a probe; under H1 that means a row is missing).

## Findings

| id | severity | finding |
|---|---|---|
| F1 | S2 | A correct fix is graded FAIL when its startup lines in `src/main/index.ts` use any identifier besides `vault`, `references`, `collectorSettings` and `githubStore` |
| F2 | S2 | The candidate sees the cause: `run.template.js` puts `Cause: ${f.cause}` in the fix prompt, which contradicts the brief ("the cause is NOT in the candidate's task text") and R4-1's T3 premise. Lead decision |
| F3 | S3 | A wrong fix that keeps unreferenced staged entries on an unread start only while they are recent passes all 13 rows. Under H1 that means a row is missing |
| F4 | S4 | `commands.test` departs from the brief (`--testTimeout=60000`). It is disclosed and measured; the lead has to ratify it |
| F5 | S4 | The builder's first runs wrote vitest caches into the read-only clone (`node_modules/.vite`, `.vite-temp`). Disclosed |
| F6 | S4 | Existing kit tests changed beyond "a new `HostPackX21` class": K3's MoonAliza rule no longer applies under `subject-pack/host/` |
| F7 | S4 | Errno codes other than EACCES and EBUSY are not exercised, so a fix that allowlists exactly those two passes. The README discloses this |
| F8 | S4 | `make-repo.sh` leaves the built TARGET in place when its id check fails (exit 1) |

### F1 (S2): a correct fix that calls an imported helper from the wiring grades FAIL

`zz_accepted_x2_1.test.ts` `wiring()` takes the lines between `vault.references` and `supervisor.attach(` from the
candidate's `index.ts`, transpiles them, and runs them with `new Function`. Only the four parameters are in scope;
index.ts's imports are not. So any correct fix whose wiring names anything else throws a `ReferenceError` in every row
that runs a start. That is 12 of the 13 rows; only the vault-default row survives.

Probe (scratch checkout of MoonAliza 16f637f's tree, node_modules linked through a directory of symlinks): I applied
01a8604's three source files, which is the accepted fix and passes 13 of 13. Then I changed only the wiring, so that it
gets the options from a helper exported by `github-account-store.ts` (an allowed source file) and imported into
`index.ts`: `export function reconcileOptions(store) { return { keepStaged: store.unreadAtOpen() }; }` and
`await vault.reconcile(new Set([...]), reconcileOptions(githubStore));`. The behaviour is identical and the startup
order is unchanged. Result: **1 passed, 12 failed, `ReferenceError: reconcileOptions is not defined`**. So this
correct fix would grade `acceptedPinGreen: false`, PASS false.

This is plausible, not a corner case. The fix prompt demands a red-first pin. `index.ts` has no harness (its only test
pins source lines). So extracting the wiring decision into a testable function in one of the allowed modules is a
natural design. Nothing tells the candidate the constraint: neither the case `instructions` nor any text the
candidate sees says the startup lines may use only those four names. The README's "What the pack does not
discriminate" lists only moving the reconcile or renaming the four names. A false FAIL misqualifies a profile, and the
pack's discriminating power in both directions is the point of R4-3.

Remedy, either or both:
- (a) Have `wiring()` resolve index.ts's imports from the three source files. Parse its `import { ... } from './github-account-store' | './vault'` lines, import those modules in the test, and pass their named exports as extra parameters. A fix that imports from any other module stays out of scope.
- (b) Name the constraint in `cases.fix.instructions` (the candidate sees it) and in the README's non-discrimination list.

Then add the probe above as a second alternative correct fix that must PASS in `HostPackX21`.

### F2 (S2, lead decision): the fix prompt carries the cause

The brief says the cause is not in the candidate's task text. H3 says `cause` is "written for the grader only ... the
candidate never sees it". R4-1 counts "the cause unnamed in the journey" among the T3 predicates. But the kit's fix
prompt (`tools/calibration/run.template.js:159`) is `... ${f.summary}. Cause: ${f.cause}. Required behaviour: ...`,
and this manifest's `cause` names the mechanism outright: the store names no references during the unread start, and
the reconcile deletes every unreferenced staged entry. Launched as is, stage 4a measures a fix whose cause is handed
to the candidate. That is not the T3 cell the plan declares.

The builder reported this (report 1, finding 1) and correctly made no kit edit. Within the permitted paths, the only
alternative is to reword `cause` so that it does not name the mechanism, which departs from H3's wording. So this needs
the lead. One option is a kit unit that leaves `cause` out of the fix prompt, or adds a manifest flag for it. Another
is a recorded decision to reword `cause`, or to accept the tier with the cause shown. It is not a defect of the build;
it blocks the launch as briefed.

### F3 (S3): an age-limited keep passes every row

Probe: on the accepted fix, I changed the vault's keep condition so that an unreferenced staged entry survives an
unread start only while `Date.now() - entry.createdAt < 24 h`. The idea is that an older staged entry counts as
abandoned. The vault stamps `createdAt` with `Date.now()` (vault.ts:90). Result: **13 of 13 pass.** The fix is wrong
by the required behaviour: an unread start a day after the crash deletes the pair the file names, and the account is
lost exactly as in X2-1. It passes only because every start in the test runs within seconds of the crash.

H1 says "a wrong fix no row catches means a row is missing". Remedy: in at least one journey row (and in the orphan
row), move the system clock days forward between the crash snapshot and the unread start, for example with
`vi.useFakeTimers({ toFake: ['Date'] })` and `vi.setSystemTime(...)`. The store's clock is already injected. Then add
the wrong fix as a W-k row in `WRONG-FIXES.md` and `X21_WRONG`.

### F4-F8 (S4)

- F4. `commands.test` adds `--testTimeout=60000` to the briefed command. The reason (the subject's 15 s tests timing out under load) is measured and disclosed in the commit and in the report. The lead should ratify it in the decision record, or drop the flag.
- F5. The clone holds `node_modules/.vite` (2026-10-24 21:33 local) and `node_modules/.vite-temp` (21:43) from the builder's first runs. They are git-ignored, `git status` in the clone is clean, and the builder disclosed them; the owner may delete them. My own runs used a symlink-shell node_modules and did not touch them (timestamps unchanged after the runs).
- F6. `hygiene_scan()` drops the "a MoonAliza name" rule for files under `subject-pack/host/`. `Docs.test_readme_lists_every_kit_file` exempts the host pack. The CHANGELOG test expects three kit lines, and `checkout()` takes a `timeout`. All of this is in the permitted file and disclosed (report finding 2). Each change is needed for a host pack to live in the kit tree. The lead should note that K3's host-name rule now stops at `subject-pack/host/`.
- F7. Only EACCES and EBUSY are exercised (README "What the pack does not discriminate"). One EIO or EPERM row would close the allowlist case cheaply.
- F8. On an id mismatch, `make-repo.sh` exits 1 and leaves the repository it built, so a rerun is refused (exit 2) until the host deletes it. Harmless, but the README could say so.

## What I re-ran and checked

| check | result |
|---|---|
| Journey test at base (MoonAliza 16f637f tree, scratch checkout) | 8 journey rows failed, 5 guard rows passed. Every failure is at the pair-state assertion after the unread start (`[undefined, undefined]` vs `['staged', 'staged']`; `['committed', undefined]` for refresh before commit 4): red for the finding's reason, not a harness error (verified) |
| Journey test with 01a8604's three source files | 13 of 13 passed (verified) |
| eslint on the journey test (accepted tree) | exit 0 (verified) |
| `npx tsc --noEmit` on the accepted tree with the journey test | exit 0, no errors (verified) |
| `make-repo.sh` from the clone into a fresh target on another drive | `base0 09fe935e…`, `accepted0 0793f9d3…`, equal to the manifest (verified; deterministic across hosts' paths) |
| make-repo guard removal: manifest `accepted_fix` altered | exit 1, names the field (verified); an existing target gives exit 2 (verified) |
| Source-hash guard: a scratch copy of the pack with `WRONG-FIXES.md` edited | `test_the_source_hashes_cover_every_pack_file` FAIL (verified) |
| WRONG-FIXES id guard: an extra key in `X21_WRONG` | `test_wrong_fixes_lists_every_wrong_fix_the_tests_grade` FAIL (verified) |
| `python tools/test_calibration_kit.py HostPackX21 Docs Hygiene` without the clone | 24 tests OK, 5 skipped with the UNSUPPORTED reason (verified) |
| `python tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (every wrong fix through `grade.sh fix`, the accepted and the alternative fix, the launch refusals) | 11 tests OK in 1918 s, exit 0. Every wrong fix FAIL with the `acceptedPin` count `WRONG-FIXES.md` states. The accepted fix and the alternative fix PASS. The ids are deterministic (verified) |
| Probe F1 (correct fix, wiring through an imported helper) | 1 passed, 12 failed, ReferenceError (verified) |
| Probe F3 (wrong fix, 24 h age-limited keep) | 13 of 13 passed (verified) |
| `python tools/check_secrets.py` | exit 0 (verified) |
| Hygiene scan of the diff (absolute paths, session or run ids, key shapes, model names) | none outside the commit trailer (verified) |
| Changed files against the permitted effects | all ten within `sr-pack-4a.json`'s permitted effects (verified) |
| Commit c43b04c: identity, trailer, five-part report, hook | identity `StepenkoAnatoli <318295322+…@users.noreply.github.com>`, `Co-Authored-By` trailer, the five parts present (plus a Deviation paragraph), `.githooks/pre-commit` (the gate) wired through `core.hooksPath` and unchanged (verified) |

Brief decisions checked and found as briefed:
- H1: 12 rows covering a-h, each with a measured grade and a test that ties each count to the grade.
- H2: journey rows for sign-in and refresh through the candidate's own wiring, plus the tombstone, orphan, ENOENT, app-changed and vault-default rows. No name of the accepted fix appears, the README justifies this, and an alternative fix passes.
- H3: the manifest's shape and pass rule are verbatim, except F4.
- H4: the tests are there, and the clone tests report UNSUPPORTED without the clone.
- H5: the README and the matrix are there.

The vault-level `keepStaged` row of H2 is replaced by journey assertions on entries and files, as H2's own
"different correct fix" clause allows.

## For the fix round

1. F1: bind index.ts's imports from the three source files in `wiring()` (or name the limit in `instructions` and the README), and add the helper-wiring fix as a second alternative that must PASS.
2. F3: advance the clock between the crash and the unread start in the journey and orphan rows, and add the age-limited keep as W-k (measured grade).
3. F2: the lead's decision, recorded; then the manifest, README and report follow it.
4. F4-F8 are optional.
