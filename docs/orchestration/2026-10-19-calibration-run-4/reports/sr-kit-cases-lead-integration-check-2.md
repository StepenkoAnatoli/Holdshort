# sr-kit-cases, lead integration check 2 (refute-first, fresh context): `--link` inside a git repository (IC4-1)

Checked: branch `build/sr-kit-cases` at 69d1d03 (lead integration 2) on 09b476d. I read it against IC4-1
(sr-pack-4a integration check 4), the integration report (`reports/sr-kit-cases-lead-integration-2.md`) and the lead's
design in the run notes ("--link refuses a DIR inside any git repository"). I wrote none of the change. This report is
the only file this round adds. Every run had TEMP and TMP on the gittoken `.tmp-gate` folder. I only read the MoonAliza
clone.

**Verdict: FIX**, for one S3 (LC2-1). IC4-1 itself is closed. The new script refuses the clone's `node_modules`, and
also a directory inside a work tree, a linked worktree, a bare repository or a `.git` directory, reached by a plain
path, a symlink, a Windows junction, a `C:\` or `C:/` spelling, or a path with spaces. Refusals create nothing. The
walk ignores `GIT_DIR`, `GIT_CEILING_DIRECTORIES` and `GIT_DISCOVERY_ACROSS_FILESYSTEM`. All guard-removal proofs go
red. But the new top-level symlink check, which the docs promise for "the real path it resolves to", has a hole: a
link spelled as a UNC path (`//host/share/...`) is checked on a different path. I reproduced that, and through the hole
`git log` in the checkout shows the pack repository's history (LC2-1). Two S4s (LC2-2, LC2-3) do not block.

## Findings

