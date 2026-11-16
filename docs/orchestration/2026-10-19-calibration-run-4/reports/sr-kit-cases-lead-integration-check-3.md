# sr-kit-cases, lead integration check 3 (refute-first, fresh context): IC4-1 and LC2-1..3 after lead integrations 2 and 3

Checked: branch `build/sr-kit-cases` at bea034a (lead integration 3) on 331ed32, with lead integration 2 (69d1d03), all
against 09b476d. I read it against IC4-1 (sr-pack-4a integration check 4), check 2's findings LC2-1, LC2-2 and LC2-3,
and the two integration reports. I wrote none of the change. This report is the only file this round adds. Every run
had TEMP and TMP on the gittoken `.tmp-gate` folder. I only read the MoonAliza clone: its `git status --porcelain
--ignored` is the same before and after every run that touched it (`!! node_modules/`, `!! research/raw/.diagnostics.jsonl`).
Below, `<scratch>` is a fixture folder under `.tmp-gate`, and `<guid>` is the C: volume's GUID.

**Verdict: FIX**, for one S3 (LC3-1). The claims about the spellings check 2 named hold: UNC spellings
(`//host/share`, `\\host\share`, `\\?\UNC\...`, `//?/UNC/...`, `//./C:/...`, `//127.0.0.1/...`, any case) are refused
wherever a check needs them. Case, 8.3 short names, `\\?\C:\...`, `//?/C:/...`, `/proc/sys/DosDevices/...` and
`/proc/cygdrive/...` spellings name the same directory and are refused. Junctions, symlink chains and relative links
into a repository are refused. Git's repository variables are dropped. The rendered prompts are byte-identical to
09b476d. But one kind of Windows symlink is invisible to the guard: a link whose target is a volume-GUID path
(`\\?\Volume{<guid>}\...`) or a `\\?\GLOBALROOT\...` path. Git Bash does not see it as a link: `[ -L ]` is false,
`readlink` prints nothing, and `pwd -P` keeps the link's own path. Native programs follow it. So
`--link node_modules=<a GUID link to the MoonAliza clone's node_modules>` is accepted, and in the checkout
`git -C node_modules log --oneline -1 01a8604` prints the accepted fix (LC3-1). That is IC4-1 itself, through one
indirection. Four S4s do not block.

## Findings

