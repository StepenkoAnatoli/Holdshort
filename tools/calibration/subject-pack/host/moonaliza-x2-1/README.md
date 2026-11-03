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
  `findings[].summary` and `required_behaviour` state the journey, never the accepted change, and never its cause.
  `cause` states the cause, and `cases.fix.cause_in_prompt` (`false`) keeps it out of the candidate's fix prompt (the
  last section).
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
2. The next start's `open()` cannot read the account file: an I/O error such as EACCES, EBUSY or EIO, not a missing
   file. The store shows no account and names no references, and the startup runs its reconcile and both
   `finishStartup()` calls. That start may come long after the crash, and a file that stays unreadable (a bad permission,
   a lock held for days) gives several such starts in a row.
3. A later start can read the file.

At the base (MoonAliza `16f637f`), step 2's reconcile deletes the staged pair because no reference names it, so step 3
finds the refs the file names gone and signs the user out.

**The cause** (`findings[].cause`): during the start that cannot read the account file the store names no references,
and the vault reconcile that start runs deletes every unreferenced staged entry, so it deletes the new pair the unread
file still names.

The crash-window table (spec 4.5, "the file write, before commit") promises a sign-in with the new pair. Required:
after step 3 the pair the file names is committed and live, however many starts of step 2 came first. Each start of
step 2 shows no account, leaves the file as it is, and leaves the pair in the vault as the crash left it, with its
encrypted files. Four things stay as they are. Tombstoned entries are deleted on every start. An unreferenced staged
entry is deleted by the next start that reads the file. A missing file reads as no account, beside a committed
account too, and the start deletes its staged entries. A file that is read and refused (invalid JSON, over 64 KiB, a
key the format does not have, or a value it does not allow, such as version 2) reads as no account too, whatever
account it names and whatever the vault holds beside it: the start deletes the unreferenced staged entries beside it,
the pair that file names among them, and rewrites the file. Only an I/O error other than a missing file (an errno
code) makes a start that cannot read the file (spec 4.4).

## How a host builds the repository and the checkouts

1. **Repository.** Copy this directory outside the kit's tree, then run
   `bash make-repo.sh <moonaliza-clone> <pack dir>/repo` from the copy. The clone must hold `16f637f` and `01a8604`
   (branch `build/github-sign-in`); nothing is written to it. The script makes a bare repository with two root
   commits, each with fixed identity, dates and messages: `base0` is MoonAliza 16f637f's tree without its
   `docs/orchestration/` directory, and `accepted0` is 01a8604's tree without that directory, plus
   `tests/zz_accepted_x2_1.test.ts` (the last section says why the directory goes). Neither commit carries MoonAliza's
   history. The script checks that `base0..accepted0`, the journey test aside, is MoonAliza's `16f637f..01a8604` outside
   `docs/orchestration/`. The ids depend on nothing on the host, so they are the ones `manifest.json` names, and the
   script checks this (on a mismatch it exits 1 and removes what it built, so a rerun is not refused); with the
   manifest's `repository` (`repo`), the copy resolves.