| id | severity | finding |
|---|---|---|
| LC2-1 | S3 | **A UNC path defeats both checks.** `phys` and the new `physd` turn a leading `//` into `/` (N3: on POSIX, `//x` is `/x`). Under Git Bash (Cygwin), `//host/share/x` is a UNC path, and `/host/share/x` is a different path that does not exist. So the guard runs `within` and `repo_holding` on a path that is not the link's target. Every ancestor test on that path is false, and nothing is refused. **Reproduced** (scratch repositories under `.tmp-gate`, `MSYS=winsymlinks:nativestrict`, the administrative share `//localhost/C$` reachable on this host). (c2) DIR is outside every repository and holds `plain/` and `lib -> //localhost/C$/<scratch>/other repo/node_modules`. Result: exit 0, "ok". In the checkout, `ls -a node_modules/lib/..` lists `.git README node_modules`, and `cat node_modules/lib/../.git/HEAD` prints `ref: refs/heads/master`. (c3) With `--pack <source repo>`, a top-level link `src -> //localhost/C$/<scratch>/src` (the source repository itself): exit 0. In the checkout, `git -C node_modules/src log --oneline` prints the source repository's commit. In a real run, that history is the one that holds the accepted fix. (c1) DIR spelled `//localhost/C$/<scratch>/other repo/node_modules`: exit 0, "ok", but the link points to `/localhost/C$/...` and dangles. That is no leak, but the script says "ok" for a broken checkout. **Why S3:** this breaks the guard's own documented promise ("Each symlink among DIR's own entries ... is checked the same way on the real path it resolves to") and Item 2, on the host the kit runs on. It is not S2, because a host has to make a UNC-spelled link; the README's procedure does not do that. The DIR half (c1) and the collapse itself predate this change. The top-level check is new, and it inherits the collapse through `physd`. **Fix (the lead decides):** collapse a leading `//` only when it names the same directory as the collapsed spelling (`[ "$p" -ef "${p#/}" ]`), or refuse a DIR or link whose physical path starts with `//name` (fail closed). If `//` is kept, `repo_holding` must also stop at `//`: `dirname //localhost` is `//`, and `dirname //` is `//`, so the loop's `[ "$p" = / ]` never ends it (checked). Add a test with a `//localhost/C$` spelling that skips when the share is not reachable. |
| LC2-2 | S4 | **On a case-insensitive filesystem, the pack check compares spellings.** `within` compares strings, and `pwd -P` keeps the case the caller typed (`cd /c/users/pc/desktop/GITTOKEN/...; pwd -P` prints that spelling). (d1) `--pack packd --link node_modules=<scratch spelled in other case>/PACKD`, with `packd` holding `repo` and `manifest.json` and lying outside every repository: exit 0. 09b476d's script accepts it too. (d2) The same through a top-level link in a clean DIR: exit 0 (new check, same comparison). The new repository walk tests the filesystem, so it is case-blind. It refuses every such spelling of the pack repository itself, and of a pack directory that sits inside a repository, which is the Holdshort layout. What stays open is only a pack directory outside every repository, or a directory that holds the pack repository, spelled in another case. **Fix:** compare paths on the filesystem: "inside" holds when some ancestor of P is `-ef` the guarded path, and "holds" when some ancestor of the guarded path is `-ef` P. Or name the limit in the docs. |
| LC2-3 | S4 | **Not from this change: the script honours the host's `GIT_DIR` / `GIT_WORK_TREE`.** The new walk does not (verified: e1 refused with `GIT_DIR` set to another repository, and `GIT_CEILING_DIRECTORIES` set to the clone-like repository changed nothing, a4). But with `GIT_DIR=<scratch>/g2/.git GIT_WORK_TREE=<scratch>/g2` and an accepted link (e2), `git init` re-initialised g2. The script then created branch `main` in g2 and ran `reset --hard` in g2's work tree, and finished with exit 1 (`.git/info/exclude: No such file`). With `GIT_DIR=/nonexist`, it refuses ("not a commit"). **Fix:** `unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR` at the top. Outside IC4-1, so it can wait for a later unit. |

## Claims, attacked

Scratch fixtures under `.tmp-gate`: a source repository, `other repo` (a work tree with a space in its name, with
`node_modules/pkg`), and `free dir/node_modules` (outside every repository). `.tmp-gate` and every ancestor up to Git
Bash's `/` hold no `.git`, `HEAD`, `objects` or `refs` entry (`ls -a` on each). "made" means the target's parent exists
afterwards.

| attack | result |
|---|---|
| DIR inside a work tree, at depth 2 (`other repo/node_modules/pkg`) | refused, exit 2, nothing made |
| DIR outside every repository (`free dir/node_modules`) | accepted, exit 0 |
| DIR as `C:\...` (cygpath -w) and as `C:/...`, with a space in the path | refused, exit 2, nothing made |
| `GIT_DIR=/nonexist GIT_CEILING_DIRECTORIES=<scratch> GIT_DISCOVERY_ACROSS_FILESYSTEM=0` | refused before the walk ("not a commit in src": the source lookup honours `GIT_DIR`, LC2-3); nothing made |
| `GIT_CEILING_DIRECTORIES=<scratch>/other repo` | refused (the walk ignores it) |
| `GIT_DIR=<another repo>/.git` | refused as inside `other repo` |
| DIR through a symlink to `other repo/node_modules`, and `sl/pkg` | both refused, the message names the physical path |
| DIR through a Windows junction to `other repo/node_modules`, and `jr/node_modules/pkg` with junction `jr` to the repo root | both refused (Git Bash shows junctions as symlinks, and `pwd -P` resolves them) |
| a top-level junction in a clean DIR, to `node_modules` and to the repo root | both refused |
| DIR spelled `sl/../free dir/node_modules` | accepted. Correct: `phys` takes `..` by spelling, and the link made is to the physical path that was checked |
| a stray `.git` file (`gitdir: /nowhere`) in DIR's parent | refused (fail closed, as documented) |
| `.git` as a symlink to another repository's `.git` | refused |
| DIR = `E:/` (a drive root outside every repository, not holding the source) | accepted. The walk checks `/e` and Git Bash's `/` |
| DIR or a top-level link spelled `//localhost/C$/...` | **accepted (LC2-1)** |
| a pack spelled in another case (pack outside every repository) | accepted (LC2-2) |
| the documented gap: `@scope/pkg ->` a work tree's `node_modules`, one level down | accepted. `ls -a node_modules/@scope/pkg/..` lists the repository's `.git`. That is what the header and README say ("Nothing deeper is checked ... the host's to avoid"). Honest |
| a real directory inside DIR that is itself a repository | not checked, covered by "a repository further down inside DIR". Honest |
| IC4-1 itself: `--link node_modules=<clone>/node_modules` | refused, exit 2, "is inside the git repository <clone>", nothing made. The clone's `status --porcelain --ignored` is the same before and after (`!! node_modules/`, `!! research/raw/.diagnostics.jsonl`) |

Nothing is created on refusal. Every refusal above, and every refusal the tests make (`assert_link_refused` checks the
fresh parent), happens before `mkdir -p`. My guard M10 below moves a `mkdir` ahead of the checks, and both new tests go
red.

## Diff, docs, CHANGELOG

- `git diff --stat 09b476d HEAD` shows six files: the script, the test module, the kit README, the subject-pack README,
  `CHANGELOG.md` and the report. Those are the files the report names. `run.template.js` is untouched, and its line-71
  comment is now incomplete, as the report says (item 2 for the lead).
- CHANGELOG: numstat 1/1. The clause is folded into the existing "Calibration kit: run 4 case keys" line, and the
  one-line tests pass in the suite. The clause matches the behaviour, but LC2-1 applies to "a top-level symlink in it
  that reaches one or the pack".
- The header comment and both READMEs describe what the script does, with two exceptions: the UNC case (LC2-1) and
  case spelling (LC2-2). The deeper-entries gap is stated plainly in all three.
- LF: `git ls-files --eol` gives `i/lf w/lf` for all six files. The changed kit lines contain no absolute host path,
  session id or run id (grep of the added lines). The commit message has the five parts, and names the model only in
  the trailer.

## Guard-removal proofs (re-run, my own driver)

Each mutation went into a scratch copy of `tools/test_calibration_kit.py`, `tools/calibration/` and
`tests/fixtures/calibration/`. Each anchor was asserted to match exactly once, and every copy passed `bash -n`. I ran
the eight checkout-script tests in `Scripts` with `MSYS=winsymlinks:nativestrict`, and read each failure to confirm it
is the intended case.

| mutation | red (where) |
|---|---|
| control | none: 8 OK (147 s) |
| M1 the `.git`-entry clause removed | inside_a_git_repository (`other`), symlinks_at_the_top (`deps-0`) |
| M2 `.git` accepted only as a directory | inside_a_git_repository (`wt/node_modules`), symlinks_at_the_top (`deps-2`) |
| M3 the git-directory clause removed | inside_a_git_repository (`bare.git`), symlinks_at_the_top (`deps-3`) |
| M4 no ancestor walk | inside_a_git_repository (`other/node_modules`), symlinks_at_the_top (`deps-0`) |
| M5 the top-level loop skips every entry | symlinks_at_the_top (`deps-0`) |
| M6 a dangling link skipped | symlinks_at_the_top (`deps-5`) |
| M7 dot entries not listed | symlinks_at_the_top (`deps-2`) |
| M8 `physd` as a plain `cd` | symlinks_at_the_top (`deps-dotdot`) |
| M9 (mine) `resolve` stops after one hop | symlinks_at_the_top (`deps-1`) |
| M10 (mine) the target's parent made before the checks | both new tests ("True is not false": parent exists) |
| M11 (mine) top-level links get only the pack/source check | symlinks_at_the_top (`deps-0`) |

M1-M8 reproduce the report's R1-R8 and R12. No test covers LC2-1 or LC2-2. The lead's fix for LC2-1 should add one.

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` at 69d1d03 (no `MSYS`) | 118 tests OK, 1 skipped (`links_only_on_request`, Git Bash copies without `MSYS`), 733 s, exit 0. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

Untested: hosts other than this Windows / Git Bash one. On Linux, `//x` is `/x`, so LC2-1 is expected not to apply
there. Expected, not run.

## For the lead

1. LC2-1 (S3): stop `phys`/`physd` turning a UNC `//host/share` into `/host/share`. Either keep `//` when it is not the
   root (and stop `repo_holding` at `//`), or refuse such paths. Add a test that skips when `//localhost/C$` cannot be
   reached.
2. LC2-2 (S4): compare the pack/source with the filesystem (`-ef`), not spellings, or name the limit.
3. LC2-3 (S4, from before this change): unset git's repository variables at the top of the script.

## What I got wrong and fixed

- My first junction fixtures used `cmd //c mklink /J` with unquoted paths that contain a space. They failed ("The
  syntax of the command is incorrect"), so b1/b2/b6 first tested missing paths (refused as "no directory", not as
  inside a repository). I re-made the junctions with PowerShell `New-Item -ItemType Junction` and re-ran them. Only the
  re-runs are cited.
- My first guard driver lost a backslash-newline in two anchors (M1, M3). Its own assertion refused them before
  anything was graded. I rebuilt them with `chr(92)` and re-ran M1-M11. Only that run is cited.
