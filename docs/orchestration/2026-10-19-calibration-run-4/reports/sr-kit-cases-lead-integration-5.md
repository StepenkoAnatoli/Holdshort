# sr-kit-cases, lead integration 5: a repository rule wider than git's own, no link named .git, Python 3.10+, and the threat model stated (LC4-1, LC4-2, LC4-3, LC4-4)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of 4bcf33c (lead integration check 4, FIX).
This is the last bounded round. The owner's decision of 2026-10-26: match git's own rule, fix the S4s, write the threat
model. The change is one commit through the pre-commit hook. This report is part of that commit, so it cannot name its
own sha (the returned gist does).

**Verdict: DONE.** All four findings of check 4 are closed in `historyless-checkout.sh`, each with a red-first test
and guard-removal proofs:

- **LC4-1 (S3):** `is_repo` is now at least as wide as git's repository detection, in both layers. A directory counts
  as a repository when it holds an entry of any type named `.git`, `HEAD`, `commondir` or `gitdir`, or both an
  `objects` and a `refs` entry. The native layer fails closed: an entry it cannot read counts as held.
- **LC4-2 (S4):** the probe asks for Python 3.10+ (the version whose `os.path.realpath` takes `strict`). The header,
  README step 3 and the refusal say so.
- **LC4-3 (S4):** the header and README step 3 now state what the guard covers and what is the host's duty. The
  subject-pack README's Isolation section points there.
