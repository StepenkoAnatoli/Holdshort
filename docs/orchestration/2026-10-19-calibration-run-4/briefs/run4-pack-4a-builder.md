# Unit sr-pack-4a: the host subject pack for calibration run 4 stage 4a (`fix@T3`), subject X2-1

Worktree and branch: created by the lead from Holdshort `main` (the kit, #106-#108 merged; the launch prompt names
the head). Work only under `tools/calibration/subject-pack/host/moonaliza-x2-1/`,
`tools/test_calibration_kit.py` (a new `HostPackX21` class), `tools/calibration/subject-pack/README.md` (one
paragraph: a host pack example lives beside the shared one), `CHANGELOG.md` (one line), plus your report file under
`docs/orchestration/2026-10-19-calibration-run-4/reports/`. Holdshort's pre-commit hook runs the regression gate on
every commit; never --no-verify, never unwire it; no push. Commit identity, trailers, five-part reports, red-first
tests with guard-removal proofs, reports: `briefs/conventions.md` (beside this brief).

The subject code is MoonAliza's (branch `build/github-sign-in`, read only; the launch prompt names the clone you read
from). **The pack carries no MoonAliza code**: it carries the manifest, the ground
truth, the accepted journey test, the wrong-fix matrix and a `make-repo.sh` that builds the pack repository from a
MoonAliza clone the host provides (`make-repo.sh <moonaliza-clone> <target>`), exporting the base tree `16f637f` and
the accepted tree `01a8604` as two root commits with fixed identity and dates, so the ids are deterministic. The
manifest's `repository` is the path the host passes; the committed manifest carries the default built beside it for
the kit's tests, which run only when a MoonAliza clone is available (`MOONALIZA_CLONE` in the environment; otherwise
the tests that need it report UNSUPPORTED, never pass).

## The finding (ground truth), stated as a journey, never as the fix

X2-1, S3, cluster C-B of calibration run 2 (adjudicated real by three lenses): a sign-in whose `replace()` crashes
between step 4 (the account file write naming the new, still-staged pair) and step 5 (the commit), followed by a
start whose `open()` cannot read the account file (an I/O error other than ENOENT), followed by a readable start,
loses the account: the second start's reconcile deletes the staged pair as unreferenced and the third start finds
the named refs gone. Spec 4.5 row 2 promises the opposite. Required behaviour: after that journey the pair the file
names is committed and live, and a refresh variant (the old pair retired) ends the same way; tombstoned entries are
still deleted on every start and an unreferenced staged entry is deleted on the next readable start. The cause is
NOT in the candidate's task text: the candidate gets the journey, the modules in scope (`src/main/github-account-store.ts`,
`src/main/vault.ts`, `src/main/index.ts`), the harnesses (`tests/github-account-store.test.ts` with its crash-window
helpers and `unreadStart`, `tests/vault.test.ts`), and the acceptance rule.

## The lead's decisions

H1. **Wrong-fix matrix first.** Before writing the pin, list every wrong fix you and the lead can name and show each
    graded FAIL on the accepted pin alone, in a committed table `WRONG-FIXES.md` (id, the wrong idea in one line,
    which pin row catches it, the grade). Start from these, and add your own: (a) retry the read at `open()` (a
    persistent EACCES still loses the pair); (b) skip the whole reconcile when the file is unread (a tombstoned entry
    from a sign-out survives; GS-11); (c) keep every staged entry on every start (the next readable start must delete
    an unreferenced one); (d) make `references()` return the vault's staged refs (the store has no such view; the fix
    must not widen U0's contract: scope rule); (e) commit unreferenced staged entries on an unread start (they must
    stay staged); (f) keep staged entries but still unlink their files; (g) fix the sign-in path only (the refresh
    variant, old pair in `retiredRefs`, still loses the account); (h) set the keep flag from `openedAppChanged()` or
    from a missing file (ENOENT must not keep). Each row of the accepted pin exists to catch one of these; a wrong
    fix no row catches means a row is missing.
H2. **The accepted journey test** `tests/zz_accepted_x2_1.test.ts` (placed by grade.sh as `paths.accepted_test.to`),
    vitest, built from the X2-1 rows of `tests/github-account-store.test.ts` and `tests/vault.test.ts` at `01a8604`
    and the wrong-fix matrix: the double fault for sign-in and for refresh with the reconcile called as `index.ts`
    calls it, the tombstone-still-deleted row, the unreferenced-staged-deleted-on-readable-start row, the ENOENT row,
    and the vault-level rows (`keepStaged` keeps entry and file; default behaviour unchanged). Red at `16f637f` for
    every journey row, green at `01a8604`. It must not import the accepted fix's new names where a different correct
    fix would use others: drive the behaviour through the startup order the wiring uses (store `open()`, reconcile,
    `finishStartup()`), and say in the README which names it does assume and why they are part of the required
    behaviour, not of the fix. An alternative correct fix (write one: e.g. the store exposing an "unread" flag under
    another name, read by the wiring) must also PASS.
H3. **Manifest** (`manifest.json`, the kit's format): `kind: host`, `pack: moonaliza-x2-1`, `pack_version: "1"`, one
    case `fix` at `tier: T3` with the journey as `findings[].required_behaviour`, `summary` and `cause` written for
    the grader only (the cause names the reconcile's deletion of unreferenced staged entries during an unread start;
    the candidate never sees it), `paths.source` the three source files, `paths.test_file`
    `tests/github-account-store.test.ts`, `paths.allowed_extra` `tests/vault.test.ts`, `tests/github-main-wiring.test.ts`,
    `docs/ARCHITECTURE.md`, `paths.map_file docs/ARCHITECTURE.md`, `paths.new_test_pattern ^tests/.*x2.*\.test\.ts$`,
    `commands.test` `npx vitest run {files} --reporter=json --outputFile={report}` with `test_report vitest-json`,
    `commands.lint` `npx eslint {files}`, `commands.timeout_seconds 900`, `checkout.links` `["node_modules", ".build"]`,
    `source_hashes` of every pack file, the isolation statement; no pin and no review case (document why: 4a is
    `fix@T3` alone). Pass rule, verbatim in the manifest and the protocol: "the candidate's tests are green at its head
    AND red again with the three source files restored to the base AND the accepted journey test is green against the
    candidate's source AND every changed file is one of the three source files, the two test files, the wiring test or
    the map, or a newly added test file matching the pattern AND eslint is clean on those files".
H4. **Tests** (`HostPackX21` in `tools/test_calibration_kit.py`): with a MoonAliza clone, `make-repo.sh` yields the
    two deterministic ids recorded in the manifest; the accepted journey test is red at base and green at accepted;
    every WRONG-FIXES row grades FAIL through `grade.sh fix` (apply the wrong fix as the candidate's change on a
    history-less checkout); the accepted fix and the alternative correct fix grade PASS; the filled `run.template.js`
    passes the launch refusals under the stub harness with this manifest and a protocol whose only case is `fix`.
    Without the clone: the K3 hygiene scan over the pack (no absolute host path, session id or run id), the manifest's
    shape, and the source hashes.
H5. **Docs.** The pack README: what the pack is, the journey, how the host builds the repository and the checkouts
    (`--link node_modules=<installed outside the pack>`), what the pack does not discriminate; `WRONG-FIXES.md`.

## Deliverables and stop triggers

A. The pack per H1-H3, H5. B. Tests per H4. C. The docs lines. D. Gate green through the hook on every commit.
Stop and report if `grade.sh` cannot grade this pack without a kit change (name the change; do not edit kit files),
or if a wrong fix cannot be caught by any test the pass rule admits.