| id | severity | finding |
|---|---|---|
| LC3-1 | S3 | **A volume-GUID or GLOBALROOT symlink defeats the DIR check, the top-level check and the target check.** Python's `os.symlink(r'\\?\Volume{<guid>}\<path>', link, target_is_directory=True)` makes such a link without admin rights (developer mode, the same way the kit's tests make links). Under Git Bash (MSYS2), `[ -L link ]` is false, `stat` says `directory`, `readlink` is empty, and `cd -P link; pwd -P` prints the link's own path. Listing works (`ls link` shows the target's entries), and `link/..` is the link's own parent. Native programs follow it: Python `os.path.realpath` returns the target, and Git for Windows' repository discovery walks up the target's real path (its `getcwd` resolves the final path). **Reproduced:** (a) **IC4-1 itself.** `<scratch>/L/vclone -> \\?\Volume{<guid>}\...\moonaliza-gsi-build\node_modules`; `--pack <pack> --link node_modules=<scratch>/L/vclone`: exit 0, "ok". In the checkout, `git -C node_modules rev-parse --show-toplevel` prints the clone's root, `cat-file -t 01a8604` prints `commit`, and `log --oneline -1 01a8604` prints the accepted fix's subject. The 09b476d script accepts it too. (b) A clean DIR whose only top-level entry `s` is a GUID link to the **source repository**, with `--pack <source>`: exit 0. In the checkout, `git -C node_modules/s log --oneline` prints the source's `fix` commit, and `show --stat` shows its diff. The top-level loop skips `s` because `[ -L ]` is false. So the docs' promise does not hold for it: each top-level symlink "is checked ... on the real path it resolves to ..., and one that does not resolve is refused". This one is neither checked nor refused. (c) The same with a `\\?\GLOBALROOT\DosDevices\C:\...` target: DIR accepted, and `git -C node_modules log` prints the other repository's history. (d) An ordinary symlink to a GUID link (a chain) as DIR: accepted, with the same leak. (e) **The target check.** `--pack <pack>` with TARGET `<scratch>/L/vpackdeep/co-x`, where `vpackdeep` is a GUID link to `<pack>/work/deeper`: exit 0, and `co-x` is created physically inside the pack. A plain symlink there is refused ("is inside the pack"). A GUID link straight to the source or the pack *as DIR* is refused, because `-ef` sees through it ("shares a path with ..."). What is lost is only the ancestors: the guard walks the link's own parents, not the target's. **Why S3, as LC2-1:** this breaks the guard's own documented promise and Item 2 on the host the kit runs on: no path from a checkout reaches the accepted fix. It is not S2, because a host has to make such a link, and the README's procedure does not. It is not from integrations 2-3 alone: the DIR half predates them. But both rounds claim to close exactly this class ("by identity", "the parents both Git Bash and native Windows programs walk"). **Fix (the lead decides):** the guard's real path has to be the one native programs use. Two options. (1) On Windows (cygpath present), ask Windows: for DIR, each top-level entry, and TARGET's parent under `--pack`, get the final path from a native call, and walk that path's parents too. (2) Fail closed: refuse any path component or top-level entry that Windows reports as a reparse point but Git Bash does not show as a link. A third, partial check is native discovery: Git for Windows' `git -C <path> rev-parse --absolute-git-dir` with `GIT_CEILING_DIRECTORIES` unset finds the repository in (a), (c) and (d). Add tests that make a GUID link with `os.symlink` and a `mountvol` lookup, and skip when either is unavailable. |
| LC3-2 | S4 | **Not from this change: a git template can give the checkout another repository's objects.** `GIT_TEMPLATE_DIR` (or `init.templateDir` in the host's global config) is not one of `--local-env-vars`. `git init` copies the template into the new `.git`. With a template holding `objects/info/alternates` -> the source's `.git/objects` and an empty `info/exclude`, the script exits 0, "ok". In the checkout, `git show 7d35a8c:fix.txt` prints the accepted fix's content, and `git log 7d35a8c` its history. The final proof counts commits reachable from refs, so it does not see the borrowed objects. The same holds with `init.templateDir` in `GIT_CONFIG_GLOBAL`. The header's promise ("the accepted fix is not an object the candidate's git can reach") then fails, but only through a host's deliberate template. **Fix:** `git init --template=` (no template), or a `-c init.templateDir=` override with `GIT_TEMPLATE_DIR` unset. The proof could also refuse a target with `objects/info/alternates`. |
| LC3-3 | S4 | **Not from this change: a target refusal creates directories first, inside the pack too.** `mkdir -p "$PARENT"` runs before the target checks. `--pack <pack>` with TARGET `<pack>/new/sub/co` is refused ("is inside the pack"), but it leaves `<pack>/new/sub`. A TARGET under a missing UNC parent is refused only after the parent was made on the share (the new UNC refusal sits after the same `mkdir`). The `--link` refusals happen before it, as check 2 found. Empty directories are not tracked by git, so nothing leaks. Still, "nothing is created on refusal" holds only for `--link` and argument refusals. **Fix:** check the target's parent before making it, by resolving its nearest existing ancestor. |
| LC3-4 | S4 | **Not from this change: a checkout placed inside a git repository is accepted.** With `--pack` given, TARGET `<scratch>/other repo/co-z` is accepted, and `ls -a co-z/..` lists that repository's `.git`. `--pack` refuses only the pack and what lies under it. A checkout root inside the subject clone, or inside the repository that holds the pack directory (beside it, not in it), would hand the candidate the same history IC4-1 was about. The docs do not tell the host to do this, and they do not forbid it either. **Fix:** apply `is_repo` along the target parent's ancestors, as for `--link`, or name the rule in README step 3. |

