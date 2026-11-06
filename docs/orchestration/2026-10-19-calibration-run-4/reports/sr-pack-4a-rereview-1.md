# sr-pack-4a, re-review 1: refute-first re-review of the host pack moonaliza-x2-1 after fix round 1

Verdict: **FIX**. Reviewed `build/sr-pack-4a` at ad5138f (fix round 1, on top of review 1 at 9d02f61 and the build at
c43b04c; base main 0a6d341) against the brief `run4-pack-4a-builder.md` (H1-H5), `conventions.md`, `run4-plan.md`, the
request `sr-pack-4a.json`, review 1 (`sr-pack-4a-review-1.md`) and the fix report (`sr-pack-4a-fix-1.md`). Fresh
context; I wrote none of the change. This report is the only file this round adds.

Review 1's F1, F3, F7 and F8 are fixed: I re-ran each proof and each guard removal and got the fix report's numbers.
Two things block ACCEPT:

- **F2 (S2) is still open.** It needs the lead, not another fix round of this unit.
- **R1 (S3) is new.** A wrong fix that keeps unreferenced staged entries whenever the store reads a file that names no
  account (a signed-out file) passes all 17 rows. Under H1 that means a row is missing. This unit can fix it within its
  paths.

## Findings

| id | severity | status | finding |
|---|---|---|---|
| F1 | S2 | fixed | A correct fix whose wiring calls a helper imported from `./github-account-store` or `./vault` now passes (verified, below) |
| F2 | S2 | **open, lead decision** | The kit's fix prompt still shows the candidate the cause: `run.template.js` line 159 on this branch, and line 174 on `build/sr-kit-cases` (draft PR #120), both read `Cause: ${f.cause}`. No decision is recorded in the lead's RUN.md |
| F3 | S3 | fixed | The day-old keep (W-k) is caught by every journey row (verified). What is left is R2 |
| F4 | S4 | open, ratification | `--testTimeout=60000` in `commands.test`. Unchanged |
| F5 | S4 | open, owner | The clone's `node_modules/.vite` and `.vite-temp` (2026-10-24 21:33 and 21:43 +0300) are unchanged. This round wrote nothing to the clone (below) |
| F6 | S4 | open, ratification | K3's MoonAliza-name rule stops at `subject-pack/host/`. Unchanged |
| F7 | S4 | fixed | EIO rows added. The EACCES/EBUSY allowlist (W-l) is caught (verified) |
| F8 | S4 | fixed | `make-repo.sh` removes its TARGET on failure (verified, with a guard removal) |
| R1 | S3 | **new** | Keeping unreferenced staged entries when the file is unread **or reads as signed out** passes all 17 rows |
| R2 | S4 | new, disclosed | The clock moves exactly 30 days, so an age limit of 31 days or more passes |
| R3 | S4 | new | The new sentence in `cases.fix.instructions` tells the candidate that the grade runs the `index.ts` startup lines on their own. That points at where the fix is wired. Weigh it in the F2 decision |
| R4 | S4 | new | `wiring()` anchors on the first line of `index.ts` that matches `vault\.references`. A candidate comment above line 193 that mentions it would anchor wrongly |

### R1 (S3): a keep flag set for a signed-out file passes every row