2. **Dependencies.** Install MoonAliza's dependencies with `npm ci` (Node 24) in a directory of their own that
   holds only MoonAliza's `package.json` and `package-lock.json` from `base0`
   (`git -C <pack dir>/repo show <base0 id>:package.json > <install dir>/package.json`, and the same for
   `package-lock.json`), made outside the pack, outside every checkout and outside every git repository's work tree.
   Each checkout links that directory's `node_modules` (step 3), and through `node_modules/..` it reaches the
   directory around it (Git Bash's tools on Windows, and every tool on a POSIX host, resolve `..` through the link).
   So the install must sit where no MoonAliza file and no history is. Never link the install of a MoonAliza clone or
   checkout: through `node_modules/..` a candidate would read its `docs/orchestration/` records, which name the
   finding and give the accepted fix, and the history that holds the accepted commit. `historyless-checkout.sh
   --link` refuses a directory inside any git repository, so a history-less checkout of `base0` is no install site
   either (it has a `.git`; its tree is the candidate's own, but the guard knows a repository only by its markers).
   The guard cannot see a plain copy or an export of MoonAliza's files, so keeping those away from the install is the
   host's part. The manifest's `commands.test` and `commands.run_one` write nothing into the `node_modules` a checkout
   links, so one install serves every cell. By default vitest keeps its results cache in vite's cache dir,
   `node_modules/.vite` of the checkout (vitest 5.0.1, vite 8.3.0), and vite bundles `vitest.config.ts` into
   `node_modules/.vite-temp`; both are written through the link, into the install. The vitest CLI cannot move the
   cache dir (it refuses `--cacheDir` and `--cache.dir`), so both commands say `--no-cache` (no results cache: it only
   orders the test files, so a grade does not depend on an earlier run) and `--configLoader runner` (vite loads the
   config with its module runner, which writes no file). Harness only, never a candidate's setup:
   `tools/test_calibration_kit.py` makes such a directory with `base0`'s two files, but fills its `node_modules` by
   copying the installed `node_modules` of the MoonAliza clone it reads instead of running `npm ci`, which would need
   the network. The lockfile is the same blob at `16f637f`, `01a8604` and the clone's head, the copy holds no link,
   and it checks that every checkout's `node_modules/..` holds no `.git` and no `docs/orchestration/`, that `--link`
   refuses the clone's own `node_modules`, and that a grade and `run_one` leave the install and the clone unchanged.
3. **Checkouts.** Make one per cell with
   `historyless-checkout.sh --pack <pack dir> --link node_modules=<install dir>/node_modules <pack dir>/repo <base0 id> <checkout> <branch>`,
   outside the pack and outside every git repository. On Windows, run it under Git Bash with `MSYS=winsymlinks:nativestrict`, so that `--link` makes a
   real symlink or fails instead of copying the tree. `.build` (the manifest's second link) is linked the same way when
   the host has one; the tests need only `node_modules`. Right after the install, before any candidate runs, seal the
   trees the checkouts link, once per install:
   `bash grade.sh --seal node_modules=<install dir>/node_modules .build=<dir> > <seal>`, with `<dir>` the host's
   `.build`, or an empty directory when it has none (a candidate that puts a tree at that name is then caught), and
   `<seal>` outside the pack, the install and every checkout.
4. **Grade.** Run `bash grade.sh --links <seal> <pack dir>/manifest.json fix <checkout>` on each finished cell, one cell
   at a time. The grade reads each linked tree against the seal before its first command and after its last, and PASS
   needs `linksIntact` true for both names; without `--links` the grade refuses this manifest.
   The subject's vitest config sets a 15 s `testTimeout`, and on the lead's Windows host some of its long tests time
   out under load (grades side by side) and even in a lone grade on a cold cache, which turns a correct candidate's
   run red. So `commands.test` raises the timeout to 60 s (`--testTimeout=60000`), and the accepted journey test gives
   each of its rows 120 s. `commands.run_one`, the command a candidate is told to run, keeps the subject's own
   timeout and adds only the two flags of step 2.

## The names the journey test assumes

The journey test drives a start as the app runs one: a new `Vault` and `GitHubAccountStore` on the crash's data
directory, the store's `open()`, then the startup statements of the candidate's own `src/main/index.ts`. Those are the
statements after the one that reads the engine's references (the statement holding the engine call whose argument has
`method: 'vault.references'`, or a later one that declares `references` when the call's result is parsed in a
statement of its own), up to the statement that calls `supervisor.attach()`, in the one block that holds both. They
run with the start's vault, store and engine references and a collector holding no token. The test parses the
candidate's file with TypeScript and transpiles the statements with esbuild (both dependencies of the subject), so
whatever name a fix gives its flag, and however it lays out its lines, the test runs the wiring the fix wrote. It
assumes only names the base already has, which belong to the required behaviour, not to any fix:

- `Vault`: the constructor, `initialize`, `saveStaged`, `commit`, `tombstone`, `has`, and `reconcile` called with the
  references alone (the vault-default row). The candidate's own wiring calls `reconcile` however it chooses.
- `GitHubAccountStore`: the constructor `(file, vault, clientId, clock)`, `open`, `replace`, `clear`, `current` and
  `openedAppChanged`.
- The account file at `<data>/github/account.json` and the vault index at `<data>/vault/index.json`, read as JSON: the
  crash-window table speaks of both.
- The two anchors of `src/main/index.ts`, found as the parser reads the file: the engine call by its
  `method: 'vault.references'` argument and the `supervisor.attach()` call. A comment, a string, a regex literal, a line
  break or a missing `;` a candidate adds does not move them, and a call wrapped over several lines, or a statement
  that shares a line with an anchor, is read whole. The identifiers the startup statements use there: `vault`,
  `references`, `collectorSettings` and `githubStore`. Every name `index.ts` imports from `./github-account-store` or
  `./vault` (named, renamed with `as`, a default or a namespace; type-only imports bind nothing) is bound as well, to
  the candidate's own export, so a wiring that calls a helper one of those modules exports runs as the app would run
  it.

It names nothing the accepted fix added. A vault-level row that called the accepted fix's new option directly would
fail every other correct fix, so the journey rows assert what such a row would: the entries are kept, with their files
and in their states. Each later start runs as the app's next start does, in a new process of its own: node, with an
empty environment, loads the candidate's two modules (bundled once per run by esbuild from the candidate's own
source), drives the start and reports the account it read, whether the file was issued to another app and which refs
its vault holds. So nothing the first session or an earlier start kept in memory reaches a later start, whether a
module kept it or the process did (on `globalThis`, on `process` or in its environment, on a built-in module object or
under a `Symbol.for` key), and a fix that keeps the refs of the last file its process wrote fails
(W-r3 keeps them in a module variable, W-r4 on `globalThis`). What a start leaves on disk reaches the next start, as it
does in the app. An unreadable file is simulated by failing every read of that one file for the whole of the start's
process, as a file another process holds or a permission denies fails every read, where a real one fails: at the
stat (a directory on the way that may not be searched), at the open (a file another process opened without sharing
it, a permission on the file) or at the read (a byte-range lock, a failing disk). At the stat, every `node:fs`
function that reads a file by its path fails (`open`, `readFile`, `stat`, `lstat`, `access`, `copyFile` and `cp`,
each in its promise, callback and synchronous form, `cp` also from a directory that holds the file, and
`openAsBlob`), and so does the module loader (an `import` or a `require` of the file). At the open, the file's `stat`,
`lstat` and `access` succeed and the rest fail. At the read, the file's `stat`, `lstat`, `access` and `open` succeed
and every read of what the open gave fails (`read` and
`readv` of the descriptor; a FileHandle's `read`, `readv`, `readFile`, `readLines`, stream and web stream), as do
`readFile`, `copyFile`, `cp`, `openAsBlob` and the module loader by the file's path. A stream from `createReadStream`
opens and reads through the callback `open` and `read` and meets the error as its `error` event. The error has a real
one's shape: the code, libuv's errno and message for it, the syscall that failed (`open`, `read`, `stat`, `lstat`,
`access`, `copyfile`) and the path. The faulted file is known by its identity (its device and file index, which every
name of the file shares), not by its path, so a hard link, a rename, a symlink or a junction, or another spelling of
the path (a relative path, another case, a `\\?\` prefix) meets the error too, and the path is taken in every form
`node:fs` takes one (a string, a Buffer or another `Uint8Array`, a `file:` URL or an object `node:fs` reads as one):
the fault hands the argument to the real `stat`, so it reads each form as `node:fs` does, and only a descriptor or a
FileHandle, which only an open can give, names no path. The start's process puts these wrappers in place before it
loads the subject's modules, so a read function the subject takes as its module loads is a wrapper too. So a fix that
re-reads the file another way through `node:fs`, or by another name, still meets the error (W-a retries the same read,
W-r reads it by a stream, W-r2 through a `promisify(readFile)` taken as its module loads, W-r5 through a hard link it
makes to the file, W-t with the path as a `Uint8Array` and W-t2 with it as an object shaped as a `file:` URL).
In the journey rows, the other-errno row, the unreadable-run row and the orphan row the starts after the crash run
ten years on, and each start after that ten years later again: vitest's fake timers move `Date` in the test's process,
and a start's own process runs with every clock it reads moved as much (`Date`, `performance.timeOrigin`, the date
`Intl.DateTimeFormat` formats when given none, and `process.hrtime`; the system's uptime stays, as ten years on the
system has booted since the crash). Before each start the times of every file and directory in the data directory are
moved back by as much as the clock moved since they were written, so the real clock reads a file the start writes as
that much newer than the crash's. So a fix that keeps the pair only while it is recent fails, whatever age limit it
picks short of that and whichever of these clocks it reads (W-k keeps for a day by `Date`, W-u for a day by
`performance`'s clock, W-u2 by `Intl`'s, W-u3 by file times, W-n for a year), and so does one that counts the age from
the boot time (W-u4). The store's clock is injected and fixed, so only the vault sees the move.
The journey rows fail the reads with EACCES, EBUSY and EIO, and
the other-errno row, at the same four crash points, with EPERM, EMFILE, EINVAL and UNKNOWN (libuv's code for an error
it does not map), so a fix that keeps only on a list of codes it takes for passing ones fails unless the list holds
all seven (W-l keeps on EACCES and EBUSY, W-l2 on EACCES, EPERM, EBUSY, EAGAIN and EIO). In both rows each code fails
three starts in a row, ten years apart: at the stat, at the open and at the read, so a fix that decides on where the
error came from rather than on its code fails too (W-l3 deletes the pair after a failed read, taken for a failing
disk, and W-l4 tells the read by the error's message; on a real byte-range lock the read fails with EBUSY). The unreadable-run row runs
four unreadable starts in a row (EACCES, EACCES again, EBUSY, then EIO), at the stat, the open, the read and the stat,
each ten years after the one before, for a
first sign-in that crashed before commit 1 and a refresh that crashed before commit 4, so a fix that keeps the pair
through only one, two or three such starts fails (W-p keeps it through one), and so does one that takes the same error
twice in a row for an abandoned pair.
The orphan row runs the same four unreadable starts before its readable one, so a fix that holds an unreferenced
staged entry for good once it has outlived a run of up to four unreadable starts fails too (W-q holds it after two).
The refused-file row refuses the signed-out file and the named refused-file row refuses a file that still names the
new pair, each as invalid JSON, over 64 KiB, with an extra key and with version 2. The named row does so after a first
sign-in's crash before commit 1 (no committed entry in the vault) and, beside the old committed pair, after
a sign-in's or a refresh's crash before commit 3 and a refresh's before commit 4, as a downgrade finds a signed-in
vault. So a fix that keeps the staged entries a refused file still names fails (W-o3 reads the file again without the
format), so does one that keeps on another format version (W-o4), and so does one that keeps beside a refused file
only while the vault holds a committed entry (W-o5). The ENOENT row removes the file after a first sign-in that
crashed before any file existed and, beside a committed account, after a sign-in that crashed after staging and a
refresh that crashed before commit 3, so a fix that takes a lost file beside a committed account for one whose
references are unknown fails too (W-h3).

## What the pack does not discriminate

- **Wiring that moves.** A fix that reconciles somewhere other than between the two anchors of `index.ts`, that
  moves the engine call or the `supervisor.attach()` call out of the one block that holds both (into a `try` block, say,
  or a helper function), that reads the references with something other than the `method: 'vault.references'` literal
  (a constant holding it, say), or that renames `vault`, `references`, `githubStore` or `collectorSettings` there, fails
  the journey test even when it is correct: the startup statements are not found, or they meet a name that is not in
  scope. The base's startup order is part of the required behaviour, so such a fix is out of the task's scope, and the
  case's `instructions` state these limits to the candidate.
- **Other names in the startup statements.** The test runs those statements on their own, with the four names above
  and what `index.ts` imports from `./github-account-store` or `./vault`. A statement there that uses any other name of
  `index.ts` (a helper declared in `index.ts` itself, `engine`, or a name imported from another module, such as `z`)
  throws a ReferenceError in every row that runs a start, so such a fix fails even when it is correct. The case's
  `instructions` state this limit to the candidate.
- **Errno codes the rows do not use.** The rows fail the reads with EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL and
  UNKNOWN. The rule is the same for every errno code but ENOENT, but a fix that keeps only on a list of codes passes when
  its list holds all seven, and so does one that deletes only on some code the rows do not use. Each of the seven
  arrives from the first call of the three points a fix makes (the stat, the open, the read; the other calls by the
  path, `access`, `copyFile`, `cp`, `openAsBlob` and the module loader, fail with their own syscall), so the syscall
  an error carries is the one a real failure there gives; a fix that decides on what a real error never says (a
  syscall only a call the rows never fail could give) is not reached.
- **Clocks a start cannot move.** A file's creation and change times (`birthtime`, `ctime`: no program sets them) are
  the real ones, and a clock outside the start's process (another process's, a server's) is not moved. So a fix that
  ages a kept pair by one of them passes. The system's uptime is not moved either, but ten years on the system has
  booted since the crash (see the journey), so a fix that ages the pair from the boot time fails (W-u4). `Temporal` is not in the
  Node the subject runs (24) without a flag.
- **Reads outside `node:fs`.** The fault is on `node:fs` and the module loader in the main thread of the start's own
  process. A second read of the file through a child process, a worker thread, a native addon, WASI or Node's internal
  bindings is not failed, so a fix that learns the pair's refs that way and keeps only those passes, although on a real
  unreadable file that read fails too and the pair is lost.
- **Paths beside the subject's own module.** A start's process runs the candidate's two modules bundled into one file
  in a temporary directory, so code in them that finds a file beside its own module (`import.meta.url`, `__dirname`)
  looks there, not in `src/main/`, and a correct fix that does so fails. Neither module does so at the base.
- **Refusals other than the four.** The refused-file rows write invalid JSON, a file over 64 KiB, a file with an extra
  key and a file with version 2, on the signed-out file and on a file that names the new pair. Other values the format
  does not allow (a revision of 0, a malformed ref, a ninth retired ref) are refused the same way but are not written,
  so a fix that keeps only on one of them passes. A path the store refuses because it is not a plain regular file (a
  symlink, a directory, a file with a second hard link) is refused the same way, with no errno code, but is not
  exercised.
- **Vault states beside a refused or missing file.** The rows put beside it either no committed entry or one
  account's committed pair (and, before commit 4 of a refresh, the new access entry), so a fix that keeps on some other
  state of the vault (two accounts' committed entries, say, or a staged entry the engine names) passes.
- **Runs of more than four unreadable starts.** The unreadable-run row and the orphan row run four in a row, so a fix
  that keeps the pair through four such starts and drops it at the fifth passes, and so does one that holds an orphan
  pair for good only after five.
- **Time limits beyond ten years.** The later starts run ten years after the crash, so a fix that drops a kept pair
  only once it is older than that passes.
- **Crash points.** Only the four the table names: before commit 1 of a first sign-in, and before commits 3 and 4 of a
  replace. A crash during the reconcile itself, or a rollback write that failed (spec 4.3 step 5), is not exercised.
- **Quality beyond the pass rule.** The grade is mechanical: a fix that passes may still be larger than it needs to be
  (`srcDiffLines` records the size), and the map clause is recorded (`committedWithMap`), not required.
- **One host only.** The cells measure a profile on MoonAliza's fix category. The shared pack is the comparable one.

## Why there is no pin and no review case

Stage 4a of calibration run 4 measures `fix@T3` alone. The journey test is the grade's pin, not a candidate's task, so
there is no `pin` case. No review ground truth is adjudicated for this subject at this base (run 2's other findings
in these files are not part of this pack), so there is no `review` case.

The manifest keeps the real cause in `findings[].cause`, and `cases.fix.cause_in_prompt` is `false`, so the kit's fix
prompt (`run.template.js`) prints the finding's summary and required behaviour but not its cause. The summary, the
required behaviour and the case's `instructions`, which the prompt prints as they are, state the journey and the
grade's limits, not the cause. No pack file reaches a candidate: a checkout is a history-less tree of `base0` alone,
made outside the pack (`historyless-checkout.sh --pack` and the launch refuse a shared path), and `grade.sh` places the
journey test only when it grades.

**MoonAliza's orchestration records are left out of both trees.** At 16f637f, `docs/orchestration/` holds MoonAliza's
own records of its runs, and some of them name X2-1, state its cause with file and line, and give the accepted fix line
by line (`docs/orchestration/2026-10-13-github-sign-in/briefs/fix-x2-1.md` among them). A checkout is `base0`'s tree,
and a candidate may read anything in it, so `make-repo.sh` exports both trees without the whole directory (the records
are not subject code, and any of them may describe the fix) and copies into the pack repository only the objects the two
filtered trees reach, so the records are not in it at all. No graded command reads that directory: the subject's tests,
eslint and the journey test give the same results without it. `tools/test_calibration_kit.py` checks that each tree is
MoonAliza's tree minus `docs/orchestration/` (the journey test aside), that no excluded object and no blob the two trees
do not reach is in the pack repository, and that no file and no path name of `base0` holds, in any case, `X2-1`,
`x2_1`, the accepted fix's two new names or a phrase of the cause (whitespace collapsed; the same scan of MoonAliza
16f637f finds hints only under `docs/orchestration/`). That check is textual: a paraphrase of the cause elsewhere in the
tree is not caught by it. MoonAliza's own code, spec and tests describe how the reconcile treats staged entries, as the
base must; the grade's limits are stated to the candidate in the `instructions`.
