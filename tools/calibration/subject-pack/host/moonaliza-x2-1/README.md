<!-- Lineage: the host-pack counterpart of ../../shared/README.md, for calibration run 4 stage 4a (fix@T3): finding X2-1 of calibration run 2 (S3, cluster C-B, adjudicated real by three lenses) in MoonAliza's GitHub sign-in, as a pack in the format of ../../README.md. -->

# Host subject pack moonaliza-x2-1 (version 1)

A host pack (`kind: host`): a real accepted defect pair from MoonAliza, the repository calibration runs 1-3 measured,
graded with the kit's `grade.sh fix`. It holds one case, `fix` at tier T3: a candidate gets the finding (the journey that
loses the account), the three modules in scope and the shipped harnesses, and fixes it red-first. Its cells qualify a
profile for MoonAliza's own fix category and do not compare across hosts.

**The pack carries no MoonAliza code.** It carries the manifest, the ground truth, the accepted journey test, the
wrong-fix matrix and `make-repo.sh`, which builds the pack repository from a MoonAliza clone the host provides.

## Files

- `manifest.json`: the pack manifest (the format of `../../README.md`): one finding, X2-1, and one case, `fix` at T3.
  `findings[].summary`, `cause` and `required_behaviour` state the journey and its cause, never the accepted change.
- `make-repo.sh`: `make-repo.sh <moonaliza-clone> <target>` builds the pack repository (below).
- `zz_accepted_x2_1.test.ts`: the accepted journey test. `make-repo.sh` adds it to the accepted commit at
  `tests/zz_accepted_x2_1.test.ts` (`paths.accepted_test.from`), and `grade.sh` places it at the same path
  (`paths.accepted_test.to`) in a candidate's checkout and runs it against the candidate's source.
- `WRONG-FIXES.md`: the wrong-fix matrix: every wrong fix named, the row of the journey test that catches it, and its
  grade.
- `.gitattributes`: keeps the pack's bytes as committed on every host. The source hashes and the accepted commit's id
  depend on those bytes.
- `README.md`: this file.

## The journey

1. A sign-in (the first one, or one that replaces an account) or a refresh reaches step 4 of `replace()`: the account
   file now names the new pair, which the vault still holds staged. The process dies before step 5 commits the pair, or
   after it commits only the access ref.
2. The next start's `open()` cannot read the account file: an I/O error such as EACCES or EBUSY, not a missing file. The
   store shows no account and names no references, and the startup runs its reconcile and both `finishStartup()` calls.
3. The start after that can read the file.