## Claims, attacked

Fixtures under `<scratch>`: `src` (two commits: base and `fix`), `other repo` (a work tree with a space in its name and
`node_modules/pkg`), `wt` (its linked worktree, a `.git` file), `bare.git/deps`, `free dir/node_modules` (outside every
repository), and `pack/` (a manifest, outside every repository). Hermetic git config. `MSYS=winsymlinks:nativestrict`
for the link cases. "made" means the target's parent exists afterwards.

| attack | result |
|---|---|
| control: DIR outside every repository (plain, as `//?/C:/...`, as `/proc/sys/DosDevices/C:/...`, with spaces in DIR and NAME) | accepted, exit 0; NAME with a space is excluded as `/node modules` |
| IC4-1: `--link node_modules=<clone>/node_modules`, with and without `--pack` | refused, exit 2, not made; clone status unchanged |
| DIR inside a work tree, a linked worktree (`.git` file), a bare repository, a `.git/objects` | refused, not made |
| DIR as `C:\...`, `C:/...`, upper case, lower case, 8.3 short name (`TMP-GA~1\...\OTHERR~1\NODE_M~1`, three spellings) | refused (identity) |
| DIR as `\\?\C:\...`, `//?/C:/...`, `\\?\Volume{<guid>}\...` (forward slashes), `/proc/sys/DosDevices/C:/...`, `/proc/cygdrive/c/...` | refused: each resolves to `/c/...` |
| DIR as UNC: `//localhost/C$/...`, `//LOCALHOST/c$/...`, `\\localhost\C$\...`, `\\?\UNC\localhost\C$\...`, `//./C:/...`, `//127.0.0.1/...` (a free dir) | refused, "is not a local path", not made |
| DIR as the source, the source's `.git`, the folder holding the source, `/`, `C:/` | refused ("shares a path") |
| DIR as `E:/`, `/tmp` | accepted (no repository, does not hold the source) |
| DIR as a junction chain, a symlink chain to that junction chain, `junction-to-repo/node_modules` | refused |
| top-level entry: a junction into a repository, a symlink chain, a relative link `../../other repo`, a file link into a repository, a dot entry, a link through `j1/..`, a link to a `.git` file, a link to a bare repository | all refused |
| top-level entry: `\\?\C:\...`, `\\?\C:\` in upper case, `\\?\UNC\localhost\...`, `\\localhost\C$\...` | refused (identity, or "not a local path") |
| top-level entry: `\\?\Volume{<guid>}\...` or `\\?\GLOBALROOT\...` into a repository | **accepted (LC3-1)** |
| DIR: a GUID link, a GLOBALROOT link, or a symlink chain ending in one, into a repository's `node_modules`, including the MoonAliza clone's | **accepted (LC3-1)**; a GUID link straight to the source is refused (`-ef`) |
| `subst Q: <other repo>\node_modules`, DIR `Q:/` or `/q` | accepted. Git Bash's `/q/..` is Git's `/`, and a native `..` stops at `Q:\`, so `..` does not reach the repository. `subst Q: <other repo>`, DIR `Q:/node_modules`: refused. (`subst` removed afterwards) |
| a junction whose target is a volume-GUID path | Windows does not resolve it; refused, "no directory" |
| `--pack`, `--link` source, or target parent spelled UNC | refused, each with its own message ("the pack", "the source repository", "its parent") |
| a source spelled UNC, no flags | refused, "not a commit" (git's dubious ownership); not made |
| a stub `cygpath` that fails | refused (fails closed; the message says "not a local path") |
| `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_COMMON_DIR` naming `other repo`, plus `GIT_CEILING_DIRECTORIES`, `GIT_DISCOVERY_ACROSS_FILESYSTEM=0`, `GIT_NAMESPACE`, `GIT_REPLACE_REF_BASE`, `GIT_GRAFT_FILE`, `GIT_SHALLOW_FILE`, with `--pack` and an accepted link | exit 0; one commit, clean status; every file of `other repo` byte-identical (md5 of all files before and after) |
| `GIT_DIR=<other repo>/.git` with the IC4-1 shape; `GIT_CEILING_DIRECTORIES=<other repo>` | refused (the walk reads the filesystem) |
| `GIT_ALTERNATE_OBJECT_DIRECTORIES=<src>/.git/objects` | dropped: the checkout has no alternates |
| `GIT_TEMPLATE_DIR` / `init.templateDir` with `objects/info/alternates` | **accepted, the fix's objects readable (LC3-2)** |
| an exported `CDPATH` naming a repository, relative DIR | not honoured by the script's `cd` (DIR resolved in the working directory) |
| `--pack` with a target inside the pack, a target through a plain symlink into the pack | refused, but the parent is made first (LC3-3) |
| a target inside the pack through a GUID link | **accepted, the checkout made inside the pack (LC3-1 e)** |
| a target inside another git repository | accepted (LC3-4) |

## Rendered prompts

A scratch driver (outside the repository) renders `run.template.js` at 09b476d and at HEAD through the test module's
own `run_config` / `execute_template`, with `GOLDEN_HOST`. It covers the fixture manifest and the shared pack's
manifest, each with `cause_in_prompt` absent, true and false. It compares every call (label, prompt and all fields)
as sorted JSON. Result: **60 calls compared, 0 differ**. The fix prompts' sha256 prefixes are `5e66cf5f4d0c141c`
(fixture) and `54a0353d503c950d` (shared), the `FIX_PROMPT_GOLDEN` values. The template change is a comment only.
Verified.

## Diff, docs, CHANGELOG

- `git diff --stat 09b476d HEAD` touches nine files: `historyless-checkout.sh`, `test_calibration_kit.py`, the kit
  README, the subject-pack README, `run.template.js` (a comment, LI2), `CHANGELOG.md`, and three reports
  (integration 2, check 2, integration 3). These are the files the reports name. Verified.
- CHANGELOG: numstat 1/1 against 09b476d. The clause is folded into the existing "Calibration kit: run 4 case keys"
  line, and `test_k6_one_changelog_line` passes in the full suite. The clause matches the behaviour except under
  LC3-1 ("a top-level symlink in it that reaches one or the pack", "compares paths by identity along the shell's and
  Windows' parents"). Verified.
- The header and both READMEs describe what the script does. Exceptions: LC3-1 (the README's "along the parents both
  Git Bash and native Windows programs walk" does not hold for a GUID link), and the fact that "nothing is created on
  refusal" is not claimed for target refusals, which do create directories (LC3-3). The deeper-entries gap is stated
  plainly. Verified.
- LF: `git ls-files --eol` gives `i/lf w/lf` for all eight files the commits added or changed. In the added lines,
  the kit files hold no absolute host path, session id, run id or model name. The only absolute path is in check 2's
  report text. Verified.
- Integration 3's commit message has the five parts and names the model only in the trailer. Verified.

## Guard-removal proofs (re-run, my own driver)

Each mutation ran in its own scratch copy of `tools/test_calibration_kit.py`, `tools/calibration/` and
`tests/fixtures/calibration/`. Each anchor had to match exactly once, and every copy passed `bash -n`. Each copy ran
the 12 checkout tests in `Scripts` (`bash -n` plus the 11 historyless tests) with `MSYS=winsymlinks:nativestrict`,
six copies at a time. I read the failure messages of N1-N5 to confirm each fails for its own case. For example, N1's
UNC case fails with "inside the git repository //localhost/..." instead of "is not a local path", and N4 accepts
`PACK/extra`.

| mutation | red tests |
|---|---|
| control | none: 12 OK, 0 skipped (562 s) |
| N1 a UNC spelling walked, not refused | unc_path; windows_parents |
| N2 `canon` always collapses `//` | unc_path |
| N3 no Windows spelling (`WINPATHS=""`) | windows_parents |
| N4 "inside" by spelling (`=` for `-ef`) | identity; windows_parents |
| N5 "holds" by spelling | identity |
| N6 target-in-pack by spelling | identity |
| N7 no `unset` | git_repository_variables |
| N8 `add_guard` ignores a non-local path | unc_path |
| N9 the target-parent check ignores a non-local path | unc_path |
| N10 `guard_link` ignores a non-local path | unc_path; windows_parents |
| N11 the shell spelling not walked | link_that_reaches_the_pack; existing_target_and_one_inside_the_pack |
| R1 no `.git` clause | inside_a_git_repository; symlinks_at_the_top; windows_parents |
| R3 no git-directory clause | inside_a_git_repository; symlinks_at_the_top |
| R4 only DIR itself checked, no ancestors | inside_a_git_repository; symlinks_at_the_top; windows_parents |
| R6 the top-level loop skips every entry | symlinks_at_the_top; unc_path; identity |
| M10 (mine) the target's parent made before the checks | 5 tests (each asserts that nothing was made) |
| M12 (mine) `resolve` stops after one hop | symlinks_at_the_top |
| M13 (mine) `physd` as a plain `cd` | symlinks_at_the_top |
| M14 (mine) a dangling top-level link skipped | symlinks_at_the_top |
| M15 (mine) dot entries not listed | symlinks_at_the_top |

