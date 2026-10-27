# sr-kit-cases, lead integration 7: every path string proved by file identity to name the file it came from (LC6-1, the class)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of e62541d (lead integration check 6, FIX).
The owner's decision of 2026-10-26 for LC6-1 was "fix by identity, then pack": close the class behind LC6-1, not only
the trailing-newline instance. The change is one commit through the pre-commit hook. This report is part of that
commit, so it cannot name its own sha (the returned gist does).

**Verdict: DONE.** The class is closed in `historyless-checkout.sh`: wherever the script turns a path into a string
and then checks that string or hands it on (to the native layer, to git, to the removal), it first proves, by file
identity, that the string still names the file it came from, and refuses the path when that fails or cannot be
proved. Keeping trailing newlines alone was not enough, and is not what the fix relies on: the strings that name
something that does not exist yet (the checkout and a link's parent) keep their exact spelling, and every string that
names an existing file is proved.

The class turned out wider than check 6's reproduction. Besides LC6-1 itself (a trailing newline dropped by a command
substitution), the same defect has a second source on Windows: Win32 drops a trailing space or dot from a path's last
segment, so a string the shell reads literally names another file to every native program. I found and closed these
instances:

| # | Instance | At e62541d | Now |
|---|---|---|---|
| 1 | a link at DIR's top to `x/repo<LF>` (a work tree) beside a free `x/repo` (check 6's LC6-1), `sys` and `.lnk` | accepted; `cd node_modules/s && git log` reads the work tree's history | refused, shell layer |
| 2 | a link to a file in it, `x/repo<LF>/brief.md` (the `$(dirname)`/`$(basename)` join) | accepted; the brief is readable | refused |
| 3 | a link to a link `x/t<LF>` that leads into another repository (the `$(readlink)` hop) | accepted; that repository's file is readable | refused |
| 4 | DIR itself `x/repo<LF>` (`$(pwd -P)`) | accepted, checked and linked as the twin | refused |
| 5 | `--pack pk<LF>` with the target inside it | refused only by luck of the spelling ("inside the pack" `pk`) | refused: the pack's string is not proved |
| 6 | a target whose nearest existing parent is `x/p<LF>`, a link into a repository | made inside that repository | refused: inside the git repository |
| 7 | `--link a<LF>=hostdir --link a<LF>/x=dep2` (LC5-3's link-parent check) | the second link made in the host directory | refused: not inside the checkout |
| 8 | DIR `x/gs ` (trailing space), a volume-GUID link into a repository, beside a free `x/gs` | accepted: the native layer checked `x/gs` | refused, native layer |
| 9 | a `sys` link at DIR's top to `x/gs ` | accepted | refused, native layer |
| 10 | an entry `s ` at DIR's top (a GUID link into a repository) beside a free entry `s` | accepted; the repository is readable | refused, native layer |
| 11 | a target under `x/gt ` (a GUID link into a repository) | git failed late ("Invalid argument") | refused, native layer, nothing made |
| 12 | a target `tw/co ` beside a host directory `tw/co` | **git init and reset --hard wrote the base tree into the host's `tw/co`** | refused, native layer; `tw/co` untouched |
| 13 | the same with a `--link` (the removal path) | **the removal was aimed at the host's `tw/co`** ("could not remove") | refused; `tw/co ` removed by its literal spelling, `tw/co` untouched |
| 14 | a source `x/rs ` (empty) beside a twin `x/rs` that is a clone | git read the twin's objects | refused, native layer |
| 15 | a target whose last segment is `.` or `..` (`host/nx/..` is `host`) | git init and reset --hard ran in `host` | refused before anything is made |
| 16 | a target `n<LF>/m<LF>/cand<LF>` (control: a new name may hold newlines) | made at the stripped `n/m/cand` | made exactly where spelled |

Each row was run against both scripts in fresh scratch directories (rows 1-14 and 16, each with and without
`--pack` where it applies, 40 result lines per script; row 15 separately), all verified:

- At e62541d: rows 1-4 and 8-10 exited 0 with the forbidden content reachable through the made link (another
  repository's commits or files, or the free twin instead of the named directory); row 6 exited 0 and made the checkout
  inside `other/sub`, a work tree; row 7 exited 0 with `--pack` and made `x` in the host directory; rows 11 and the
  middle-space control failed late in git (exit 128, "Invalid argument"); row 12 exited 0 with `tw/co` now holding
  `.git`, `README.md` and `a` beside the host's `host.txt`; row 13 exited 1 ("could not remove"), its removal aimed at
  the host's `tw/co`; row 14 exited 0 (git read the twin); row 15 exited 0 with `.git` and `README.md` written into
  the host directory; row 16 exited 0 with the checkout made at the stripped `n/m/cand`, not the exact name.
- Now: rows 1-15 exit 2 with nothing made and the host directories unchanged (row 7: "not inside the checkout"; row 6:
  "inside the git repository"; rows 4 and 5: "is not proved to name the file it came from"; the rest name the layer
  that refused); row 16 and the free controls exit 0, made exactly where spelled; the middle-space control exits 2 and
  leaves nothing behind.

## The fix

All in `tools/calibration/historyless-checkout.sh`.

**Shell layer.** `[ a -ef b ]` (same device and inode, each followed to the end of its links, as `stat(2)` does) is
the proof:

- `phys` and `physd` (`$(pwd -P)`): the physical path must be `-ef` the directory it was asked for, else status 3.
  `cd`'s own output is dropped too, so a `CDPATH` match cannot slip in as the path (it would fail the proof anyway).
- `resolve`: each join of the physical directory and `$(basename)`, and each `$(readlink)` hop, must be `-ef` the link
  it replaces, else status 3.
- `ancestors`: the Windows spelling (`cygpath -m`) of an existing path must be `-ef` the path, else status 3. A mount's
  Windows spelling is the same directory under other parents, so a real mount passes; one that names another
  directory is no spelling of the path, and its parents say nothing about the path's.
- `add_native` (now one function for every item: S, P, L, E, T, C, K): the Windows spelling handed to the native layer
  must be `-ef` the shell's path, else refused.
- the removal (`discard`): the Windows spelling of `MADE` must be `-ef` `MADE`, else "could not remove" (exit 1) and
  nothing is removed.
- A status 3 is reported by `unproved` as "WHAT is not proved to name the file it came from: ... (LC6-1)", so a refusal
  says which string failed; other failures keep their old messages.
- The strings that name something not made yet are spelled exactly: `spell_dir`/`spell_base` print a sentinel after
  `dirname`/`basename`, so the substitution drops only the sentinel's newline. They are used for TARGET's parent and
  name, each missing parent segment, and a link's parent in the checkout. TARGET's last segment may not be `.` or `..`.

**Native layer.** `final()` keeps resolving each string with `os.path.realpath(strict=True)`, and now also proves
that what it resolved is, by file identity (`os.path.samestat`: the volume serial number and the file id), what the
string's literal spelling (`\\?\` + the path, which Windows reads as it is, dropping no trailing space or dot) names.
A string with no drive letter, or one whose two readings differ, is refused. `--discard` removes the literal spelling.

**Git.** Git is a native program, so it reads a string the way the native layer does. It is now given only proved
strings: the source as the S item's proved Windows spelling (the S item now always runs, not only with `--link`), and
the checkout as the C item's, after the shell has made the checkout directory itself (`mkdir` of the exact spelling)
and the native layer has proved it. Before, `git init` made the checkout at its own reading of the string, which is
how the base tree was written into the host's `tw/co`. A failing `git init` (Git for Windows refuses any path segment
that ends in a space or dot, "Invalid argument") now removes what was made and refuses (exit 2), instead of leaving
it behind under `set -e`. Handing git only Windows spellings also makes the script work when the host turns off MSYS's
argument conversion (`MSYS_NO_PATHCONV=1`): before, git took `/c/x` as `\c\x` on its current drive and the source
lookup failed (verified at e62541d: "cannot change to '/c/...'"; at the fix the checkout is made).

## Tests: red first, then green

Three new tests in `tools/test_calibration_kit.py` (the suite runs 138, was 135), and one changed:

- `proves_each_path_string_names_the_file_it_came_from` (shell layer, trailing newline): check 6's reproduction (a
  `sys` and a `.lnk` link at DIR's top to `x/repo<LF>` beside a free `x/repo`) and rows 2-7, 15 and 16 of the table,
  each with and without `--pack`; a source `srcnl<LF>` beside a clone `srcnl` is refused, not read as the clone.
- `proves_native_programs_read_each_path_string_as_the_same_file` (native layer, trailing space): rows 8-14, with
  the host's `co` checked byte for byte after each run and `co ` removed by its literal spelling.
- `proves_each_windows_spelling_it_hands_on` (the strings handed to the native layer, to git and to the removal): a
  stub `cygpath` that spells the checkout, or the source, as another directory (a host directory, or a clone) is
  refused as unproved, nothing is made, written or removed in the other directory, and the source is checked with no
  `--link` (the S item always runs); and the script, run from a `subst` drive's root with `MSYS_NO_PATHCONV=1`, makes
  the checkout (one commit) and writes nothing on that drive.
- `walks_the_windows_parents_of_a_mounted_directory` (changed): the stub `cygpath` used to give Windows spellings that
  named other, unrelated directories; a real mount's Windows spelling is the same directory, so each spelling is now
  a junction to `mnt/deps` (the same directory, which the identity proof accepts), and each refusal the test asserted
  is still asserted. Two new cases give a spelling that names another directory, a free one and one inside a
  repository: walked, the first was accepted and the second refused for the other directory's repository; both are
  now refused as unproved. This is a fixture made truthful, not a check weakened: every reason asserted before is still
  asserted, with `--pack` and without.

Red first, verified: the four tests, run against e62541d's script (the rest of the tree at the fix), fail, each at its
first case (0 != 2: the e62541d script made the checkout). On the fix all four pass (the mutation control below runs
them with the 20 other tests the mutants target: 24 tests, 0 failures).

## Guard-removal proofs

**Earlier mutants.** I re-applied all 70 of rounds 4 and 5 to the fixed script, each on the tests its earlier result
names, and the 19 of round 6 (the lead's 17 and check 6's W2 and W4) on the 24 tests the mutants target: round 6's
new or changed tests and this round's four.

- 41 of the 70 applied with `patch -F0` (line offsets only); 13 whose context my additions changed were applied as one
  exact replacement of the hunk's removed lines; 16 whose own lines this round rewrote (for example `cd -P` in `physd`,
  each `ancestors` call site, the native items, `git init`) were ported: the same guard removed from the new line.
