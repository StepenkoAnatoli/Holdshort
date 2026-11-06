# sr-kit-cases, lead integration 3: UNC paths refused, paths compared by identity, git's repository variables dropped (LC2-1, LC2-2, LC2-3)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of 331ed32 (lead integration check 2, FIX).
The change is one commit through the pre-commit hook. This report is part of that commit, so it cannot name its own sha
(the returned gist does).

**Verdict: DONE.** Each of the check's three findings is closed at its root in `historyless-checkout.sh`, with a
red-first test and guard-removal proofs:

- **LC2-1 (S3), UNC:** a UNC path is refused wherever a check needs it. This fails closed.
- **LC2-2 (S4), case:** the pack and source are compared by identity (`-ef`) along the ancestors, not by spelling.
- **LC2-3 (S4), git variables:** the script unsets every variable `git rev-parse --local-env-vars` lists, before any
  git command runs.

While closing LC2-1 I found one more case of the same class (mount aliases, below) and closed it too. LI2 (the
`run.template.js` comment) is updated; no test pins the template's bytes.

## LC2-1: a UNC path is refused (fail closed)

The check offered two fixes: keep `//` and stop the walk at the UNC root, or refuse a UNC path. **I refuse it.**

**Why refusing is the provably safe choice:**

- **Refusing can be proved.** No path whose physical spelling starts with `//name` reaches a comparison, so nothing
  can be compared by a wrong spelling.
- **Keeping `//` cannot be proved.** It would rest on facts that hold on this host but not in general:
  - `-ef` across a UNC spelling and a local spelling held here (a `//localhost/C$/<dir>` spelling is `-ef` its `/c/<dir>` spelling). That
    depends on the SMB server returning stable file ids, which a server need not do.
  - `..` at a share root differs between Cygwin and native Windows programs.
  - git already treats such a path as foreign ("dubious ownership", "may refer to a non-local directory").
- **The cost is small.** The README's procedure never makes a UNC path. A host that installs on a share is told to
  install on a local drive.

**Where it is refused.** The check applies to every path the script compares:

- DIR;
- each top-level symlink's resolved target;
- `--pack`, and the source repository when `--link` is given;
- the checkout's parent under `--pack`.

The message names the reason: "... is not a local path (a UNC path //host/share/..., or a mount of one), whose parents
cannot be checked reliably (Item 2)".

**How it works:**

- `canon` keeps a leading `//` unless it names the same directory as the collapsed spelling. On Linux, `//x` is `/x`,
  so the collapse still happens there, and the old N3 spelling rule holds.
- The new `ancestors` builds the list of parents to walk. It returns failure for a `//` spelling, and every caller
  turns that into a refusal.
- The source lookup (`git rev-parse` of the commit) now runs after the pack and source checks. Before, git's own
  dubious-ownership error came first for a UNC source, and the script then said "not a commit", which named the wrong
  reason.

**The walk always ends.** The check noted that `dirname //` is `//`, so the old loop never reached `/`. The new walk
strips one `/name` at a time and stops when a step changes nothing (`/`, or `X:/`). A `//` path never enters it.

## Found while closing LC2-1: mount aliases (same class, closed)

UNC is one way a path's real parents differ from the parents its shell spelling shows. MSYS mounts are another:

- Git Bash's `/` is `C:/Program Files/Git`, and `/tmp` is the user's temp directory.
- A directory under such a mount has Windows parents that the shell spelling hides.
- A native Windows program (node, npm) resolves `..` along those Windows parents.

So `ancestors` now walks both spellings: the shell's physical path, and `cygpath -m` of it. Every comparison (pack,
source, git repository) runs over both lists.

**When `cygpath` is missing:**

- On Cygwin, MinGW or MSYS (by `uname -s`), the script refuses, because the Windows parents cannot be checked.
- On any other host, there are no Windows parents, and only the shell spelling is walked.