- **LC4-4 (S4):** a junction test covers the reparse-point half of the native `is_link`. A `--link` NAME is refused
  when any of its segments names `.git` in any spelling Windows resolves to it, or when it holds a `\` or a `:`.

All 45 guard mutants of round 4 are still killed, and so are 25 new ones. The rendered prompts are byte-identical to
09b476d. The IC4-1 reproduction against the read-only MoonAliza clone is refused in all 14 variants, and the clone is
unchanged.

## LC4-1: git's own rule, and the wider one

I read `setup.c` and `compat/mingw.c` at git-for-windows v2.55.0.windows.5 (the host's git, 2.55.0.windows.5):

- `setup_git_directory_gently_1` walks up from the working directory. At each level it takes `.git` when
  `read_gitfile_gently` reads it as a gitfile (`gitdir: <path>`), or when `is_git_directory(.git)` accepts it. Failing
  both, it takes the directory itself when `is_git_directory` accepts it (a bare repository, the inside of a `.git`
  directory, a linked worktree's admin directory).
- `is_git_directory(suspect)` (setup.c:415) needs three things:
  - `validate_headref(suspect/HEAD)` (setup.c:352) to succeed. It accepts a symlink whose target starts with `refs/`
    (a dangling one too: the target is never opened), or a file holding `ref: refs/...` or a hex object id.
  - `objects` in the common directory, or `GIT_OBJECT_DIRECTORY`.
  - `refs` in the common directory.
- The common directory comes from `GIT_COMMON_DIR`, or from a `commondir` file in the suspect (`get_common_dir_noenv`,
  setup.c:323).
- `objects` and `refs` are tested with `access(..., X_OK)`. Git for Windows' `mingw_access` (mingw.c:1170) drops
  `X_OK`, so a *file* named `refs` passes.

So under the environment variables a candidate may run with (`GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`), the only entry
git always needs is `HEAD`. The rule I chose is wider than git's own on purpose (erring wider, as the brief asks). A
directory is a repository when it holds:

- `.git` (any type: a directory, a gitfile, a link);
- `HEAD` (any type, a dangling link too);
- `commondir` or `gitdir` (a linked worktree's admin files);
- or both `objects` and `refs` (any type). A `..` reaches and reads these objects without git, even with `HEAD` gone.

"Any type" is `[ -e ] || [ -L ]` in the shell layer and `os.lstat` in the native layer. In the native layer, an
`OSError` other than `FileNotFoundError` or `NotADirectoryError` counts as the entry being there (fail closed).

**Per shape, at 4bcf33c and now.** Each shape is a directory `d` holding an empty `deps/`. Columns:

- DIR: `--pack P --link node_modules=d/deps`;
- top link: a top-level symlink to `d/deps` in a free directory;
- TARGET: `d/deps/co`;
- DIR via GUID and TARGET via GUID: the same through a volume-GUID link Git Bash cannot see.

S is the shell layer, N is the native layer ("as native programs resolve it"). I ran the driver on both trees with the
same test helpers.

| shape (git's view) | 4bcf33c | now |
|---|---|---|
| `commondir` git dir: `HEAD` and a `commondir` file pointing at another repository (git takes it) | ACCEPTED in all five | refused S, S, S, N, N |
| symlink `HEAD`: bare clone, `pack-refs --all`, `HEAD` a symlink to `refs/heads/main` (git takes it) | ACCEPTED in all five | refused S, S, S, N, N |
| `refs` as a file: bare clone, `pack-refs --all`, `refs` a file (git takes it on Windows) | ACCEPTED in all five | refused S, S, S, N, N |
| gitfile: `git init --separate-git-dir`, `.git` a file pointing elsewhere (git takes it) | refused S, S, S, N, N | refused S, S, S, N, N |
| `HEAD` only (git takes it with `GIT_COMMON_DIR`) | ACCEPTED in all five | refused S, S, S, N, N |
| dangling `HEAD` symlink only (git takes it with `GIT_COMMON_DIR`) | ACCEPTED in all five | refused S, S, S, N, N |
| `commondir` only (git never takes it) | ACCEPTED in all five | refused S, S, S, N, N |
| `gitdir` only (git never takes it) | ACCEPTED in all five | refused S, S, S, N, N |
| `objects` and `refs` only (git never takes it) | ACCEPTED in all five | refused S, S, S, N, N |

The tests assert git's own view for each shape, so a later git that stops taking one shows up as a test failure, not
as silent drift. The view comes from `git rev-parse --absolute-git-dir` in `deps`. For the `refs` file it is asserted
on Windows only.

**What is wider than git, and its cost.** A directory that merely holds a file named `HEAD`, `commondir` or `gitdir`,
or both `objects` and `refs`, is refused as a parent of DIR or TARGET. Such a directory above a dependency tree is
rare. A refusal names the directory and the rule, and the host moves the tree. I judged a false refusal cheaper than a
missed repository.

## LC4-2: Python 3.10+

The probe is now `sys.version_info >= (3, 10)`. The header, the comment on `NATIVE_PY`, README step 3 and the refusal
("needs a Windows Python 3.10+ (os.path.realpath's strict argument) on PATH ...") say 3.10+. This host has only Python
3.14. The test therefore emulates a 3.9: a stub `python3` on `PATH` runs the real Python with `sys.version_info` set to
3.9.18 and a `realpath` without `strict`. The test first checks the emulator itself: it raises the `TypeError` check 4
predicted. The script then refuses with "no native path resolver ... Python 3.10+", exit 2, and makes nothing.
At 4bcf33c the same stub passed the probe, and every checkout failed with "the native path check failed (exit 1)" and
the `TypeError` (fail closed, but with the wrong reason).

## LC4-3: what the guard covers, and what is the host's duty

The header has a new paragraph, "What the guard covers, and what it cannot", and README step 3 has a bold paragraph,
"What the guard covers, and what is the host's duty". Both state:

- **Covered:** no path the checkout gets from the script reaches a git repository, the pack or `SOURCE_REPO`, by any
  spelling native programs resolve. That covers TARGET's own parents, each DIR and its parents, and each link at DIR's
  top together with the parents of where it leads.
- **The host's duty, which the guard cannot see:**
  - a plain copy or export (`git archive`) of the subject's files;
  - a work tree whose git directory lies elsewhere (`core.worktree`, which leaves no `.git` in the tree);
  - a link or a repository deeper inside DIR;
  - anything else the guard could know only by its content.
- A refusal never means "remove the `.git` and retry": a stripped clone still hands over its files (orchestration
  records, a brief).
- Install dependencies where no subject file is, such as a history-less checkout of the case base made outside the
  pack.

The subject-pack README's Isolation section adds one sentence. It says the guard knows repositories by their markers
only, that a copy, an export or a detached work tree is the host's to keep away, and it points to step 3.
`subject-pack/shared/README.md` is not touched: its hash is pinned in `shared/manifest.json`.

## LC4-4: the junction half of is_link, and link names

- **Junction:** the native LC4-1 test makes a junction with `_winapi.CreateJunction`. The junction points at a hidden
  GUID link into another repository's `node_modules`, and sits at the top of DIR. The test asserts the following:
  - Python sees no `is_symlink()` on it;
  - Git Bash sees it (`-L`), but the shell resolves it to a plain directory, so only the native `is_link`'s
    `FILE_ATTRIBUTE_REPARSE_POINT` half catches it;
  - it is refused with the native layer's reason, with and without `--pack`;
  - a control junction to a free `node_modules` is accepted, and the checkout is one commit.

  Mutant JR (`is_link` reduced to `is_symlink()`) turns this test red. No round-4 test did that.
- **Link names:** NAME is split on `/`. In each segment, trailing dots and spaces are stripped (Windows drops them),
  and the segment is refused when it is `.git` in any case or the 8.3 name `GIT~1`. The message says "a link name may
  not name .git (in any case or spelling)". `\` and `:` are refused as "a plain relative name" (another separator, a
  drive or a stream). I refuse every segment, not only the first: `vendor/.git` would make a nested repository's
  `.git`. The test covers these cases:
  - refused: `.git`, `.git/hooks`, `.git/objects/info`, `.GIT`, `.Git/hooks`, `.git.`, `.git `, `.git. .`, `GIT~1`,
    `git~1/hooks`, `vendor/.git`, `a/./.git/x`, `a\b`, `\x`, `c:x`, `x:y`;
  - accepted (controls, with `git status` clean after): `.github`, `git`, `gitdir`.

## Files

- `tools/calibration/historyless-checkout.sh`:
  - the header (the `--link` text, the NAME rule, the new coverage paragraph, 3.10+);
  - `has` and `is_repo` with the setup.c citation, in both layers;
  - the NAME check;
  - the probe and its message.
- `tools/test_calibration_kit.py`:
  - `repo_holding` uses the new rule;
  - `git_directory_shapes` (nine shapes, git's view asserted);
  - five new tests (below).
- `tools/calibration/README.md` step 3: the rule, Python 3.10+, the NAME rule, the coverage paragraph.
- `tools/calibration/subject-pack/README.md` (Isolation): one sentence.
- `CHANGELOG.md`: a clause folded into sr-kit-cases' existing entry ("Calibration kit: run 4 case keys"). No new line.

## Tests

| test | what it covers |
|---|---|
| `..._refuses_every_directory_git_takes_for_a_repository` | the nine shapes as DIR (with `--pack`) and as TARGET, and the four check-4 shapes as a top-level link; all refused by the shell layer |
| `..._refuses_every_directory_git_takes_for_a_repository_as_native_programs_resolve_it` | the nine shapes through hidden GUID links as DIR and as TARGET, and the four check-4 shapes as a hidden top-level link; the junction case and its control; all refused by the native layer |
| `..._native_layer_counts_an_entry_it_cannot_read_as_a_marker` | runs the heredoc's own code with `os.lstat` raising `PermissionError` for `HEAD`: an empty directory is no repository without the fault, and is one with it |
| `..._refuses_a_link_name_that_names_dot_git` | the names listed under LC4-4, and the controls |
| `..._needs_a_windows_python_3_10_for_the_native_layer` | the 3.9 emulation described under LC4-2 |

Layer pins: the shell test expects the shell's reason and the native test expects the native one ("as native programs
resolve it"). So removing a clause from one layer alone turns a test red.

**Red first, against 4bcf33c** (its `tools` and fixtures from `git archive`, with the new test file):

| test | 4bcf33c result |
|---|---|
| shell LC4-1 | `commondir-gd/deps` with `--pack` accepted ("ok", one commit) |
| native LC4-1 | `L/v-0` (GUID link to `commondir-gd/deps`) accepted |
| unreadable marker | `(0, 'False') != (0, 'True')`: an unreadable `HEAD` counted as absent |
| link name | `.git` accepted as a NAME |
| Python 3.10 | "no native path resolver" not in the output; the run died on the `TypeError` |

**Green:** 132 tests OK, 0 skipped, in the full suite (below). The mutation control ran the 22 checkout tests (`bash -n`
and 21 `historyless` tests): all OK in 1520 s.

## Guard-removal proofs

Driver: each mutant is a copy of the working tree's `tools/test_calibration_kit.py`, `tools/calibration` and
`tests/fixtures/calibration` with one change to the script. I ran six in parallel with `MSYS=winsymlinks:nativestrict`.

**Round 4's 45 mutants.** I re-applied each as a unified diff against round 4's control, with `patch -F0`. Forty
applied cleanly with an offset only. Five I redefined to the same change by an exact replacement:

- R1 and R3: the predicate they cut is rewritten;
- M15, NB and NC: their context lines changed. NB's probe message changed, and its second hunk needs the second
  `if [ -n "$WINDOWS" ]; then`.

Each ran the tests that were red for it in round 4. Every one is red again, on the same tests:

- NB and NC are now also red on the Python 3.10 test.
- R1 and R3 ran the new set and are red on the shell LC4-1 test, the link-repository test and the target-repository
  test. The two older tests R1 was red on in round 4 were not in that set.

**25 new mutants**, each run on the new set: both LC4-1 tests, the unreadable-marker, link-name and Python tests, and
`..._refuses_a_link_inside_a_git_repository` and `..._refuses_a_target_inside_a_git_repository`.

| mutant | change | red tests |
|---|---|---|
| R0 | shell `is_repo` back to 4bcf33c's predicate | shell LC4-1 |
| RH / RC / RG / RO | shell rule without `HEAD` / `commondir` / `gitdir` / `objects`+`refs` | shell LC4-1 |
| RL | `has` without `-L` (a dangling `HEAD` link missed) | shell LC4-1 |
| RE | `has` without `-e` (only links count) | shell LC4-1, link-repository, target-repository |
| Q0 | native `is_repo` back to 4bcf33c's predicate | native LC4-1, unreadable marker |
| QG / QC / QI / QO | native rule without `.git` / `commondir` / `gitdir` / `objects`+`refs` | native LC4-1 |
| QD | native rule `.git` only | native LC4-1, unreadable marker |
| QH | native rule without `HEAD` | native LC4-1, unreadable marker |
| QL | `os.stat` for `os.lstat` (follows links) | unreadable marker |
| QX | an unreadable entry counts as absent | unreadable marker |
| Z1 | the NAME check refuses nothing | link name |
| Z2 | first segment only | link name |
| Z3 | no trailing dot or space stripping | link name (plus a tearDown error: the accepted `.git.` link) |
| Z4 / Z5 | no `GIT~1` / case-sensitive `.git` | link name |
| Z6 / Z7 | `\` / `:` allowed | link name |
| PV | the probe back to `(3, 8)` | Python 3.10 |
| JR | `is_link` reduced to `is_symlink()` | native LC4-1 (the junction case) |

70 mutants, 70 red, and the control green.

- **QL is red only on the unit test.** I checked why: on Windows, `os.stat` on the shapes' dangling `HEAD` link (target
  `refs/heads/main`, with `/`) raises a generic `OSError` (WinError 123), not `FileNotFoundError`. So the fail-closed
  branch still counts it as held. The unit test pins `lstat`: it patches `os.lstat`, so a `has` that calls `os.stat`
  never sees the fault.
- **RL is caught by the dangling-`HEAD`-only shape.** The symlink-`HEAD` bare clone still has `objects` and `refs`
  directories, so it does not catch RL.

## IC4-1, re-run against the read-only MoonAliza clone

The same variants as round 4, plus two junction variants. All links and checkouts live in a scratch directory under
the gate's temporary directory, and nothing is written in the clone. Each variant ran with and without `--pack`:

- the clone's `node_modules` directly;
- a GUID link to it;
- a GLOBALROOT link;
- a chain (a plain link to the GUID link);
- a DIR whose top-level entry is a GUID link to the clone;
- a junction to the GUID link, as DIR;
- a DIR whose top-level entry is that junction.

All 14 runs exited 2, and none made a checkout. The direct runs were refused by the shell layer. Every other run was
refused natively with "is inside the git repository" and the clone's path. `git status --porcelain --ignored` in the
clone was `!! node_modules/ | !! research/raw/.diagnostics.jsonl` before and after (unchanged, verified).

## Checks

- **Rendered prompts:** `run.template.js` is unchanged since 4bcf33c. I rendered it at 09b476d and at the working tree
  for the fixture and shared manifests, with `cause_in_prompt` absent, true and false: 60 calls compared, 0 differ.
  The fix prompt sha prefixes are `5e66cf5f4d0c141c` (fixture) and `54a0353d503c950d` (shared), as before (verified).
- **Full kit suite:** `python -W error::SyntaxWarning tools/test_calibration_kit.py` with
  `MSYS=winsymlinks:nativestrict`: 132 tests OK, 0 skipped (was 127; five new) (verified).
- **Evidence check:** `check_calibration_evidence.py`: 3 folders, 0 failures, 14 limitations, as before (verified).
- **Secrets:** `check_secrets.py` clean (0 hits); `check_credential_hygiene.py` clean, 0 new findings (verified).
- **Hygiene:** every changed file is LF (`git ls-files --eol`). The diff adds no absolute host path, session or run
  id, or model name (verified).
- **Pre-commit gate:** it runs on the commit itself, so its outcome is in the returned gist, not here.

**Untested or expected:**

- Hosts other than this Windows 11 / Git Bash one. On Linux and macOS the shell rule is the same and the native layer
  does not run (expected, untested).
- A real Python 3.8 or 3.9: emulated, not installed (expected from the documented `realpath` signature).
- 8.3 names other than `GIT~1` (for example `GIT~2`, when several names collide): not refused. Such a name resolves
  to `.git` only when `.git` is not the first name with that prefix, and the checkout's `.git` is made by the script
  before any link. I judged it out of scope (expected, untested).

## What I got wrong and fixed

- **Backslashes collapsed in shell heredocs.** I wrote the `\` case of the NAME check through a heredoc, and it came out
  as `*\*` (a pattern that matches anything). The same collapse later broke my mutation driver (an unterminated
  string) and one of its edits (`\n` became a newline). **Fix:** those files were written or edited with the file tools,
  and the NAME test's `a\b` and `\x` cases, with mutant Z6, pin the pattern.
- **`${seg,,}` needs bash 4.** I first lowercased the segment with it. **Fix:** case patterns
  (`.[Gg][Ii][Tt] | [Gg][Ii][Tt]~1`), which any bash reads.
- **Placeholder expressions** (`... if False else ...`) were left in a draft of the new tests. **Fix:** removed before
  the green run.
- **`git init --separate-git-dir` failed** in the gitfile shape because its parent directory did not exist. **Fix:**
  the shape makes `store/` first.
- **My first red run for the unreadable-marker test was an ERROR, not a red.** The 4bcf33c copy still had an older
  test file without that test. **Fix:** I copied the current test file in and re-ran it. It fails on its assertion
  (`False` where `True` is expected).
