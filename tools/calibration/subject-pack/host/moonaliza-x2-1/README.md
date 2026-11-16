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
   needs `linksIntact` true for both names; without `--links` the grade refuses this manifest. The two linked names
   are the only paths the base lacks that the commands see unless the grade counts them as the candidate's: the grade
   sets every other one aside while they run (`setAside`, the kit README's limits).
   The subject's vitest config sets a 15 s `testTimeout`, and on the lead's Windows host some of its long tests time
   out under load (grades side by side) and even in a lone grade on a cold cache, which turns a correct candidate's
   run red. So `commands.test` raises the timeout to 60 s (`--testTimeout=60000`), and the accepted journey test gives
   each of its rows 120 s, and 300 s to the thirteen rows that run the most starts (the lasting row, the orphan-codes
   row, the tombstone-at-each-point row, the two keep-at-each-point rows, the four vault-state rows of both kinds, the
   two point-pair rows and the two start-sequence rows).
   `commands.run_one`, the command a candidate is told to run, keeps the subject's own
   timeout and adds only the
   two flags of step 2.

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
- `GitHubAccountStore`: the constructor `(file, vault, clientId, clock)` (a later start passes no clock, as `index.ts`
  passes none), `open`, `replace`, `clear`, `current` and
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
stat (a permission that denies reading the file's attributes), at the open (a file another process opened without sharing
it, a permission on the file) or at the read (a byte-range lock, a failing disk). At the stat, every function of
`node:fs` and `node:fs/promises` that takes a path fails on the file, in its promise, callback and synchronous form:
those that read its bytes (`open`, `readFile`, `copyFile`, `cp`, `cp` also from a directory that holds the file, and
`openAsBlob`) and those that read its attributes, its link target, its real path or a directory's entries (`stat`,
`lstat`, `access`, `statfs`, `readlink`, `realpath` and `realpath.native`, `readdir`, `opendir` and `watch`);
`exists` and `existsSync` answer false, as a real one does when the stat fails; and so does the module loader (an
`import` or a `require` of the file). The functions are read from the two modules as the running Node has them, not
from a list of names: one the fault's table does not name (one a later Node adds, say) fails at every point, as a
read of the file's bytes does. Only the writes (the fault is on reads), the functions that take a descriptor rather
than a path, and `createReadStream`, `glob`, `watchFile` and `unwatchFile` are left out (the limits). At the open,
the functions that read the file's attributes, link target, real path or a directory's entries succeed, `exists` and
`existsSync` answer true, and those that read its bytes fail. At the read, those succeed and so does `open`, and
every read through a descriptor of the file fails, however the descriptor was had (`read`, `readv` and `readFile` of
a descriptor, a FileHandle's `fd` among them, and so a stream on one; a FileHandle's `read`, `readv`, `readFile`,
`readLines`, stream and web stream), as do `readFile`, `copyFile`, `cp`, `openAsBlob` and the module loader by the
file's path. A stream from `createReadStream` opens and reads through the callback `open` and `read`
and meets the error as its `error` event. The error has a real one's shape: the code, libuv's errno and message for
it, the syscall that failed (the one the real call makes: `open`, `read`, `stat`, `lstat`, `access`, `copyfile`,
`scandir` and so on) and the path. The faulted file is known by its identity (its device and file index, which every
name of the file shares), not by its path, so a hard link, a rename, a symlink or a junction, or another spelling of
the path (a relative path, another case, a `\\?\` prefix) meets the error too, and the path is taken in every form
`node:fs` takes one (a string, a Buffer or another `Uint8Array`, a `file:` URL or an object `node:fs` reads as one):
the fault hands the argument to the real `stat`, so it reads each form as `node:fs` does. A descriptor or a
FileHandle names no path: it is known by the identity of the file it is open on, through the real `fstat`, so a read
through a FileHandle's `fd` meets the error too (W-l5 reads the file again that way). The start's process puts these wrappers in place before it
loads the subject's modules, so a read function the subject takes as its module loads is a wrapper too. So a fix that
re-reads the file another way through `node:fs`, or by another name, still meets the error (W-a retries the same read,
W-r reads it by a stream, W-r2 through a `promisify(readFile)` taken as its module loads, W-r5 through a hard link it
makes to the file, W-t with the path as a `Uint8Array` and W-t2 with it as an object shaped as a `file:` URL). A fix
that asks `existsSync` whether the file is still there meets a false at the stat and at the directory, as a real one
does there, so one that takes a file gone since the failure for a deletion race fails too (W-x keeps only while
`existsSync` sees the file).
The lasting row also fails a start at the directory, as a directory on the way that may not be searched does: every
path inside the account file's directory, there or not, by any spelling or link that leads there, meets the stat's
failure (the reads above fail for it as at the stat), so a copy of the refs kept beside the file fails too (W-s keeps
one beside the file and keeps the refs it names).
In the journey rows, the other-errno row, the unreadable-run row, the orphan row, the lasting row, the engine row, the
engine-key row, the orphan-codes row, the keep-at-each-point rows and the vault-state rows (both kinds) the starts after
the crash run ten years on, and each start after that
ten years later again: vitest's fake timers move `Date` in the test's process,
and a start's own process runs with these clocks moved as much: `Date`, `performance.timeOrigin`, the date
`Intl.DateTimeFormat` formats when given none, and `process.hrtime` (the system's uptime stays, as ten years on the
system has booted since the crash; any other clock stays real: the limits). Before each start the times of every file
and directory in the data directory are
moved back by as much as the clock moved since they were written, so the real clock reads a file the start writes as
that much newer than the crash's (the file times are moved against each other, not against a time a file stores: the
limits). The first session's store has a fixed clock of its own (the account file's dates); a later start's store is
given none, as `index.ts` gives it none, so it reads the store's default, `Date.now`, which is moved. A date's
constructor (`Date.prototype.constructor`, so `new Date().constructor`) is the moved `Date` too. So a fix that keeps
the pair only while it is recent fails, whatever age limit it picks short of that and whichever of these clocks it
reads (W-k keeps for a day by `Date`, W-u for a day by `performance`'s clock, W-u2 by `Intl`'s, W-u3 by file times,
W-u5 by the store's clock, W-u6 by `Date` reached through a date's constructor, W-n for a year), and so does one that
counts the age from the boot time (W-u4).
The journey rows fail the reads with EACCES, EBUSY and EIO, and
the other-errno row, at the same four crash points, with EPERM, EMFILE, EINVAL and UNKNOWN (libuv's code for an error
it does not map), so a fix that keeps only on a list of codes it takes for passing ones fails unless the list holds
all seven (W-l keeps on EACCES and EBUSY, W-l2 on EACCES, EPERM, EBUSY, EAGAIN and EIO). In both rows each code fails
three starts in a row, ten years apart: at the stat, at the open and at the read, so a fix that decides on where the
error came from rather than on its code fails too (W-l3 deletes the pair after a failed read, taken for a failing
disk, W-l4 tells the read by the error's message, and W-l5 deletes after a failed read unless a read through a new
FileHandle's descriptor succeeds; on a real byte-range lock the read fails with EBUSY). The unreadable-run row runs
four unreadable starts in a row (EACCES, EACCES again, EBUSY, then EIO), at the stat, the open, the read and the stat,
each ten years after the one before, for a
first sign-in that crashed before commit 1 and a refresh that crashed before commit 4, so a fix that keeps the pair
through only one, two or three such starts fails (W-p keeps it through one), and so does one that takes the same code
twice in a row for an abandoned pair. The lasting row runs the same failure, code and call, at four starts in a row,
ten years apart, as a lasting cause gives it: EACCES at the directory after a first sign-in's crash before commit 1,
EACCES at the open after a sign-in's before commit 3, and EIO at the read after a refresh's before commit 4. So a fix
that takes the same failure twice in a row for an abandoned pair fails too (W-p2 keys it on the code and the call).
The engine row gives each unreadable start a staged entry the engine names beside the kept pair (a credential the
engine stores), after a first sign-in's crash before commit 1 and a refresh's before commit 4, with EACCES at the
stat, EBUSY at the open and EIO at the read: the start commits the engine's entry and keeps the pair, so a fix that
keeps the pair only while the engine names no reference fails (W-b4 reconciles as the base does when it names one).
The engine-key row has the engine store a key during an unreadable session, as an engine that runs does: after the same
two crashes, three unreadable starts ten years apart fail with EACCES at the stat, EBUSY at the open and EIO at the read,
the engine saves a staged entry during the first one's session and the next two commit it, so the pair to keep is
older than a committed entry. Each start keeps the pair, so a fix that keeps only the staged entries at least as new as
the newest committed one fails (W-z).
The orphan row runs the same four unreadable starts before its readable one, so a fix that holds an unreferenced
staged entry for good once it has outlived a run of up to four unreadable starts fails too (W-q holds it after two).
The orphan-codes row runs each of the seven codes at the stat, the open, the read and the directory, at two
unreadable starts in a row, ten years apart, each code and point on a fresh copy of the orphan row's crash, before a
readable one ten years after the second, so a fix that holds an orphan pair for good on some code or at some point
fails too (W-j2 holds it on EPERM, W-j4 holds it when the directory fails, with any code, taken for another instance
mid-replace in a locked directory). The tombstone row fails its unreadable start at the stat. The tombstone-at-each-point row runs each of
the seven codes at the stat, the open, the read and the directory, each start on a fresh copy of a tombstoned pair
beside a staged entry the engine names, signed out (a sign-out's removals failed) and beside a committed account (a
refresh's removals failed), so no such start meets a vault an earlier start reconciled: each deletes the tombstoned
pair and commits the engine's entry. So a fix that spares tombstoned entries, or leaves the engine's entry staged, at
some point or on some code fails (W-b3 spares them after a failed open or read, W-b6 skips the reconcile on EIO).
The two vault-state rows build what an unreadable start must still delete in every vault state the rows build beside
an unreadable file: beside no committed entry (signed out) and beside the old committed pair, a tombstoned pair (a
sign-out's or a refresh's removals that failed), an orphan pair (a sign-in that crashed after staging, before its
file write) or both, each with and without a staged entry the engine names. In each of the twelve states three
unreadable starts, ten years apart, fail with EACCES, EBUSY and EIO at the stat, the open and the read in turn (the
first point moving on from one state to the next): each deletes the tombstoned pair, commits the engine's entry and
keeps the committed pair, and the readable start after them deletes the orphan pair. So a fix that spares what must
go only in some of those states fails (W-j3 holds an orphan pair for good only beside no committed entry, W-b5 spares
tombstoned entries only beside a committed one).
The two keep-side vault-state rows build what an unreadable start must keep in every vault state the rows build
beside it: a replace that crashed before its pair's first commit, so the file names a staged pair, beside no committed
entry (a sign-in after a sign-out) and beside the old committed pair (a refresh of it), each with and without a
tombstoned pair (that sign-out's or an earlier refresh's removals that failed), a staged entry the engine names and an
orphan pair (two staged entries nothing names, staged before the pair). In each of the sixteen states three unreadable
starts, ten years apart, fail with EACCES, EBUSY and EIO at the stat, the open and the read in turn, and beside an
orphan pair a second one is staged during the first unreadable start's session (a sign-in retried while the file
cannot be read, crashed before its file write), so the pair to keep is newer than one orphan pair and older than the
other: each start keeps the staged pair the file names and the old committed pair, deletes the tombstoned pair and
commits the engine's entry, and the readable start after them has the pair live and committed, nothing else left but
the engine's entry. So a fix that drops the keep only in some of those states fails (W-b7 drops it beside a
tombstoned entry). So does one that keeps only the newest two staged entries nothing names, as if only one replace were
ever in flight (W-k2).
The two keep-at-each-point rows run each of the seven codes at the stat, the open, the read and the directory at two
unreadable starts in a row, ten years apart, after each of the four crashes the table names (a first sign-in's and a
sign-in's in one row, the two refreshes' in the other), each code and point on a fresh copy of the crash, then a
readable start ten years after the second: each unreadable start keeps the pair and the readable one has it live and
committed. So a fix that drops the keep for some code at some point fails (W-y drops it when the directory fails
with any code but EACCES, taken for a lost volume). So does one that drops it at the second of two such starts (W-p3
drops it when the directory fails with a code other than EACCES at two starts in a row), which the lasting row meets
only for EACCES at the directory, EACCES at the open and EIO at the read.
The two point-pair rows run seventeen unreadable starts in a row on one data directory, a year apart, whose points run
through every ordered pair of the stat, the open, the read and the directory (each pair once, in the order stat, stat,
open, stat, read, stat, dir, open, open, read, open, dir, read, read, dir, dir, stat), the code moving on through
EACCES, EBUSY, EIO, EPERM, EMFILE, EINVAL and UNKNOWN at each start, then a readable start a year after the last.
After a first sign-in's crash before commit 1 and a refresh's before commit 4 each unreadable start keeps the pair and
the readable one has it live and committed; after the orphan row's crash each keeps the committed account and the
readable one deletes the orphan pair. So a fix keyed on the point the start before failed at fails (W-p4 drops the pair
when the directory fails right after a start that failed at the file, taken for a swapped volume; W-j6 holds an orphan
pair for good then, taken for another instance that took the directory over).
The two start-sequence rows (review loop 15) do not write their shapes row by row: they generate them. After a first
sign-in's crash before commit 1 in one row and a refresh's before commit 4 in the other, each runs 127 events on the
data directory, a year apart, in a de Bruijn order of five events that holds every ordered run of three of them once: an
unreadable start, a readable start, and three sessions in which the file reads again (a new store on the data directory,
whose open() reads the file), each ending in a crash: a sign-in before its new pair's first commit (the file names the
pair, both entries staged), a refresh of the account the file names before its new pair's second commit (the file names
the pair, one entry committed and one staged), and a sign-in after staging its pair, before the file write (an orphan
pair). A session runs in the test's own process, as the first session does (it loads the subject afresh); every start
runs in a process of its own. The unreadable starts' codes move on through the seven and their points through the stat,
the open, the read and the directory; a readable start comes a year after the last event. After each unreadable start
the pair the file names is in the vault in the states the crash left, files and all, and the file is as it was; after
each readable start that pair is live and committed and nothing else is left. So a fix whose rule builds its state at
one start and reads it at a later one fails when a run of three events breaks the rule (W-C1 marks the staged entries an
unreadable start keeps and, at a later unreadable start that finds marked ones, keeps only those: a pair a session
staged and wrote to the file since then is deleted, which every other row misses, as each stages the pair to keep before
the first unreadable start).
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

## What the pack is and is not expected to catch

The journey test is a sample of the journey, not a proof that a fix is right. It is expected to catch a wrong fix
whose rule, in the states the rows build, deletes what an unreadable start must keep, keeps what a start must delete,
or keeps in another state or without the encrypted files: whether the rule turns on the errno code, the point the read
failed at (and the one the start before failed at), the number of unreadable starts in a row (up to seventeen), the
order of the starts and sessions before it (every run of three of the start-sequence rows' five events), the
pair's age by any clock the start's process
moves, the vault's committed entries (one newer than the pair to keep among them), the engine's references, the file's being refused or missing, or a second read
of the file, or a question about it (`existsSync`, `stat`), through `node:fs` or the module loader in the start's own
process. What an unreadable start must still delete (a tombstoned pair, an orphan pair) and what it must keep (the
staged pair the file names, the old committed pair, the engine's entry) are each built in every combination of the
vault states the rows build beside an unreadable file (the vault-state rows and the keep-side vault-state rows), so a
rule keyed on one of those states is reached, and the tombstone and the pair to keep each meet every code at every
point (the tombstone-at-each-point and keep-at-each-point rows), as the orphan pair does beside a committed account (the
orphan-codes row). Each such wrong fix the reviews named is in `WRONG-FIXES.md` with the
row that catches it.

It is not expected to catch a wrong fix whose rule turns on something the rows hold fixed or never build: the
inputs below, and any other the rows hold fixed. The list names the ones the reviews found; it is not a claim that
it is complete, and a wrong fix keyed on an input it does not name may pass.

Review has found new wrong fixes that pass the journey test round after round: fourteen of the fifteen review rounds of
calibration run 4 so far found at least one (the eleventh three: W-b6, W-l5, W-b7; the twelfth two: W-y, W-z; the
thirteenth three: W-j4 and W-p3, caught once two rows were changed for them, and W-j5, which passed every row until the
start-sequence rows; the fourteenth three: W-k2, W-p4 and W-j6, caught once two rows were changed and two added for
them; the fifteenth one: W-C1, caught once the two start-sequence rows were added for it, which catch W-j5 too), and
each was caught only once a row or the fault was changed for it, but for the ones the limits name. Expect more. The pack is a sample of wrong fixes and of the journey's states, not
a proof: a fix that passes it has met every row, not been shown right, and the grade says no more than that.

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
  Node the subject runs (24) without a flag. The file system's clock is not moved either: a file the start creates or
  writes gets the real time, and only the files already in the data directory are moved back. Those times are moved
  against each other, not against a time a file stores, so a fix that ages the pair by a new file's time against the
  `Date` value the vault stored at the crash (`createdAt`) passes (W-v), although ten years on the pair is deleted. Nor
  is a `Date` the start's process makes in a new `vm` context (each context has its own, unmoved), nor any other
  clock the start's process reads beyond the ones the journey names: the diagnostic report's timestamps
  (`process.report`), a worker thread's `Date` and the like. So a fix that ages the pair by one of them passes (W-u7
  takes the time from the report's `dumpEventTimeStamp`), although ten years on the pair is deleted. The pack moves
  the clocks it names, not every clock a process can read.
- **Forms of the rows that guard what an unreadable start still deletes and keeps.** Every code at every point meets
  a tombstoned pair and an engine's staged entry on a fresh vault (the tombstone-at-each-point row), but only in that
  row's two states (signed out, and beside a committed account, neither with an orphan or a pair to keep). In the
  vault-state rows of both kinds only the first of a state's three unreadable starts meets a tombstone or an
  uncommitted engine entry, and it fails with EACCES (at one of the three points). So a fix that spares tombstoned
  entries or leaves the engine's entry staged on some other code only in some other vault state (beside an orphan
  pair, say) passes. Neither kind of vault-state row asserts what an unreadable start does with the orphan pair, only
  that the readable start after it deletes it, and the keep-side rows build the pair to keep only as a crash before
  its first commit leaves it (not before its second, nor after staging, before the file write). The keep-at-each-point
  rows build it after each of the four crashes at every code and every point, but beside nothing else the crash leaves
  (no tombstoned pair, orphan pair or engine entry). The orphan pair meets every code at every point only beside a
  committed account (the orphan-codes row); beside no committed entry (signed out) it meets EACCES, EBUSY and EIO in
  the vault-state rows, and in the start-sequence rows the codes and points their order gives it (a session's sign-in
  after another's tombstones the committed pair and leaves the earlier session's pair staged, unnamed, beside no
  committed entry). So a fix that holds an orphan pair for good on some code at some point only beside no committed
  entry passes when the order does not give it that code there. W-j5 (it holds one on EPERM only while the vault holds
  no committed entry: W-j2's rule and W-j3's together) passed every row until review loop 15; both start-sequence rows
  catch it, and it is in `WRONG-FIXES.md`.
- **The directory beyond its reads.** At the directory only the reads fail; a write into the account file's directory
  still succeeds, where under a real directory that may not be searched it fails too. A copy of the refs kept outside
  that directory (beside the vault, say) stays readable, so a fix that keeps the refs such a copy names passes; it is
  right while the copy agrees with the file.
- **Functions the fault leaves out.** The writes (`writeFile`, `rename`, `unlink` and the rest) succeed on the
  faulted file at every point, as the fault is on reads, so a fix that probes the file by writing to it passes where
  a real permission may deny the write. `watchFile` and `unwatchFile` are not failed (a failed stat reaches a
  `watchFile` listener as zeroed stats, not as an error, and the fault does not forge them), and `glob` lists names,
  which the fault leaves readable. At the stat the fault answers `existsSync` false, as a real one is under a
  directory that may not be searched (the cause of a failed stat on POSIX); under a Windows permission on the file
  alone a real `existsSync` may still be true.
- **Reads outside `node:fs`.** The fault is on `node:fs` and the module loader in the main thread of the start's own
  process. Any API outside that layer that reads the file is not failed: a child process, a worker thread, a native
  addon, WASI, Node's internal bindings, or a built-in that reads a file by its own route (`process.loadEnvFile` reads
  it at every point, say). So a fix that learns the pair's refs that way, or only whether the file reads, and keeps on
  what it learns passes, although on a real unreadable file that read fails too and the pair is lost.
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
  state of the vault (two accounts' committed entries, say, or a staged entry the engine names) passes. Beside an
  unreadable file the rows put no committed entry or the old committed pair, with or without a staged entry the
  engine names (the vault-state rows build each with a tombstoned pair, an orphan pair or both, and the keep-side
  vault-state rows each with a pair to keep, with or without either), and the engine-key row a committed entry newer
  than the pair to keep (the engine's key stored during an unreadable session); other states (two accounts' committed
  entries, two tombstoned pairs, say) are not built. Beside the pair to keep the keep-side vault-state rows put one
  orphan pair staged before it and one staged after it, no more, so a fix that keeps only the newest four or more
  staged entries nothing names passes (with the engine's entry, which the engine names, not among them).
- **Runs of more than seventeen unreadable starts.** The point-pair rows run seventeen in a row (the unreadable-run row,
  the lasting row and the orphan row four), so a fix that keeps the pair through seventeen such starts and drops it at
  the eighteenth passes, and so does one that holds an orphan pair for good only after eighteen. The same failure, code
  and point, comes at four starts in a row only in the lasting row (EACCES at the directory, EACCES at the open, EIO at
  the read); the keep-at-each-point rows and the orphan-codes row run it at two starts in a row at every other code and
  point, so a fix that drops the pair, or holds an orphan pair, only at the third such start in a row there passes. The
  point-pair rows meet every ordered pair of the four points at two starts in a row, each pair with the two codes the
  order gives it: not every pair of codes, and no ordered triple of points. So a fix keyed on the codes of two starts in
  a row, or on the points of three, passes when its pair or triple is not one the rows meet (review loop 14 RL14-P2
  closed the pairs of points; the codes and the triples are left).
- **Sequences of starts beyond runs of three.** The start-sequence rows hold every ordered run of three of their five
  events, and runs of four or more only as their one order happens to hold them (124 of the 625 runs of four), so a fix
  keyed on four or more events in a given order passes when its run is not one the order holds. What the generator does
  not reach: each session is a new store that reads the file, never the unreadable start's own store going on; a session
  runs in the test's process, so what an earlier session kept there (on `globalThis`, say) reaches it, though never a
  start; a session's sign-in crashes only before its first commit or after staging, its refresh only before its second
  commit, and none runs to the end; no session puts an engine entry or a tombstone in the vault; and the codes and
  points move on with each unreadable start, not with the run it is in (27 unreadable starts, 27 of the 28 pairs of code
  and point), so a fix keyed on a code or a point at some place in a run passes when the order does not put it there.
  Its 127 events run on one order, the same at each run of the test.
- **Time limits beyond ten years.** The later starts run ten years after the crash (in the start-sequence rows a year
  after the event before, the pair kept at an unreadable start there at most seven years old), so a fix that drops a
  kept pair only once it is older than that passes.
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