**How it is tested.** A real mount changes the MSYS mount table every Git Bash process shares, so the test models one
instead. It puts a stub `cygpath` first on PATH. The stub delegates to the real `cygpath` and maps one scratch
directory to a Windows spelling inside another repository, the source, or the pack.

## LC2-2: identity, not spelling

All three relations now compare with `[ a -ef b ]` along the ancestors. On a case-insensitive filesystem, a spelling in
another case therefore names the same directory:

- **"Inside":** some ancestor of the link target (either spelling) is `-ef` the source or the pack.
- **"Holds":** some ancestor of the source or pack (either spelling, collected once by `add_guard`) is `-ef` the link
  target.
- **"Target inside the pack":** some ancestor of the checkout's parent is `-ef` the pack. The target does not exist
  yet, so it is inside the pack exactly when its parent is the pack or lies under it.

`within` is kept only for the last line of the target check ("the pack is inside the target"). That line cannot fire,
because the target does not exist, and it is left as it was.

## LC2-3: git's repository variables are dropped

Right after `set -euo pipefail`:

```bash
GIT_LOCAL_VARS=$(git rev-parse --local-env-vars) || { echo "historyless-checkout: git rev-parse --local-env-vars failed" >&2; exit 1; }
unset $GIT_LOCAL_VARS
```

**The list comes from git, not from the script.** On this host it is `GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CONFIG
GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT GIT_OBJECT_DIRECTORY GIT_DIR GIT_WORK_TREE GIT_IMPLICIT_WORK_TREE GIT_GRAFT_FILE
GIT_INDEX_FILE GIT_NO_REPLACE_OBJECTS GIT_REPLACE_REF_BASE GIT_PREFIX GIT_SHALLOW_FILE GIT_COMMON_DIR`. That is the set
git itself drops when it enters another repository, so a later git version's additions are covered.

**It works even when the host's variables point nowhere.** `git rev-parse --local-env-vars` needs no repository: with
`GIT_DIR=/nonexist` it exits 0.

## LI2: the `run.template.js` comment

The line-71 comment now says `--link` refuses "a directory inside the pack or its repository, or inside any git
repository". It is a comment only.

I checked that no test pins the template's bytes:

- the tests pin the rendered fix prompts (`FIX_PROMPT_GOLDEN`) and slot counts, not the template file;
- no tool hashes it.

The full suite passes with the change.

## Files

- `tools/calibration/historyless-checkout.sh`: the unset; `canon`; `is_repo`, `ancestors` and `add_guard`, which
  replace `repo_holding`; identity comparisons in `guard_link` and the target check; the source lookup moved after the
  pack check; a header paragraph "How paths are compared".
- `tools/test_calibration_kit.py`: four new tests and their helpers (`unc`, `bash_native`, `STUB_CYGPATH`,
  `tree_bytes`). `assert_link_refused` gains an optional `env`.
- `tools/calibration/README.md` (step 3) and `tools/calibration/subject-pack/README.md` (Isolation): identity, Windows
  parents, UNC refused, git variables ignored. Every phrase the existing tests pin is kept.
- `CHANGELOG.md`: a clause folded into the existing "Calibration kit: run 4 case keys" line (numstat 1/1, no new line).
- `tools/calibration/run.template.js`: the comment (LI2).
- This report.

## Tests (new)

All four sit with the other checkout tests in `Scripts`.

### `test_historyless_checkout_refuses_a_unc_path`

Needs Python symlinks. It skips when there is no `//localhost/<drive>$` spelling or the share is unreachable. The cases:

- DIR spelled UNC: inside a repository's `node_modules`, and a free directory. Both refused, "is not a local path".
- Top-level links `lib`, `src` and `free` to backslash UNC targets. The test asserts the link really reads
  `//localhost/...`. All refused.
