# sr-kit-cases, lead integration 4: every path checked as native programs resolve it, no git template, nothing made on refusal, no checkout inside a repository (LC3-1, LC3-2, LC3-3, LC3-4)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of 16ef0a5 (lead integration check 3, FIX).
The change is one commit through the pre-commit hook. This report is part of that commit, so it cannot name its own sha
(the returned gist does).

**Verdict: DONE.** All four findings of check 3 are closed in `historyless-checkout.sh`, each with a red-first test
and guard-removal proofs:

- **LC3-1 (S3), the class behind it:** on Windows, every path the guard reasons about is resolved again by a native
  resolver (a Windows Python's `os.path.realpath(strict=True)`, which goes through `GetFinalPathNameByHandle`), and
  every containment check and the `.git` walk run again on that resolved path. The layer fails closed: a path that
  does not resolve, one that resolves to anything but a drive-letter path, and a host with no native resolver are all
  refused. The shell checks of rounds 2-3 stay, and run first.
- **LC3-2 (S4):** `git init --template=`, and the final proof now compares every object the checkout's git can read
  (`cat-file --batch-all-objects`, which reads alternates too) with the base commit and its tree.
- **LC3-3 (S4):** every target check runs on the nearest existing parent before anything is made.
- **LC3-4 (S4):** a checkout inside any git repository is refused, in both layers, with the same walk `--link` uses.

The IC4-1 reproduction against the read-only MoonAliza clone is refused in all ten variants, and the clone is unchanged.

## LC3-1: the class, and why it is a class

Check 3 found one spelling (a symlink whose target is `\\?\Volume{guid}\...`). The class is wider: **any link Git Bash
cannot see but native programs follow.** For such a link, under Git Bash:

- `[ -L ]` is false, `readlink` prints nothing, and `cd -P link; pwd -P` keeps the link's own path;
- a dangling one still reads as `-e` and `-d`, but `pwd -P` fails on it.

Native programs (git, node, Python's `realpath`) follow it. Members I reproduced on this host:

- `\\?\Volume{guid}\...` (check 3's spelling);
- `\\?\GLOBALROOT\DosDevices\C:\...`;
- `\\?\GLOBALROOT\Device\Mup\localhost\C$\...`, which resolves natively to the UNC path `\\localhost\C$\...`;
- an ordinary symlink (which the shell does see) pointing at any of these: the shell resolves the first hop, then stops.

Adding one more shell spelling check per member would leave the next member open. So the fix asks the resolver
native programs use, for every path, and refuses whatever it cannot answer.

### The two layers, and what each covers

| layer | runs | resolves a path with | covers |
|---|---|---|---|
| shell (rounds 2-3, kept) | always, first | `cd -P` / `pwd -P`, hop-by-hop `readlink` for `-L` entries, `cygpath -m` for the Windows parents of a Git Bash mount, `-ef` for identity | every link the shell sees; mounts such as `/` and `/tmp` whose Windows parents differ; case and spelling differences; UNC spellings the shell shows (`//host/share`); the only layer on a non-Windows host |
| native (new, Windows only) | after the shell layer passes | a Windows Python 3.8+, run as `python -I -` with the paths as arguments in their `cygpath -m` spelling; `os.path.realpath(strict=True)` | every link of any kind native programs follow, including those the shell cannot see; a dangling link the shell reads as a directory; a link that resolves to a UNC path or a volume with no drive letter |

**What the native layer checks** (the same checks as the shell layer, on the resolved path):

- each `--link DIR`: not inside or holding the pack or the source repository (both resolved too), and not inside any
  git repository (the `.git` walk over the resolved path and all its parents);
- each top-level entry of DIR that is a link of any kind (`is_symlink`, or the `FILE_ATTRIBUTE_REPARSE_POINT`
  attribute, which also covers junctions): resolved and checked as DIR is;
- the target's nearest existing parent: not inside the pack (`--pack`), and not inside any git repository;
- the source repository and the pack themselves: they must resolve to a drive-letter path, or they are refused.

**Fail closed.** The native layer refuses:

- a path that does not resolve (`realpath(strict=True)` raises), such as a dangling GUID link at DIR's top;
- a path that resolves to anything but `X:\...`: a UNC path, or a `\\?\Volume{guid}\` path of a volume with no drive
  letter, whose parents the checks cannot walk reliably;
- every checkout, when no Windows Python 3.8+ is on `PATH` as `python3` or `python` (an MSYS2 or Cygwin Python is
  rejected by the probe: its `os.name` is `posix`, and it resolves as the shell does);
- every checkout, when the check itself fails (any exit but 0 or 2): "the native path check failed (exit N)".

Its refusals carry the phrase "as native programs resolve it", and the tests pin which layer refuses each case: a
shell-layer case asserts the phrase is absent, a native-only case asserts it is present. So removing a guard from one
layer cannot hide behind the other (the guard-removal proofs below show this for both layers).

**Why a Windows Python.** grade.sh already runs Python as `python3`, so the kit adds no dependency. Git Bash's own
tools all resolve as the shell does; `cmd /c` and PowerShell were the alternatives, but their quoting through MSYS2 is
fragile, and neither has a strict final-path call as direct as `realpath(strict=True)`. Paths go in as arguments with
`MSYS2_ARG_CONV_EXCL='*'`, so MSYS2 does not rewrite them, and the script is a quoted heredoc, the pattern grade.sh uses.

## LC3-2: no git template

`git init -q --template= -b BRANCH TARGET` copies no template, so neither `GIT_TEMPLATE_DIR` nor `init.templateDir` can
place `objects/info/alternates`, hooks or a description in the new `.git` (verified: none is created). The objects the
script unpacks are now computed once (the base tree and every tree and blob under it), and the final proof compares
that set plus the base commit with every object the checkout's git can read. `--batch-all-objects` reads alternates
too, so a borrowed object store fails the proof (exit 1).

With `--template=` in place the proof cannot be triggered by a test; it is defence in depth. The paired mutation below
shows it working: without `--template=` the test goes red on the proof's own message, and only with the proof removed
too do the borrowed objects stay readable.

## LC3-3: nothing is made on refusal

The target section no longer runs `mkdir -p` before its checks. It climbs from TARGET's parent to the nearest parent
that exists (refusing one that exists but is not a directory), and runs every check on that parent: the UNC check,
the pack check, the repository walk, and the native layer. Only then are the missing parents made. Because the missing
part is made as spelled, it may hold no `.` or `..` segment (refused: "spell it without '.' or '..'"); a missing
parent holds no link and no repository, so checking the nearest existing parent is exact.

## LC3-4: no checkout inside a git repository

**First, the STOP condition.** I checked that no test or documented flow places a checkout inside a repository: the
kit's tests (every target is under the test's own temporary root, which is checked to lie outside any repository), the
pack-4a tests on `build/sr-pack-4a` (targets under the test root), the kit README, the subject-pack READMEs,
`run.template.js` and the run 4 docs. None does, so no STOP.

The target's parent walk now runs `is_repo` over every ancestor, in both layers, and refuses "target T is inside the
git repository R; a checkout inside a repository reaches that repository's history and files through '..' (Item 2)".
This applies with and without `--pack`. The pack directory itself is not a repository (its `repo/` is), so a checkout
beside the pack's repository stays accepted.

## Files

- `tools/calibration/historyless-checkout.sh`: the native layer, the resolver probe, the target section, `--template=`,
  the object-set proof; the header's "How paths are compared" paragraph describes both layers and the fail-closed rules.
- `tools/test_calibration_kit.py`: five new tests, helpers for real volume-GUID, GLOBALROOT and Mup links, and pins on
  which layer refuses each existing case.
- `tools/calibration/README.md` step 3 and `tools/calibration/subject-pack/README.md` (Isolation): both layers, the
  repository rule for the checkout, nothing made on refusal, no template.
- `CHANGELOG.md`: a clause folded into sr-kit-cases' existing entry ("Calibration kit: run 4 case keys"); no new line.

**Not touched, on purpose:** `tools/calibration/subject-pack/shared/README.md`. I first added a sentence to its step 3,
then found that `shared/manifest.json` records that README's SHA-256 in `source_hashes` (so every host's
`subject_pack.manifest_sha256` would change), and the manifest is not a file this round may touch. I reverted it. Its
text stays true: the guards it names still compare paths with the pack directory only.

## Tests

New tests (all in `Scripts`):

| test | what it covers |
|---|---|
| `..._checks_the_paths_native_programs_resolve` | real GUID and GLOBALROOT links made with `os.symlink` (C:'s volume name from `GetVolumeNameForVolumeMountPointW`), first checked to be invisible to Git Bash: DIR into another repository's `node_modules`, a linked worktree, a bare repository's `refs`, the source, the pack; a chain; hidden top-level entries into the source, a work tree (two spellings), the drive root, and a dangling one ("does not resolve"); Mup links resolving to UNC as a top-level entry, as the pack and as the source (when the admin share is reachable); a target through a GUID link into the pack and into another repository; accepted controls |
| `..._refuses_without_a_native_path_resolver_on_windows` | `PATH` without any Python, and with stubs answering `posix`: refused, nothing made; a stub that passes the probe but fails the check: "the native path check failed (exit 3)" |
| `..._copies_no_git_template` | a template with alternates, hooks and a description, first shown live (a plain `git init` with it reads the accepted fix); through `GIT_TEMPLATE_DIR` and through `init.templateDir`: none copied, the accepted fix not readable, the object set exact |
| `..._makes_nothing_when_it_refuses_a_target` | a target under missing parents in the pack, under a missing UNC parent (with and without `--pack`), and with `..` in the missing part: refused, nothing made; a plain missing path: made |
| `..._refuses_a_target_inside_a_git_repository` | targets in a work tree, at depth, under missing parents, in `.git`, in a linked worktree, in a bare repository and its `refs`, in the source; through a symlink; a control beside the repositories |

A test that needs links skips, with its reason, on a host that cannot make them; the native test also skips when the
volume name cannot be read. On this host none skips.

**Red first, against 16ef0a5** (the new tests run against the old script): all five fail, each for its own reason:

| test | 16ef0a5 result |
|---|---|
| native | the GUID link into another repository's `node_modules` accepted ("ok") |
| resolver | accepted with no Python on `PATH` |
| template | `objects/info/alternates` copied from the template (re-run with the fixed test, below: the same) |
| nothing made | `pack/new` made by a refused target |
| repository | a target inside another repository accepted |

**Green:** the 17 checkout tests (`bash -n` and the 16 `historyless` tests) pass, 0 skipped, with `MSYS=winsymlinks:nativestrict` (the mutation control); the two later test edits (the crash stub, the template fix) passed on their own and in the full suite.

## Guard-removal proofs

Each mutation ran in its own scratch copy of the kit, its tests and fixtures, against the same 17 checkout tests, with
`MSYS=winsymlinks:nativestrict`. Each anchor had to match exactly once, and every copy passed `bash -n`. The control
(no mutation) passed all 17. Every mutation below turned at least one test red; none survived.

**A note on the shell mutations.** With a shell-layer guard removed, the native layer still refuses most of those
cases on Windows, so a test that only asserted "refused" would stay green. The tests pin the layer: a shell-layer case
asserts that the refusal does *not* carry "as native programs resolve it". So these mutations go red with the message
`'as native programs resolve it' unexpectedly found`. This is what the pins are for: each layer's guard is proven on
its own. It also shows, on this host, that the native layer is a real second line for every one of those cases.

**Shell layer (rounds 2-3, re-run with the native layer in place):**

| mutation | red tests (reason) |
|---|---|
| N1: a UNC spelling walked, not refused | UNC (wrong reason, "inside the git repository //localhost/..."); Windows parents (native "does not resolve" instead of the shell's refusal); nothing made (the native layer refused the UNC parent) |
| N2: `canon` always collapses `//` | UNC; nothing made (wrong reason: native "does not resolve") |
| N3: no Windows spelling | Windows parents (the native layer refused instead) |
| N4: "inside" by spelling | identity (native refused `PACK/extra`); Windows parents (wrong reason) |
| N5: "holds" by spelling | identity (native refused) |
| N6: target-in-pack by spelling | identity (native refused `pack/cand-case`) |
| N7: no unset | git variables (`g2` changed) |
| N8: `add_guard` ignores a non-local path | UNC (native refused the UNC pack) |
| N9: the target parent ignores a non-local path | UNC; nothing made (native refused) |
| N10: `guard_link` ignores a non-local path | UNC; Windows parents |
| N11: the shell spelling not walked | reaches_the_pack (`node_modules=/` accepted); existing_target (`under-root` accepted) |
| R1: no `.git` clause | inside_a_git_repository; symlinks_at_the_top; Windows parents; target inside a repository (each refused natively instead) |
| R3: no git-directory clause | inside_a_git_repository (`bare.git`); symlinks_at_the_top; target inside a repository (`bare.git/co`) |
| R4: `guard_link` checks DIR itself only | inside_a_git_repository; symlinks_at_the_top; Windows parents |
| R6: no top-level loop | symlinks_at_the_top; UNC; identity |
| M10: `mkdir` of TARGET's parent first (the 16ef0a5 order) | 9 tests, among them nothing made (`pack/new` made) and target inside a repository (`other/new` made) |
| M12: `resolve` follows one hop | symlinks_at_the_top |
| M13: `physd` uses plain `cd` | symlinks_at_the_top (`deps-dotdot`: wrong reason) |
| M14: a dangling top-level link skipped | symlinks_at_the_top (`gone` refused natively instead) |
| M15: dot entries not enumerated | symlinks_at_the_top (`.hidden` refused natively instead) |

**Native layer (LC3-1):**

| mutation | red tests (reason) |
|---|---|
| NA: the layer never runs | native (`v-clone` accepted); resolver (the crash stub accepted) |
| NB: no resolver: skip the layer instead of refusing | resolver (accepted with no Python) |
| NC: the probe accepts a POSIX Python | resolver (the `posix` stub accepted) |
| ND: a top-level entry that does not resolve is skipped | native (a dangling GUID entry accepted) |
| NE: a non-drive-letter result accepted | native (the Mup entry resolving to UNC accepted) |
| NF: no native "inside the source or pack" | native (`v-src` refused for the wrong reason: repository, not "holds the accepted fix") |
| NG: no native "holds the source or pack" | native (an entry to the drive root accepted) |
| NH: no native repository walk for links | native (`v-clone` accepted) |
| NI: the native repository check on the path itself only | native (`v-clone` accepted) |
| NJ: top-level entries not enumerated | native (a hidden GUID entry accepted) |
| NK: the source and pack not resolved | native (the Mup pack accepted) |
| NL: no native target-in-pack check | native (`v-deeper/co-x` made inside the pack) |
| NM: no native target repository check | native (`v-sub/new/co-y` made inside a repository) |
| NN: the target's parent not resolved | native (`v-deeper/co-x` made inside the pack) |
| NO: a `--link DIR` not resolved | native (`v-clone` accepted) |
| NS: the source not passed to the layer | native (`v-src`: wrong reason) |
| NP: the pack not passed to the layer | native (`v-pack` accepted) |
| NX: the layer's refusal (exit 2) ignored | native (`v-clone` accepted) |
| NY: the layer's failure (any other exit) ignored | resolver (the crash stub accepted) |

**LC3-2, LC3-3, LC3-4:**

| mutation | red tests (reason) |
|---|---|
| T1: no `--template=` | template: **exit 1 from the new proof**, "can read objects other than the base commit and its tree (objects/info/alternates?)" |
| T12: no `--template=` and no object-set proof | template: exit 0, `objects/info/alternates` copied |
| Mmk: the missing parents made before the target checks | nothing made; target inside a repository; native; resolver (each left a directory behind) |
| Mdd: `.` / `..` in the missing part allowed | nothing made (refused anyway, but for a wrong reason: `cygpath` cannot convert the missing `m2/..`, so the shell layer calls it "not a local path") |
| RT: no shell target repository check | target inside a repository (refused natively instead) |
| RTM: no target repository check in either layer | target inside a repository (`other/co` made); native (`v-sub/new/co-y` made) |

T1 and T12 were run again after I fixed the template test (see "What I got wrong"); the results above are from the
fixed test. The other mutations ran with the earlier version of that one test, which no other mutation depends on.

**Not proven by a mutation:** the `FILE_ATTRIBUTE_REPARSE_POINT` half of `is_link` (a junction at DIR's top). The
tests make symlinks only, and `is_symlink` catches them. A junction is expected to be caught the same way (untested).

## IC4-1, re-run against the read-only MoonAliza clone

The clone at HEAD 1ac226d, read only (nothing written there; the links live in a scratch directory). Each variant ran
with `--pack` and without, ten runs:

| `--link node_modules=` | result | layer |
|---|---|---|
| the clone's `node_modules` directly | refused, exit 2, nothing made | shell |
| a volume-GUID link to it | refused, exit 2, nothing made | native |
| a `GLOBALROOT\DosDevices` link to it | refused, exit 2, nothing made | native |
| a plain symlink to the GUID link (a chain) | refused, exit 2, nothing made | native |
| a clean directory whose top-level entry is a GUID link to the clone | refused, exit 2, nothing made | native |

`git status --porcelain --ignored` of the clone is the same before and after (`!! node_modules/`,
`!! research/raw/.diagnostics.jsonl`).

## Checks

- **Rendered prompts:** `run.template.js` is unchanged since 09b476d (`git diff --quiet 09b476d` on it). Rendering it at
  09b476d and at the working tree for the fixture and shared manifests, with `cause_in_prompt` absent, true and false:
  60 calls compared, 0 differ (verified).
- **Full kit suite:** `python -W error::SyntaxWarning tools/test_calibration_kit.py`: 127 tests OK, 1 skipped (was 122 and 1). The skip is the existing one: without `MSYS=winsymlinks:nativestrict`, Git Bash's `ln -s` copies instead of linking; with it set, the 17 checkout tests ran with 0 skipped (verified).
- **Evidence check:** `check_calibration_evidence.py`: 3 folders, 0 failures, 14 limitations, as before (verified).
- **Secrets:** `check_secrets.py` clean (0 hits); `check_credential_hygiene.py` clean, 0 new findings (verified).
- **Hygiene:** every changed file is LF (`git ls-files --eol`, no CR); the diff adds no absolute host path, session or
  run id, `getenv`/`os.environ`, or model name (verified).
- **Pre-commit gate:** runs on the commit itself (its outcome is in the returned gist, not here).

**Untested or expected:**

- Hosts other than this Windows 11 / Git Bash one. On Linux and macOS the native layer does not run (`uname` names no
  `CYGWIN`, `MINGW` or `MSYS`), and the shell layer's `pwd -P` is the kernel's own resolution, so this hidden-link class
  does not arise there (expected, untested).
- A volume mounted with no drive letter (a folder mount point): its `realpath` result is a `\\?\Volume{...}` path, which
  the layer refuses by the same rule the Mup case proves (expected, untested).
- `subst` drives: not exercised (untested).
- A junction at DIR's top (see above).

## What I got wrong and fixed

- **At first the template test did not set up a working alternate.** I wrote `objects/info/alternates` with Python's
  `write_text`, which writes CRLF on Windows. Git read the path with a trailing CR, warned "does not exist", and skipped
  it. So the test only proved that no template file was copied, not that a copied one would leak; the red run against
  16ef0a5 failed on the file's presence, which hid this. I found it when mutation T1 (no `--template=`) failed on the
  file's presence instead of on the new proof. **Fix:** the file is written as bytes, with LF, and the test first proves
  the template is live: a plain `git init --template=<it>` reads the accepted fix. With that, T1 fails on the proof's
  own message, as designed, and the test still fails against 16ef0a5 (the file is copied).
- **I edited the shared pack's README** (a sentence on the new repository refusal), then found its hash in
  `shared/manifest.json` `source_hashes`. Changing it would change every host's manifest hash, and the manifest is not
  mine to touch in this round. **Fix:** reverted; the README's text stays true.
- **A doubled comma** in the native message for a top-level entry ("a link at the top of DIR,, as native ..."), seen in
  my first IC4-1 run. **Fix:** the message is built without it; the final IC4-1 run shows the fixed text.
- **Test setup slips, fixed before the green run:** removing a scratch repository with `shutil.rmtree` failed on
  read-only git objects (I used separate output directories instead); a first draft of the template test's object set
  started from a wrong expression.
- **Tool slips:** the shell wrapper halves `\\?\` and `\\n` in typed text, which broke a GLOBALROOT probe and a test
  edit (I wrote those scripts with the file tool instead); unittest was first run from the wrong directory.