These reproduce integration 3's N1-N11, R1, R3, R4 and R6 with the same red tests. M12-M15 re-cover the `resolve`
and loop proofs that integration 3 did not re-run. No test covers LC3-1: the control passes while the GUID links above
are accepted.

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` at bea034a (no `MSYS`) | 122 tests OK, 1 skipped (`links_only_on_request`: Git Bash copies without `MSYS`), 770 s, exit 0. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

Untested: hosts other than this Windows / Git Bash one. On Linux there are no GUID links and no `cygpath`, so LC3-1
is expected not to apply. Expected, not run. A real MSYS mount is still modelled only by integration 3's stub.

## For the lead

1. LC3-1 (S3): make the guard use the path native programs resolve. Either resolve DIR, each top-level entry, and
   TARGET's parent under `--pack` with a native final-path call and walk those parents too, or refuse a reparse point
   that Git Bash does not show as a link. Add a test with a `\\?\Volume{...}` link made by `os.symlink`, for DIR, for
   a top-level entry, and for a target parent.
2. LC3-2 (S4, older): `git init --template=`, and refuse alternates in the proof.
3. LC3-3 (S4, older): no `mkdir` before the target checks.
4. LC3-4 (S4, older): refuse a target inside any git repository, or document the rule.

## What I got wrong and fixed

- My first 8.3 and `\\?\` probes were broken by quoting. The `cmd for %~sI` call returned a mangled path, and the
  tool wrapper halved the backslashes in `'\\?\'`. Those runs were refused as "no directory": they tested missing paths,
  not the guard. I re-made the spellings with `GetShortPathNameW` and `printf '\134'` and re-ran them. Only the re-runs
  are cited.
- PowerShell `New-Item -ItemType SymbolicLink` needs admin rights on this host, and my `cmd mklink` quoting failed. So
  my first GUID-link "accept" (`top-vol`) tested a DIR with no link in it. I made the links with Python `os.symlink`
  (unprivileged create), checked each with `os.readlink`, and re-ran. Only those runs are cited.
- My first `GIT_*` run fed the variables to my own helper's `git rev-parse` too, so the commit argument was wrong
  (refused "not a commit"). `GIT_REPLACE_REF_BASE=refs/x` without a trailing slash also tripped a git BUG assertion. I
  computed the commit once beforehand, fixed the value and re-ran.
- My first stub-`cygpath` run put `C:/...` on PATH, so the colon split the entry and the stub was never found (it
  falsely looked accepted). I re-ran with the `/c/...` spelling, and it refuses.
- My first template run exited 1 only because my template lacked `info/exclude`. I added one and re-ran: "ok", with
  the fix readable (LC3-2).