- `--pack` spelled UNC: refused, "the pack ".
- The source spelled UNC: refused, "the source repository ".
- The checkout's parent spelled UNC under `--pack`: refused.
- Control: the same layout spelled locally is accepted.

### `test_historyless_checkout_compares_the_pack_by_identity_not_spelling`

It skips on a case-sensitive filesystem. Spellings in another case, each refused:

- `PACK`, and `PACK/extra`;
- `--pack PACK`;
- the scratch root swapped to another case (a directory that holds the pack);
- a top-level link into `PACK/extra`;
- a target inside the pack, given `--pack PACK` ("is inside the pack").

### `test_historyless_checkout_walks_the_windows_parents_of_a_mounted_directory`

A stub `cygpath` maps a clean scratch directory to a Windows spelling. The cases:

- inside another repository: refused, "is inside the git repository", with and without `--pack`;
- inside the source repository: refused, "holds the accepted fix", with and without `--pack`;
- inside the pack: refused, "holds the accepted fix", with `--pack` only (without `--pack` there is no pack to guard);
- `//server/share/x`: refused, "is not a local path";
- no mapping: accepted.

### `test_historyless_checkout_ignores_the_hosts_git_repository_variables`

- **Setup:** `g2` is a clone of the source plus an extra file. `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`,
  `GIT_OBJECT_DIRECTORY` and `GIT_COMMON_DIR` all point into `g2`.
- **Runs:** once with `--pack` and `--link`, once with no flags.
- **Asserts:** every byte of every file in `g2` is unchanged. The checkout exits 0 with one commit, the right tree and a
  clean status.

### Red first

I ran each new test against the 331ed32 script. Each failed for the reason it targets:

| test | 331ed32 result |
|---|---|
| UNC | passed the checks and failed later at `ln` (exit 1), with the target already made |
| identity | "ok" for `PACK` |
| Windows parents | "ok" |
| git variables | `g2` rewritten ("re-init: ignored --initial-branch"), then exit 1 on `.git/info/exclude` |

After the change, all 12 checkout tests pass (`bash -n` plus the 11 historyless tests) with
`MSYS=winsymlinks:nativestrict`, 0 skipped (270 s).

## Guard-removal proofs

Each mutation ran in its own scratch copy of the kit, its tests and fixtures, against the same 12 checkout tests, with
`MSYS=winsymlinks:nativestrict`. Each mutation's anchor had to match exactly once, and every copy passed `bash -n`. The
control (no mutation) passed all 12.