Probe W-m. On the base (MoonAliza 16f637f's tree), the store gets the getter `openFailed() { return this.unread ||
this.disk?.account === null; }`, the vault gets the keep option (`X21_KEEP_UNREFERENCED`), and the wiring passes
`{ keepStaged: githubStore.openFailed() }`. Result: **0 of 17 rows fail.**

The idea behind it: "when the store names no account, its references may be incomplete, so keep staged entries, but a
missing file (ENOENT) is a fresh install and an account for another app is a deliberate drop". The two exclusions are
what the ENOENT row and the app-changed row catch (W-h2, W-h1). Nothing catches the remaining case: a readable file
whose `account` is `null`.

This fix is wrong by the manifest's own required behaviour ("an unreferenced staged entry is deleted by the next start
that reads the file"). The failing journey is realistic and lies in the same crash window as the orphan row:

1. Sign out (the file now names no account).
2. Sign in again; the process crashes after the pair is staged, before step 4 writes the file.
3. Every later readable start keeps the orphan pair. Its encrypted token files stay on disk for as long as the user stays
   signed out.

None of the 17 rows has a readable start with a signed-out file and an unreferenced staged entry. The tombstone row's
start is unreadable, and the orphan row's readable start has account A.

Remedy, in this unit's paths:
1. Add a row: sign in, sign out (`clear` returns `durable`, and the file reads `account: null`), then a sign-in that
   crashes after staging (the `afterStaged` hook, before the file write). A readable start must then delete the orphan
   pair: no entries, no `.bin` files, the store signed out.
2. Add W-m to `WRONG-FIXES.md` and `X21_WRONG` with its measured grade.

The journey-test result above is verified. That `grade.sh fix` would grade W-m PASS is expected, not verified: its
other prongs are those of the other wrong fixes (the candidate test keeps on an unread start, the restored base fails
it, the change is in scope, eslint is clean).

### R2 (S4): age limits of a month or more

`later(30)` moves `Date` exactly 30 days. An age-limited keep with a 31-day limit (W-n31) and one with a 90-day limit
(W-n90) each pass 17 of 17 (verified). The README discloses this ("Time limits beyond a month"), so the finding is not
hidden. But 30 days is a natural limit for a candidate to pick, and the test passes it by only the seconds the row
takes. Moving the clock years instead of a month (for example `later(3650)`) would close the whole class at no cost:
the store's clock is injected and fixed, so only the vault's `Date.now()` sees the move.

### R3, R4 (S4)

- R3. The new instructions sentence ("The grade runs the startup lines of src/main/index.ts, from the line that reads
  the engine's references up to supervisor.attach(), on their own ...") is the price of F1's option (b). It tells the
  candidate that the decisive behaviour runs through those startup lines. That says nothing the cause does not already
  say, but if F2 is settled by keeping the cause from the candidate, the lead should decide whether this sentence stays.
- R4. `lines.findIndex(line => /vault\.references/.test(line))` takes the first match in the file. Today the only
  match is line 193. A candidate comment above it that names `vault.references` would shift the slice, and the row
  would fail with a SyntaxError or ReferenceError. This is unlikely. Anchoring on the `engine.control({ method:
  'vault.references' })` line would remove the risk.

## Re-run proofs

Probes ran on a scratch checkout of MoonAliza 16f637f's tree, extracted with `git archive` (a read on the clone), with
`node_modules` as a directory of symlinks to the clone's entries (`x21_shell_modules`, without `.vite`). Each candidate
was applied with the kit's own `x21_edit` and `X21_*` edits, and the journey test was run with
`npx vitest run tests/zz_accepted_x2_1.test.ts --testTimeout=60000 --reporter=json`.

| candidate | journey test at ad5138f | expected (fix report) |
|---|---|---|
| base (16f637f) | 12 of 17 failed: every journey row, at the pair-state check after the unread start (`[undefined, undefined]` against `['staged','staged']`; `['committed', undefined]` for refresh before commit 4); the 5 guard rows pass | 12 of 17 |
| accepted (01a8604's three source files) | 0 of 17 failed | 0 |
| `X21_ALTERNATIVE` | 0 of 17 failed | 0 |
| `X21_ALTERNATIVE_HELPER` (F1) | 0 of 17 failed | 0 |
| helper imported under another local name, multi-line import (`startupReconcileOptions as reconcileOptionsFor`) | 0 of 17 failed | (new probe) |
| accepted plus a `console.warn` line in the wiring | 0 of 17 failed | (new probe) |
| W-k, keep while less than a day old (F3) | 12 of 17 failed, every journey row | 12 |
| W-l, keep on EACCES/EBUSY only (F7) | 4 of 17 failed, the four EIO rows | 4 |
| **W-m**, keep when unread or the file names no account (R1) | **0 of 17 failed** | (new probe) |
| W-n31 / W-n90, keep while less than 31 / 90 days old (R2) | 0 of 17 failed each | (new probe; disclosed) |

Guard removals (scratch copies of the journey test):

| guard removed | result |
|---|---|
| import binding (`const extra = new Map<string, unknown>()`) | `X21_ALTERNATIVE_HELPER`: 16 of 17 failed, `ReferenceError: startupReconcileOptions is not defined` (fix report: 16 of 17) |
| clock move (`later()` a no-op) | W-k: 0 of 17 failed (fix report: 0) |
| EIO code (`['EACCES', 'EBUSY']`) | W-l: 0 of 13 failed (fix report: 0 of 13) |
| `make-repo.sh` EXIT trap deleted, manifest `accepted_fix` set to forty zeros | without the trap: exit 1, TARGET left in place; with it: exit 1, `make-repo: failed; removed <target>`, TARGET gone |

## Checks

| check | result |
|---|---|
| `python tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (TEMP and TMP on drive C) | 12 tests OK in 2000 s, exit 0 (verified): every wrong fix W-a..W-l graded FAIL through `grade.sh fix` with the count `WRONG-FIXES.md` states; the accepted change and both alternatives PASS; make-repo builds base0 09fe935e… and accepted0 f39d775b… (the manifest's) and removes its target on a mismatch; the launch refusals hold |
| `python tools/test_calibration_kit.py HostPackX21 Docs Hygiene` without the clone | 25 tests OK, 6 skipped with the UNSUPPORTED reason (verified) |
| `python tools/check_secrets.py` | clean, 0 hits (verified) |
| Hygiene scan of every line the branch adds (absolute paths, session or run ids, UUIDs, key shapes, model names) | none (verified) |
| Changed files against `sr-pack-4a.json`'s permitted effects | all within them: the pack directory, `tools/test_calibration_kit.py`, `tools/calibration/subject-pack/README.md`, `CHANGELOG.md`, the reports (verified) |
| Commit ad5138f: identity, trailer, five-part report | `StepenkoAnatoli <318295322+…@users.noreply.github.com>`, `Co-Authored-By` trailer, all five parts (verified) |
| The MoonAliza clone | `git status` clean; the `.vite` and `.vite-temp` timestamps unchanged; my probes reached `node_modules` only through the symlink shell, and the clone was only read (`git archive`, `git show`) (verified) |
| F2 on the branches | `run.template.js:159` (this branch) and `:174` (`build/sr-kit-cases`) still put `Cause: ${f.cause}` in the fix prompt (verified) |

## For fix round 2

1. R1: add the signed-out-orphan row and W-m with its measured grade.
2. R2 (optional, cheap): move the clock years instead of a month, and drop or reword the README's "Time limits beyond a
   month" line.
3. R4 (optional): anchor `wiring()` on the `engine.control({ method: 'vault.references' })` line.
4. F2: the lead records a decision (a kit unit that drops `cause` from the fix prompt or puts it behind a manifest flag,
   a reworded `cause`, or accepting the tier with the cause shown), and R3 goes with it. A fix round of this unit cannot
   settle F2 on its own.