- Result: 69 of 70 give exactly the same red set as before (verified). **RH** (no `HEAD` in the repository test) gave
  its old red test and also the native-layer test, which failed on a process that died with no output (exit
  2147483652) while four mutants ran in parallel. Rerun alone on the same mutant, that test passes (verified), so RH's
  red set is its old one; the extra failure was the load, not the mutant.
- Round 6's 19: 18 red on the tests they were red on before (V1 and W2 now on the native trailing-space test too; D1,
  D2, D3 and W4 on new tests too, since a refusal there must remove a checkout it made). **O4** is green again,
  equivalent for round 6's reason: `nullglob` only drops a pattern that matches nothing, a word the loop skips anyway,
  and no other line depends on it (my reading, expected).
- The control (the fixed tree on the union of all those tests: 24) is green (verified).
- The mutants ran on the script before its last two edits, which changed only comments (the header's list of what
  the native layer checks, two lines rewrapped) and one docstring (see Checks); `diff` shows no other line changed
  (verified).

**New mutants**, one per identity check and per exact spelling, each on the 24 tests:

| Mutant | What it removes | Result |
|---|---|---|
| I1 | `phys`'s proof (`$(pwd -P)` `-ef` DIR) | red: newline test |
| I2 | `physd`'s proof | red: newline test |
| I3 | `resolve`'s proof of the `$(dirname)`/`$(basename)` join | red: newline test |
| I4 | `resolve`'s proof of each `$(readlink)` hop | red: newline test |
| I5 | `ancestors`' proof of the Windows spelling | green at first; red after a test case was added (below): mount test |
| I6 | `add_native`'s proof of the Windows spelling it hands on | red: Windows-spelling test |
| I7 | the native proof (`samestat` of the literal and the resolved path) | red: native trailing-space test |
| I8 | the removal's proof of `MADE`'s Windows spelling | red: Windows-spelling test |
| I9 | the native removal by the plain string, not the literal one | red: native trailing-space test |
| S1 | TARGET's parent by `$(dirname)` | red: newline test |
| S2 | TARGET's name by `$(basename)` | red: newline test |
| S3 | each missing parent segment by `$(basename)` | red: newline test |
| S4 | the next existing parent by `$(dirname)` | red: newline test |
| S5 | a link's parent in the checkout by `$(dirname)` | red: newline test |
| S6 | TARGET's last segment `.` or `..` allowed | red: newline test |
| G1 | git given the shell's spelling of the checkout | red: newline and Windows-spelling tests |
| G2 | git given the shell's spelling of the source | red: Windows-spelling test (the `MSYS_NO_PATHCONV` case) |
| G3 | `git init` makes the checkout (no `mkdir` of the exact spelling first) | red: every test that makes a checkout |

