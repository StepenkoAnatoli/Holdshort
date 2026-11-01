<!-- Lineage: the wrong-fix matrix of calibration run 4 stage 4a (the lead's decision H1): written before the accepted journey test was settled, one row per wrong fix the lead and the builder named, each graded through grade.sh fix by tools/test_calibration_kit.py (HostPackX21). -->

# Wrong fixes of X2-1, and the row of the accepted journey test that catches each

Each wrong fix is applied as a candidate's change on a history-less checkout of the base (`base0`): its source edits,
the wiring a candidate would write for it in `src/main/index.ts` (except W-i, which leaves it out), and the candidate's
own red-first test `tests/x2_candidate.test.ts` (a first sign-in that crashed before its first commit, then a start that
cannot read the account file). Every one is green on its own tests at its head, red with the three source files
restored to the base, in scope and eslint-clean, so the grade turns on the accepted journey test alone. W-c also
drops the shipped crash-window row its idea contradicts (a crash after staging, before the file write, whose orphan pair
the next start deletes; `X21_TEST_EDITS`), as a candidate that takes its change for the rule would. The edits live in
`X21_WRONG` of `tools/test_calibration_kit.py`; the row ids here are its keys (a test checks the two agree), and the
letters follow the lead's list (H1), with W-b2, W-i and W-j added by the builder, W-k and W-l by review 1, W-m and W-n by re-review 1, W-o2 by review loop 1 and W-p and W-q by review loop 2.

The pin rows are the tests of `zz_accepted_x2_1.test.ts`: the twelve **journey rows** (first sign-in before commit 1,
sign-in before commit 3, refresh before commit 3, refresh before commit 4, each with EACCES, with EBUSY and with EIO at
the next start, which comes ten years after the crash), the **tombstone row** (a sign-out whose removals failed, then an
unreadable start), the **orphan row** (a crash after staging, before the file write, then four unreadable starts in a row,
ten years apart, then a readable one), the **signed-out orphan row** (a sign-out, then a sign-in that crashed after staging, before
the file write, then a readable start of a file that names no account), the **refused-file row** (the signed-out
orphan row's crash, then the file replaced by one the store reads and refuses: invalid JSON, over 64 KiB, or with an
extra key, each in a start of its own), the **ENOENT row** (a first sign-in that crashed before any file existed), the
**app-changed row** (a file issued to another app, with an orphan
pair beside it), the **vault-default row** (the reconcile called with the references only) and the **unreadable-run row** (a
first sign-in that crashed before commit 1 and a refresh that crashed before commit 4, each followed by four starts in a
row that cannot read the file, with EACCES, EACCES again, EBUSY and EIO, each ten years after the one before, then a
readable start).

The grade column is what `grade.sh fix` returned on the pack built from MoonAliza 16f637f and 01a8604: `acceptedPin`
counts the accepted journey test's failed rows out of its 20.

| id | the wrong idea | the pin row that catches it | grade |
|---|---|---|---|
| W-a | retry the read once at `open()` before taking the file for unread | journey rows (all 12) and the unreadable-run row: the read fails for the whole start, so the retry fails too and the pair is deleted | FAIL: acceptedPin 13 of 20 red; candidate green, guard red, scope and lint ok |
| W-b | skip the whole reconcile when `open()` could not read the file | tombstone row: the sign-out's tombstoned pair survives and the engine's referenced staged entry stays staged (GS-11) | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-b2 | the keep flag spares tombstoned entries as well as staged ones | tombstone row: the tombstoned pair survives the unreadable start | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-c | keep every unreferenced staged entry on every start (the vault's default changed) | orphan, signed-out orphan, refused-file, ENOENT, app-changed and vault-default rows: no start deletes an unreferenced staged pair, whether the file was read, read as signed out, read and refused, missing or issued to another app, and the reconcile called with the references alone keeps them too | FAIL: acceptedPin 6 of 20 red; candidate green, guard red, scope and lint ok |
| W-d | `references()` returns the vault's staged refs during an unread start (a wider vault contract for the store) | journey rows (all 12), the orphan row and the unreadable-run row: the unread start commits the pair instead of leaving it in the crash's states, and commits the orphan pair the next readable start should delete | FAIL: acceptedPin 14 of 20 red; candidate green, guard red, scope and lint ok |
| W-e | commit unreferenced staged entries on an unread start | journey rows (all 12), the orphan row and the unreadable-run row: the pair is committed, not left staged, and so is the orphan pair, which the next readable start then keeps | FAIL: acceptedPin 14 of 20 red; candidate green, guard red, scope and lint ok |
| W-f | keep the staged entries on an unread start but unlink their encrypted files | journey rows (all 12) and the unreadable-run row: the pair's encrypted files are gone | FAIL: acceptedPin 13 of 20 red; candidate green, guard red, scope and lint ok |
| W-g | keep staged entries only while the vault holds no committed entry (the first sign-in's crash only) | journey rows sign-in before commit 3, refresh before commit 3 and before commit 4, and the unreadable-run row's refresh: the old pair is committed, so the new one is deleted | FAIL: acceptedPin 10 of 20 red; candidate green, guard red, scope and lint ok |
| W-h1 | set the keep flag from an unread file or `openedAppChanged()` | app-changed row: the orphan pair beside an account issued to another app survives | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-h2 | set the keep flag from "no account was read", so a missing file (ENOENT) keeps too | ENOENT row: the staged pair of a first sign-in that never wrote its file survives | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-i | the store and the vault changed, `src/main/index.ts` left calling the reconcile as before | journey rows (all 12) and the unreadable-run row: the startup statements `index.ts` runs never pass the flag | FAIL: acceptedPin 13 of 20 red; candidate green, guard red, scope and lint ok |
| W-j | an unread start marks the kept entries held, and no later start deletes a held entry | orphan row: the readable start after the unreadable ones leaves the orphan pair | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-k | keep an unreferenced staged entry on an unread start only while it is less than a day old (an older one counts as abandoned) | journey rows (all 12) and the unreadable-run row: the unread start comes ten years after the crash, so the pair is deleted as too old | FAIL: acceptedPin 13 of 20 red; candidate green, guard red, scope and lint ok |
| W-l | keep only when `open()` met EACCES or EBUSY (a lock or a permission error), not on any other I/O error | the four EIO journey rows and the unreadable-run row's EIO start: the pair the unreadable file names is deleted | FAIL: acceptedPin 5 of 20 red; candidate green, guard red, scope and lint ok |
| W-m | set the keep flag from an unread file or a file that names no account (a signed-out file may not list every reference); a missing file and an account for another app still delete | signed-out orphan row: the orphan pair a crashed sign-in staged after the sign-out survives the readable start | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-n | W-k's idea with a year for the limit (a staged entry a year old counts as abandoned) | journey rows (all 12) and the unreadable-run row: the unread start comes ten years after the crash, so the pair is deleted as too old | FAIL: acceptedPin 13 of 20 red; candidate green, guard red, scope and lint ok |
| W-o2 | set the keep flag whenever `open()` found no usable file but a missing one, so a file that was read and refused (invalid, oversized, an extra key) keeps too; narrower than re-review 2's probe W-o (an unread file or any startup write), it leaves an account issued to another app alone | refused-file row: the orphan pair beside the refused file survives the start that read it | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-p | keep an unreferenced staged entry through one start that cannot read the file and mark it kept; a second such start in a row takes a kept entry for abandoned and deletes it (W-k's limit counted in starts, not in age) | unreadable-run row: the second of the four unreadable starts deletes the pair | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |
| W-q | an unreferenced staged entry kept through two starts in a row that cannot read the file is taken for one the file still needs and held for good, so no later start deletes it (W-j's hold, earned by a run of unreadable starts) | orphan row: after its four unreadable starts the readable start leaves the orphan pair | FAIL: acceptedPin 1 of 20 red; candidate green, guard red, scope and lint ok |

The three correct fixes grade PASS: the accepted change (MoonAliza 01a8604's three source files, its two test files, the
wiring test and the map) and an alternative (the store's flag under another name, a positional vault parameter, the
wiring reading the flag), `X21_ALTERNATIVE` in the same test file, and a second alternative whose wiring calls a helper
the store's module exports and `index.ts` imports (an options object under another name), `X21_ALTERNATIVE_HELPER`.