At the base (MoonAliza `16f637f`), step 2's reconcile deletes the staged pair because no reference names it, so step 3
finds the refs the file names gone and signs the user out. The crash-window table (spec 4.5, "the file write, before
commit") promises a sign-in with the new pair. Required: after step 3 the pair the file names is committed and live.
Step 2 shows no account, leaves the file as it is, and leaves the pair in the vault as the crash left it, with its
encrypted files. Three things stay as they are. Tombstoned entries are deleted on every start. An unreferenced staged
entry is deleted by the next start that reads the file. A missing file reads as no account, and the start deletes its
staged entries.

## How a host builds the repository and the checkouts

1. **Repository.** Copy this directory outside the kit's tree, then run
   `bash make-repo.sh <moonaliza-clone> <pack dir>/repo` from the copy. The clone must hold `16f637f` and `01a8604`
   (branch `build/github-sign-in`); nothing is written to it. The script makes a bare repository with two root
   commits, each with fixed identity, dates and messages: `base0` is MoonAliza 16f637f's tree as it is, and `accepted0`
   is 01a8604's tree plus `tests/zz_accepted_x2_1.test.ts`. Neither commit carries MoonAliza's history. The ids depend
   on nothing on the host, so they are the ones `manifest.json` names, and the script checks this; with the manifest's
   `repository` (`repo`), the copy resolves.
2. **Dependencies.** Install MoonAliza's dependencies (`npm ci` in a MoonAliza checkout of `16f637f`, Node 24) outside
   the pack and outside every checkout. vitest writes its caches into the `node_modules` a checkout links
   (`node_modules/.vite`, `node_modules/.vite-temp`), so link an install the host may write to, never a read-only
   clone's. A directory of its own whose entries are symlinks to an install's entries is enough.
   `tools/test_calibration_kit.py` builds one so that the clone stays untouched.
3. **Checkouts.** Make one per cell with
   `historyless-checkout.sh --pack <pack dir> --link node_modules=<installed outside the pack> <pack dir>/repo <base0 id> <checkout> <branch>`,
   outside the pack. On Windows, run it under Git Bash with `MSYS=winsymlinks:nativestrict`, so that `--link` makes a
   real symlink or fails instead of copying the tree. `.build` (the manifest's second link) is linked the same way when
   the host has one; the tests need only `node_modules`.
4. **Grade.** Run `bash grade.sh <pack dir>/manifest.json fix <checkout>` on each finished cell, one cell at a time.
   The subject's vitest config sets a 15 s `testTimeout`, and on the lead's Windows host some of its long tests time
   out under load (grades side by side) and even in a lone grade on a cold cache, which turns a correct candidate's
   run red. So `commands.test` raises the timeout to 60 s (`--testTimeout=60000`), and the accepted journey test gives
   each of its rows 120 s. `commands.run_one`, the command a candidate is told to run, stays the subject's own.

## The names the journey test assumes

The journey test drives a start as the app runs one: a new `Vault` and `GitHubAccountStore` on the crash's data
directory, the store's `open()`, then the startup lines of the candidate's own `src/main/index.ts`. Those are the lines
after the one that reads the engine's references (`vault.references`), up to the one that attaches the supervisor
(`supervisor.attach(`), run with the start's vault, store and engine references and a collector holding no token. The
test reads them from the candidate's file and transpiles them with esbuild (a dependency of the subject), so whatever
name a fix gives its flag, the test runs the wiring the fix wrote. It assumes only names the base already has, which
belong to the required behaviour, not to any fix:

- `Vault`: the constructor, `initialize`, `saveStaged`, `commit`, `tombstone`, `has`, and `reconcile` called with the
  references alone (the vault-default row). The candidate's own wiring calls `reconcile` however it chooses.
- `GitHubAccountStore`: the constructor `(file, vault, clientId, clock)`, `open`, `replace`, `clear`, `current` and
  `openedAppChanged`.
- The account file at `<data>/github/account.json` and the vault index at `<data>/vault/index.json`, read as JSON: the
  crash-window table speaks of both.
- The two anchor lines of `src/main/index.ts`, and the identifiers the startup lines use there: `vault`, `references`,
  `collectorSettings` and `githubStore`.

It names nothing the accepted fix added. A vault-level row that called the accepted fix's new option directly would
fail every other correct fix, so the journey rows assert what such a row would: the entries are kept, with their files
and in their states. An unreadable file is simulated by failing every read of that one path (`lstat`, `stat`, `open`
and `readFile` in `node:fs/promises`, and their synchronous forms) for the whole start, so a fix that re-reads the file
another way still meets the error.

## What the pack does not discriminate

- **Wiring that moves.** A fix that reconciles somewhere other than between the two anchor lines of `index.ts`, or that
  renames `vault`, `githubStore` or `collectorSettings` there, fails the journey test even when it is correct. The
  base's startup order is part of the required behaviour, so such a fix is out of the task's scope.
- **Errors other than EACCES and EBUSY.** EIO, EPERM and others are not exercised; the rule is the same, any errno code
  but ENOENT.
- **Crash points.** Only the four the table names: before commit 1 of a first sign-in, and before commits 3 and 4 of a
  replace. A crash during the reconcile itself, or a rollback write that failed (spec 4.3 step 5), is not exercised.
- **Quality beyond the pass rule.** The grade is mechanical: a fix that passes may still be larger than it needs to be
  (`srcDiffLines` records the size), and the map clause is recorded (`committedWithMap`), not required.
- **One host only.** The cells measure a profile on MoonAliza's fix category. The shared pack is the comparable one.

## Why there is no pin and no review case

Stage 4a of calibration run 4 measures `fix@T3` alone. The journey test is the grade's pin, not a candidate's task, so
there is no `pin` case. No review ground truth is adjudicated for this subject at this base (run 2's other findings
in these files are not part of this pack), so there is no `review` case.

The kit's fix prompt (`run.template.js`) gives the candidate the finding's `cause` along with its summary and its
required behaviour. Keeping the cause from the candidate needs a kit change, which this pack does not make. The
manifest's cause says where the loss happens (the reconcile during the unreadable start), never how to fix it.