| mutation | red tests |
|---|---|
| N1: a UNC spelling is walked, not refused | UNC (wrong reason: "inside the git repository //localhost/..."); Windows parents (`//server` accepted) |
| N2: `canon` always collapses `//` | UNC (accepted) |
| N3: no Windows spelling (`WINPATHS` empty) | Windows parents (accepted) |
| N4: "inside" by spelling | identity (`PACK/extra` accepted); Windows parents (wrong reason) |
| N5: "holds" by spelling | identity (root swapcase accepted) |
| N6: target-in-pack by spelling | identity (target inside `PACK` accepted) |
| N7: no unset | git variables (`g2` changed) |
| N8: `add_guard` ignores a non-local path | UNC (a UNC pack accepted) |
| N9: the target-parent check ignores a non-local path | UNC (exit 128, git's dubious ownership) |
| N10: `guard_link` ignores a non-local path | UNC; Windows parents |
| N11: the shell spelling not walked | reaches_the_pack (`node_modules=/` accepted); existing_target (`--pack /` accepted) |
| R1: no `.git` clause | symlinks_at_the_top (`deps-0`); inside_a_git_repository (`other`); Windows parents |
| R3: no git-directory clause | symlinks_at_the_top (`deps-3`); inside_a_git_repository (`bare.git`) |
| R4: no ancestor walk | 7 tests |
| R6: no top-level symlink loop | symlinks_at_the_top (`deps-0`); identity (`deps-case`); UNC (`deps-unc-0`) |

N1-N11 are new for this round. R1, R3, R4 and R6 re-run lead integration 2's proofs against the reworked walk. The
other R proofs from that round mutate `resolve`, which this round does not touch. They are covered by the unchanged
tests passing.

## IC4-1 re-checked

I re-ran the original IC4-1 command against the MoonAliza clone, read only, with `--link node_modules=<clone>/node_modules`.

- **Result:** refused, exit 2, nothing made.
- **The clone is unchanged:** `git status --porcelain --ignored` prints the same before and after (`!! node_modules/`,
  `!! research/raw/.diagnostics.jsonl`).

## Checks

- **Full kit suite** (`python -W error::SyntaxWarning tools/test_calibration_kit.py`): 122 tests OK, 1 skipped
  (verified). The skip is `links_only_on_request`, the same as the baseline: without `MSYS=winsymlinks:nativestrict`,
  bash's `ln -s` copies the directory. The baseline was 118 OK, 1 skipped; this round adds 4.
- **The CHANGELOG-reading tests** (`test_k6_one_changelog_line`, `test_changelog_and_readme_name_the_kit`): passed
  after the last CHANGELOG edit (verified). The edit landed after the full run started, so I re-ran these.
- **Evidence check:** 3 folders, 0 failures, 14 limitations, unchanged (verified).
- **Secrets and credential hygiene:** `check_secrets` clean; `check_credential_hygiene` clean, 0 new findings
  (verified).
- **Speed:** with a hermetic git config, a checkout takes about 16.6 s, against about 14.7 s for the old script
  (measured on one small source).
- **The regression gate** runs in the pre-commit hook of this commit (expected: green, as the parts above are).

## Untested (expected behaviour stated)

- **The refusal when `cygpath` is missing** (Cygwin, MinGW or MSYS by `uname`): untested. Expected: refused, with the
  message in the script.
- **Hosts other than this Windows / Git Bash one:** untested. Expected on Linux:
  - `canon` collapses `//x` to `/x`, as before;
  - no `cygpath`, so only the shell spelling is walked;
  - the identity test skips on a case-sensitive filesystem;
  - the UNC test skips.
- **A real MSYS mount:** untested. The stub stands in for one, because a real mount changes the shared mount table.
  Expected: the same refusals, because the script reads only `cygpath -m`'s output.

## For the lead

- **The UNC decision fails closed.** A host whose dependencies live on a share now gets a refusal it did not get
  before. The README says to install on a local drive.
- **One host setting affects tests.** On this host, the global git config (git-lfs filters, a global `core.hooksPath`)
  can stall a scratch `git reset --hard`. The kit tests already use the hermetic `git_env`. A probe run outside it can
  hang. That is a host matter, not the kit's. A plain run of the old script under the host config finished in 22 s.

## What I got wrong and fixed

- **The first full run of the new tests had 2 failures.**
  - The UNC source case: git's dubious-ownership error came before the script's own check. **Fix:** I moved the source
    lookup after the pack and source checks.
  - The stub test's pack case: I had asserted a refusal without `--pack`. Without `--pack` there is no pack to guard,
    so the script was right and my test was wrong. **Fix:** I split it into a source case (both flag sets) and a pack
    case (`--pack` only).
- **A timing probe hung** at `git reset --hard` under the host's global git config. I stopped it and re-ran with a
  hermetic config.
- **Several command mistakes, all fixed by re-running correctly:**
  - a bash heredoc with nested quotes broke in the tool wrapper;
  - unittest was run from the wrong directory;
  - a stray `cat > /dev/null` blocked on stdin;
  - MSYS argument conversion mangled a backslash UNC path passed from bash to Python. The tests are unaffected: they
    make links with `symlink_to` directly.
- **One command was refused by the permission check.** It pointed git's variables at the read-only MoonAliza clone. I
  dropped it and only read the clone (`status --porcelain --ignored`).