**I5 survived the first run, and was not equivalent.** On Windows every string `ancestors` proves is then handed to
the native layer, and `add_native` proves the same `cygpath -m` spelling, so with I5 the mount test's free spelling
was still refused as unproved, one step later. But in between, `ancestors` walked the unproved spelling's parents: when
those hold a repository, the refusal names that repository, which is not the directory's. And on a host with `cygpath`
but no native layer (the mount test's stub on Linux), `ancestors`' proof is the only one (expected, not run here). I
added a case to the mount test: a Windows spelling that names a directory inside a repository must be refused as
unproved. With I5 it is refused as "inside the git repository" of the other directory, and the test fails (verified:
I5 and I6 rerun with the control, I5 red on the mount test, I6 red as before, the control green on the 24 tests).

## IC4-1 and LC5-1, against the read-only MoonAliza clone

The round-6 reproduction (IC4-1 and LC5-1: a `--link node_modules` that leads, by a direct path, a volume-GUID link,
a `\\?\GLOBALROOT` link, a chain, a junction, a link at the top of DIR of each kind, and `sys`/`.lnk` symlinks through
a GUID path or a `subst` drive, into the read-only MoonAliza clone's `node_modules`), rerun against the final script,
each of the 12 variants with and without `--pack` (24 runs), verified:

- all 24 exit 2 with nothing made; the clone's `git status --ignored` is the same before and after;
- the 2 direct runs are refused by the shell layer ("is inside the git repository"); the 8 GUID, GLOBALROOT, chain and
  junction runs by the native layer ("as native programs resolve it ... is inside the git repository"); the 6 links at
  DIR's top and the 8 `sys`/`.lnk` symlinks through a GUID path or a `subst` drive as links whose target, as native
  programs resolve it, is inside the repository. None is refused for an unproved string: the identity proofs do not
  change how a real link is judged;
- the exit code and the refusing layer of every run are the same as round 6's (`cut -f1-4` of both logs is
  identical). Nothing was written in the clone.

The LC5-1 test (`checks_where_a_link_only_the_shell_sees_leads_as_native_programs_resolve_it`) passes alone on the
final script (verified).

## Behaviour changes a host can see

- A source, pack, DIR or target parent whose name ends in a newline is refused: `$(pwd -P)` cannot spell it, so it
  cannot be proved (fail closed). A checkout name with newlines is made exactly as spelled.
- A path whose last segment ends in a space or dot, where it is checked natively, is refused (Windows reads it as
  another name). A link at DIR's top to a literal `name ` directory is refused for the same reason, even when it is
  free: a false refusal, by design.
- A target whose last segment is `.` or `..` is refused.
- A checkout whose path has a segment ending in a space or dot is refused once made (git cannot hold it), and removed.
- The source is always checked natively (before only with `--link`).

## Observations, not fixed (out of this round's scope)

- `-ef` proves the same file, so a hard link to a file (another name for the same file) passes it. A link at DIR's
  top to a file is followed to its directory's physical path, and a directory cannot be hard-linked, so this changes
  no check; noted for completeness.
- `mkdir -- "$TARGET_ABS"` after the checks: if another process makes TARGET in between, `mkdir` fails and `set -e`
  ends the script (exit 1) with the made parents left behind. That is a race with the host's own processes, outside
  this class.
- The native layer proves only each string's final segment. Windows keeps a trailing space or dot in a middle
  segment, so a middle segment cannot be read as another name; the only effect is a false refusal (verified with
  `x/ms /co`: git refuses it, the script now removes what it made and refuses).
- OBS-1 stays out of scope, as the brief says.

## Checks

- **Rendered prompts:** `run.template.js` is untouched this round (it differs from 09b476d only in a comment, since
  bea034a). Rendered through the test module's `run_config`/`execute_template` with `GOLDEN_HOST`, at 09b476d and at
  the working tree, for the fixture and shared manifests, each with `cause_in_prompt` absent, true and false, every
  call compared as sorted JSON: **60 calls, 0 differ**; the `fix:alpha-low` prompt sha256 prefixes are
  `5e66cf5f4d0c141c` (fixture) and `54a0353d503c950d` (shared), the `FIX_PROMPT_GOLDEN` values (verified).
- **Full kit suite:** `python -W error::SyntaxWarning tools/test_calibration_kit.py` with
  `MSYS=winsymlinks:nativestrict`: 138 tests (135 before, three new), 0 skipped; 137 passed and one failed: the kit
  hygiene scan found a drive-letter spelling (its "Windows drive path" rule) in the docstring of the native layer's
  new `drive()`. I reworded the docstring (no code changed) and the hygiene tests pass (verified). The pre-commit gate
  runs the whole suite again on the committed content.
- **Evidence check:** `check_calibration_evidence.py`: 3 folders, 0 failures, 14 limitations, as before (verified).
- **Secrets:** `check_secrets.py` clean (0 hits); `check_credential_hygiene.py` clean, 0 new findings (verified).
- **Hygiene:** every changed file is LF (`git ls-files --eol`); `bash -n` passes on the script; the diff adds no
  absolute host path, session or run id, or model name (verified).
- **MoonAliza clone:** read only; nothing was written in it (its `git status --ignored` is the same before and after).

**Untested or expected:**

- Hosts other than this Windows 11 / Git Bash one (expected): on Linux and macOS the shell proofs are the same, and
  `-ef` is POSIX; the native layer and the Windows spellings do not exist there. A trailing space or dot is an
  ordinary name there, and the shell reads it as one.
- A host that turns off MSYS's argument conversion was tested from a `subst` drive's root; other current directories
  follow the same rule (expected).

## What I got wrong and fixed

- I edited the script while a test run was reading it. Bash reads a script as it runs, so that run's results meant
  nothing; I discarded them and reran, and touched no file under `tools/` again while tests or mutants ran.
- The new tests first wrote the host's `host.txt` with `write_text`, which on Windows writes CRLF, and then compared
  it byte for byte with `HOST\n`: the asserts failed on the fix for a reason of the test's own. They now write bytes.
  The first mutation run had already started with those tests, so its results for them were void: I stopped it and
  reran every mutant those tests decide (the second run, below), keeping only the first run's results for mutants
  the changed tests do not take part in.
- I first expected a source `srcnl<LF>` (no twin) to be accepted. It is refused, rightly: `$(pwd -P)` cannot spell a
  name that ends in a newline, so the proof fails closed. The test now expects the refusal and adds a clone `srcnl`
  beside it, so it also shows the clone is not read in its place (a stronger check, not a weaker one).
- The native test's cleanup could not remove git's read-only object files; it now makes each writable before removing
  it, still by the literal spelling, so `gs ` is removed as `gs ` and never followed.
- `cygpath`'s stub in the mount test gave Windows spellings that named other directories. With the identity proof
  those were refused as unproved, not walked; a real mount's spelling is the same directory, so I made the fixture
  truthful (junctions to the same directory) and added the unrelated-directory case as its own refusal (see above).
- Two mutants (git given the shell's spelling of the source or of the checkout) survived my first test set: on this
  host MSYS converts `/c/x` for git, so the spelling made no difference. I added the `MSYS_NO_PATHCONV=1` case, where
  it does; at e62541d that case fails ("cannot change to '/c/...'"), at the fix it passes.
- Mutant I5 (`ancestors` without its proof) survived my tests: on this host the native items prove the same strings
  next, so the refusal still came. I had not tested what the refusal says when the unproved spelling's parents hold a
  repository; the mount test now does, and I5 is red.
- My new `drive()` docstring spelled a Windows drive path, which the kit's hygiene scan forbids; the full suite caught
  it, and I reworded it.
- Scratch only, nothing committed: my first MoonAliza run used a relative scratch path, which broke the run's own
  `GIT_CONFIG_GLOBAL`; I reran it with absolute paths. A reproduction target named `coN` is the reserved device name
  `CON` on Windows (names are case-blind); I renamed it.
