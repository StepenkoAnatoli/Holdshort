# sr-kit-cases, lead integration 2: `--link` refuses a directory inside any git repository (IC4-1)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of 09b476d (lead integration 1 and its check,
ACCEPT). The change is one commit through the pre-commit hook. This report is part of that commit, so it cannot name its
own sha (the returned gist does).

**Verdict: DONE.** IC4-1 (S3, sr-pack-4a integration check 4): `historyless-checkout.sh --link` refused only a directory
that shares a path with the pack or its repository. So it accepted a MoonAliza clone's `node_modules`, and from the
checkout `node_modules/../` reached the clone's `docs/orchestration/` and its history (the accepted fix 01a8604). That
breaks proposal Item 2 ("no path from a checkout reaches the accepted fix"). I reproduced it with the 09b476d script, and
the new script refuses the same command (below).

## This round was continued after a host restart

An earlier run of this same task was stopped at or during its commit, with its whole change staged on 09b476d. I
treated that staged change as an untrusted draft: I checked it against the lead's design, re-ran every proof myself and
trusted no log from before the stop. What I changed:

- **A hole in the draft's symlink resolution (fixed).** The draft's `resolve` joined a relative link target to the
  link's directory as spelled, and made only the last directory physical, with `phys` (a plain `cd`, which drops
  `link/..` by spelling). So a top-level file link `a -> sub/b`, with `sub` a link to a clean directory `far/x` whose
  `b -> ../y/file`, was resolved to `DIR/y/file` when DIR holds a `y` of its own, while the kernel (and Git Bash's
  `cat`) reaches `far/y/file`. With `far/y` a repository, the draft accepted the link. I reproduced that with the draft
  script under Git Bash (exit 0, `cat <checkout>/node_modules/a` printed the repository's file). Now `resolve` makes
  each hop's directory physical before it joins a relative target, and uses a new `physd` (`cd -P`), so a linked
  directory is followed before the `..` after it, as a POSIX kernel does. The same case is now refused.
- **Two new cases in the symlink test** for this: the chain above (`deps-chain`), and a link whose own target walks `..`
  after a linked directory (`deps-dotdot`, `c -> sub/../y/file`). Each has a decoy `y` in DIR outside every repository.
- **Three new guard-removal proofs** (R11 the draft's `resolve`, R12 `physd` as a plain `cd`, R13 an absolute hop
  joined as if relative), and every earlier proof re-run.
- Docs: the header comment and the kit README say the top-level links are followed hop by hop, a linked directory
  before the `..` after it.

The rest of the draft held up against the design and is kept as it was: the walk, the messages, the docs and the
CHANGELOG clause, the two new tests, the TEMP precondition and the note to the lead about sr-pack-4a's harness.

## Decision (the lead's design, followed)

`--link NAME=DIR` is now also refused when DIR is inside a git repository. That means DIR, or any ancestor of its
physical path:

- holds a `.git` entry: a directory, the file a linked worktree or submodule has, or a link; or
- is itself a git directory, holding a `HEAD` file and `objects/` and `refs/` directories. That is git's own test for a
  git directory, and it covers a bare repository and a directory inside a `.git` directory.

The message gives the reason: `--link NAME: DIR is inside the git repository R; a dependency tree inside a repository
lets the checkout reach that repository's history and files through '..' (Item 2)`. The existing pack/source check is
kept, unchanged and first, so its message ("... holds the accepted fix (Item 2)") and every existing case read as before.
The script refuses before it creates anything, so neither the target nor its parent is made.

### One check: a filesystem walk, not `git rev-parse`

I kept a single check, a walk up the physical parents that reads only the filesystem, and did not use
`git -C DIR rev-parse --is-inside-work-tree / --is-inside-git-dir / --is-bare-repository`. The reason is that `..`
walks exactly those physical parents, and git's repository discovery has stopping rules that `..` does not have:

- discovery stops at a filesystem boundary unless `GIT_DISCOVERY_ACROSS_FILESYSTEM` is set;
- it errors on a repository another user owns (`safe.directory`, "dubious ownership"), so that case would need its own
  fail-closed branch;
- it honours `GIT_DIR`, `GIT_WORK_TREE` and `GIT_CEILING_DIRECTORIES` from the host's environment, which the design
  would have had to unset;
- it ignores a `.git` file it cannot parse.

None of these stops a `..` from reaching the files and the history (from git's documentation, not tested here). The walk
spawns no git process and needs no environment cleaning. Its cost is a false refusal for a stray `.git` or
`HEAD`+`objects/`+`refs/` that is no repository. That fails closed, which is the right side for a guard.

### DIR's own symlinked entries: checked

Every symlink among DIR's top-level entries, dot entries included, gets the same two checks on the physical path it
resolves to: the pack/source check and the repository check. A directory link resolves through `cd -P`. A file link is
followed hop by hop (at most 40 links): each hop's directory is made physical with `cd -P` before a relative target is
joined to it, so the result is the file the kernel reaches. A link that does not resolve is refused, not skipped,
because a dangling link can be made to point anywhere later. Links that stay inside DIR (a pnpm-style store) or reach a
directory outside every repository are accepted.

Why check them: a directory of links into a clone's `node_modules` is the same leak one level down.
`node_modules/<pkg>/../../` is the clone. Without the check, a host could get past the new rule by wrapping the clone's
entries in a directory of its own. That is exactly what sr-pack-4a's own test fixture does (see "For the lead").

What is still not checked, as the docs say plainly: anything deeper than DIR's top level. A symlink, or a repository,
further down the dependency tree is not followed and is the host's to avoid. I rejected a full recursive scan. It means
one `cd -P` per link over thousands of links (pnpm, `.bin` on POSIX), it is slow under Git Bash, and resolving file links
portably without `realpath`/`readlink -f` makes it fragile. A partial depth such as `@scope/<pkg>` would be specific to
npm's layout, and the kit is not npm-specific.

## Files

- `tools/calibration/historyless-checkout.sh`: the header's `--link` paragraph; `repo_holding`, `physd`, `resolve` and
  `guard_link` (the old pack/source loop moved into `guard_link`, with its message unchanged); the top-level symlink loop.
- `tools/test_calibration_kit.py`: the helpers `repo_holding` (the same walk in Python), `TEMP_IN_REPO` and
  `native_links`; in `Scripts`, `assert_link_refused` and `other_repositories` and two new tests; one precondition line
  in `test_historyless_checkout_links_only_on_request_and_hides_the_links`.
- `tools/calibration/README.md`: step 3 (Checkouts). It says to install outside every repository, what is refused and
  why, that top-level links are checked (followed as the kernel follows them), and that nothing deeper is.
- `tools/calibration/subject-pack/README.md`: the Isolation sentence and `checkout.links`.
- `CHANGELOG.md`: one clause folded into sr-kit-cases' existing "Calibration kit: run 4 case keys" line (no new line).
- This report.

## Tests

- `test_historyless_checkout_refuses_a_link_inside_a_git_repository`. Fixtures: `other` (a work tree with a commit), a
  linked worktree `wt` of it (its `.git` is a file, asserted) and `bare.git` (a bare repository with no `.git`,
  asserted), all beside the pack under the temporary directory. Each of these directories is refused with exit 2, with
  "is inside the git repository", and nothing is made (neither the target nor its fresh parent): `other`,
  `other/node_modules`, `other/node_modules/pkg`, `other/.git/info`, `wt/node_modules`, `bare.git` and
  `bare.git/refs`. Each is tried both with and without `--pack`. The full reason ("... history and files through
  '..'") is checked once. A directory outside every repository is accepted as before: exit 0, a real symlink resolving
  to it, `git status` clean.
- `test_historyless_checkout_checks_the_symlinks_at_the_top_of_a_linked_directory`. DIR is outside every repository,
  holds a plain directory, and has one top-level link. That link reaches, in turn: a directory in a work tree, a file in a
  work tree, a linked worktree (through a dot entry), a bare repository's `objects`, the pack repository's `src`
  ("holds the accepted fix"), and nothing at all ("does not resolve"). Then the two chain cases added in this round
  (`deps-chain`, `deps-dotdot`), each refused naming the repository `far/y`; the test first asserts that `far/x` is in
  no repository, that the chain reads the repository's file (Python for `deps-chain`; bash, from inside the directory,
  for `deps-dotdot`, since Windows' own API takes `sub/..` by spelling). Every case is refused with exit 2, with and
  without `--pack`, and nothing is made. A DIR whose links stay inside it, or reach a directory outside every
  repository, is accepted.
- TEMP independence. Each test that needs `--link` to accept a directory it made under the temporary directory first
  asserts that the temporary directory is in no repository. If it is, the test fails with "set TEMP outside any
  repository to run this test" and does not pass silently. I checked that the gate's TEMP (the gittoken `.tmp-gate`
  folder) and every ancestor up to Git Bash's `/` hold no `.git`, `HEAD`, `objects` or `refs` entry (`ls -a` on each)
  (verified). The suite's green run confirms it.
- Both new tests need Python to make symlinks (`NEEDS_PY_LINKS`). The accepting halves run Git Bash's `ln -s` with
  `MSYS=winsymlinks:nativestrict` (`native_links`), so on Windows they check a real link and not a copy. Other hosts
  ignore `MSYS`.

## Red first (re-run in this round)

Scratch copies outside the repository (`tools/test_calibration_kit.py`, `tools/calibration/`,
`tests/fixtures/calibration/`), `MSYS=winsymlinks:nativestrict`, the eight `Scripts` tests of the checkout script
(`bash -n` and the seven `historyless_checkout` tests):

| Script | Result |
|---|---|
| 09b476d's | 2 FAIL: `refuses_a_link_inside_a_git_repository` (`0 != 2` on `other`: the old script made the checkout) and `checks_the_symlinks_at_the_top` (`0 != 2` on `deps-0`, `lib` linking into `other`). Verified |
| the staged draft's `resolve` (R11 below) | 1 FAIL: `checks_the_symlinks_at_the_top`, `0 != 2` on `deps-chain`. Verified |
| this commit's (control) | 8 OK, none skipped. Verified |

## IC4-1 reproduced, and refused after the change (re-run in this round)

A scratch source repository under `.tmp-gate`, `MSYS=winsymlinks:nativestrict`, and
`historyless-checkout.sh --link node_modules=<clone>/node_modules`:

- With the 09b476d script: exit 0. `readlink node_modules` names the clone's `node_modules`. In Git Bash,
  `head -1 node_modules/../docs/orchestration/2026-10-13-github-sign-in/briefs/fix-x2-1.md` (spelled from inside the
  checkout) prints "# Unit fix-x2-1: a crash before commit followed by an unreadable start must not lose the account
  (X2-1, S3)" (verified).
- With the new script: exit 2, `refused: --link node_modules: <clone>/node_modules is inside the git repository <clone>;
  a dependency tree inside a repository lets the checkout reach that repository's history and files through '..'
  (Item 2)`, and the target does not exist (verified).

The clone was only read. Before and after, `git --no-optional-locks status --porcelain --ignored` gives the two lines
integration check 4 recorded (`!! node_modules/`, `!! research/raw/.diagnostics.jsonl`) and `ls -A node_modules` counts
357 entries (verified). I removed the old-script checkout by first removing its `node_modules` link with a plain `rm`
(no `-r`), then the checkout.

## Guard-removal proofs (re-run in this round)

A driver applied each mutation to a scratch copy (each substitution asserted to apply exactly once), checked it with
`bash -n` (all passed), and ran the same eight tests as above with `MSYS=winsymlinks:nativestrict`. I read each failure
to confirm it is the intended case, not a precondition.

| Guard removed or weakened | Tests that went red (where) |
|---|---|
| R1 the `.git`-entry clause | inside_a_git_repository (`other`), symlinks_at_the_top (`deps-0`) |
| R2 `.git` accepted only as a directory (a worktree's `.git` file passes) | inside_a_git_repository (`wt/node_modules`), symlinks_at_the_top (`deps-2`, `.hidden` to the worktree) |
| R3 the git-directory clause (`HEAD`+`objects/`+`refs/`) | inside_a_git_repository (`bare.git`), symlinks_at_the_top (`deps-3`, into `bare.git/objects`) |
| R4 no ancestor walk (DIR itself only) | inside_a_git_repository (`other/node_modules`), symlinks_at_the_top (`deps-0`) |
| R5 the repository check skipped for DIR itself (entries only) | inside_a_git_repository (`other`) |
| R6 no top-level symlink loop | symlinks_at_the_top (`deps-0`) |
| R7 a link that does not resolve skipped, not refused | symlinks_at_the_top (`deps-5`) |
| R8 dot entries not listed | symlinks_at_the_top (`deps-2`) |
| R9 a file link not resolved (refused as unresolvable, the wrong reason) | symlinks_at_the_top (`deps-1`) |
| R10 a top-level link not checked against the pack/source | symlinks_at_the_top (`deps-4`, wrong reason) |
| R11 the staged draft's `resolve` (relative target joined to the unresolved directory) | symlinks_at_the_top (`deps-chain`) |
| R12 `physd` as a plain `cd` (`..` taken by spelling) | symlinks_at_the_top (`deps-dotdot`) |
| R13 an absolute link target joined as if relative | symlinks_at_the_top (`deps-1`, wrong reason) |

## Checks

| Check | Result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` (whole file, this commit's tree) | 118 tests OK, 1 skipped (501 s). The skip is `links_only_on_request` (Git Bash's `ln -s` copies without `MSYS`); it ran green in the guard control with `MSYS` set. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations (unchanged). Verified |
| `python tools/check_secrets.py` | clean (0 hits). Verified |
| LF endings of the five changed files and this report (`git ls-files --eol`) | `i/lf w/lf` for all six. Verified |
| No absolute host path, session id or run id in the changed kit files (grep) | none. Verified |
| The full regression gate through the pre-commit hook | passed: the commit exists only if it passed |

Every check ran with TEMP and TMP set to the gittoken `.tmp-gate` folder on drive C.

Expected, untested: hosts other than this Windows / Git Bash one. The walk and the link resolution use only POSIX shell,
`cd -P`, `pwd -P`, `dirname`, `basename` and `readlink` without options, so I expect them to behave the same on Linux and
macOS, but I ran nothing there. The claims about git's discovery rules come from git's documentation and were not tested
here.

## For the lead

1. **sr-pack-4a's test harness will be refused once it sits on this commit.** `x21_shell_modules` (sr-pack-4a's
   `tools/test_calibration_kit.py`) makes a `node_modules` of its own whose every entry links to the clone's entries.
   HostPackX21 then passes it, or the clone's `node_modules` itself, to `--link`. The new checks refuse both: the
   clone's directory is inside the clone's repository, and the shell's top-level links resolve into it. The refusal is
   correct, because `node_modules/<pkg>/../../` from such a checkout is the clone, which is IC4-1 again. IC4 said "the
   kit's own tests may keep linking the clone", but under this guard they cannot. The pack's tests need the same install
   the README fix needs: `npm ci` from base0's `package.json` and `package-lock.json` in a directory that is no
   repository (for example, a history-less checkout of `base0` made outside the pack, under TEMP). That is sr-pack-4a's
   change, not this unit's.
2. `tools/calibration/run.template.js` line 71 (a comment) still says `--link` "refuses a directory inside the pack or
   its repository". That is true but no longer the whole rule. The file is outside the files this change may touch, so I
   left it. One clause ("or inside any git repository") would complete it.
3. A Git Bash host without `MSYS=winsymlinks:native*` gets a copy from `--link`, not a link. That predates this change
   (and is why the older acceptance test skips here). A copy reaches nothing through `..`, so it is no leak, but it can
   be large.
4. On Windows, the candidate's tools disagree about `link/..`: Windows' own API (Node, Python, git) takes it by spelling,
   Git Bash's tools follow the link. The guard follows the link (the POSIX reading), which is the stricter of the two for
   a refusal.

## What I got wrong and fixed

From the stopped run (as its draft recorded): a bash heredoc the tool's shell wrapper could not parse (nothing was
written; re-run from a file); a first red-first run without `MSYS`, where the second test failed on Git Bash's copy of a
directory holding a symlink rather than on the guard (re-run with `MSYS=winsymlinks:nativestrict`); and a `C:/...`
spelling of the checkout path in the IC4-1 reproduction, which MSYS resolves lexically (re-run with the relative
`node_modules/../` spelling).

In this round:

- The draft's `resolve` let a chain of file links through a linked directory past the guard (above). It was not caught
  because no test had a link whose target walks `..` after a linked directory. I fixed the resolution and added the two
  cases and R11-R13.
- My first run of the new `deps-dotdot` precondition gave bash the `C:\...` spelling of the link, which Git Bash hands to
  Windows' own API, so `cat` failed (ENOENT) and every guard variant went red on that precondition, not on the guard. I
  caught it because the control copy was red too; the test now reads `c` from inside the directory, and I re-ran the
  whole guard table after the fix.
