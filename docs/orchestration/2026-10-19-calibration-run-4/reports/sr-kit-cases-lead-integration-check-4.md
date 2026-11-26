# sr-kit-cases, lead integration check 4 (refute-first, fresh context): IC4-1 and LC3-1..4 after lead integration 4

Checked: branch `build/sr-kit-cases` at 91c0485 (lead integration 4) on 16ef0a5, with lead integrations 2 and 3, all
against 09b476d. I read the change against IC4-1 (sr-pack-4a integration check 4), check 3's LC3-1..LC3-4, and the
reports of integrations 2-4. I wrote none of the change. This report is the only file this round adds. Every run had
TEMP and TMP on the gittoken `.tmp-gate` folder, and the link cases ran with `MSYS=winsymlinks:nativestrict`. I only
read the MoonAliza clone. Its `git status --porcelain --ignored` is the same before and after every run that touched
it (`!! node_modules/`, `!! research/raw/.diagnostics.jsonl`). Below, `<fx>` is my fixture folder under `.tmp-gate`.

**Verdict: FIX**, for one S3 (LC4-1). The claims of integration 4 hold for what it names:

- every link class I tried that Git Bash cannot see is resolved natively and refused;
- the target checks run before anything is made;
- no template is copied;
- the rendered prompts are byte-identical to 09b476d;
- every guard-removal proof goes red.

But "inside any git repository" is decided by the script's own copy of git's repository test, `is_repo`, and that copy
is incomplete in both layers. Git itself recognises three directory shapes that `is_repo` does not, and from the
checkout `git -C node_modules log` prints the other repository's history, its fix commit included (LC4-1). That is
IC4-1's leak again, through a different gap in the same promise. Four S4s do not block.

## Findings

| id | severity | finding |
|---|---|---|
| LC4-1 | S3 | **`is_repo` is not the test git applies, so some directories that git treats as repositories pass as "outside every repository".** The header says a directory is a git directory when it holds "HEAD, objects/ and refs/, the test git itself applies". Git's `is_git_directory` differs in three ways, and each one let me through on this host (Git 2.55.0.windows.5, both layers): **(a) `commondir`.** Git reads `objects` and `refs` from the directory a `commondir` file names. This is the shape of a linked worktree's admin directory. `<fx>/commondir-gd` holds only `HEAD` and `commondir` (pointing at `<fx>/other/.git`), plus `sub/`. `git -C commondir-gd/sub rev-parse --absolute-git-dir` prints `commondir-gd`. `--pack <pack> --link node_modules=<fx>/commondir-gd/sub`: exit 0, "ok". In the checkout, `git -C node_modules log --oneline` prints `65047e1 f` and `487876f b`, and `show --stat HEAD` shows the fix's diff. TARGET `<fx>/commondir-gd/sub/co` is accepted as well ("ok"). **(b) A HEAD that is a dangling symlink.** Git's `validate_headref` accepts a symlink HEAD whose target starts with `refs/`, even when the ref is packed and the target file is missing. This is what `core.preferSymlinkRefs` leaves after `pack-refs`. `[ -f HEAD ]` and Python's `isfile` both reject it. With a bare clone, `pack-refs --all`, and HEAD replaced by a symlink to `refs/heads/main`: DIR `symhead.git/deps` is accepted, and `git -C node_modules log` prints the fix commit. **(c) `refs` as a file.** Git for Windows' `access()` drops `X_OK`, so a file named `refs` passes git's check, and the refs come from `packed-refs`. With a bare clone, `pack-refs --all`, `refs/` removed and a file `refs` in its place: git discovers the directory, DIR `refsfile.git/deps` is accepted, and the checkout's `git -C node_modules log` prints the fix commit. **Why S3 (the rubric of LC2-1 and LC3-1):** the guard's documented promise and Item 2 fail on the kit's own host: no path from a checkout reaches the accepted fix, and a directory inside any git repository is refused. It is not S2: the README's procedure does not produce these shapes, and a host must place the dependency tree inside an unusual git directory. It is not from round 4 alone: the predicate dates from round 2. But round 4 mirrors it in the native layer, and the header claims it is git's own test. **Fix (the lead decides):** make the predicate fail closed and match git in both layers. For example, a directory is a git directory when it holds a `HEAD` entry of any type (`-e \|\| -L`, `lexists`) and either a `commondir` entry, or `objects` and `refs` entries of any type, with the `.git` clause unchanged. Then add tests for (a), (b) and (c), for DIR, a top-level link and TARGET, in both layers (a GUID link to each). |
| LC4-2 | S4 | **"Windows Python 3.8+" is wrong: the native check needs 3.10+.** `os.path.realpath` gained `strict` in Python 3.10 (docs.python.org, os.path: "Changed in version 3.10: The strict parameter was added"). The probe accepts 3.8 and 3.9. Under them, `realpath(path, strict=True)` raises `TypeError`, which `final()` does not catch. The heredoc exits 1, and every checkout is refused with "the native path check failed (exit 1)". That fails closed, so no leak. But the header, README step 3, the probe's own message and the commit message all promise 3.8+. Expected from the documented signature; not run, because this host has only 3.14. **Fix:** probe for `>= (3, 10)` and say 3.10+. |
| LC4-3 | S4 | **The threat model does not say that the guard knows repositories only by their markers.** The guard refuses a DIR whose ancestry holds a `.git` entry or a git directory. It cannot refuse a subject's *files* outside a repository. Reproduced: a work tree whose git directory lies elsewhere (`core.worktree`; `<fx>/detached-wt` checked out from `<fx>/store/r.git`) is accepted as `--link node_modules=<fx>/detached-wt/node_modules`. In the checkout, under Git Bash, `ls node_modules/../` lists `docs`, `node_modules` and `secret.txt`, and `cat node_modules/../secret.txt` prints the fix's file. Git discovery finds nothing there, so the history is not reached. The same holds for a copy or `git archive` export of the subject. MoonAliza's 16f637f itself carries `docs/orchestration/` (IC4-2), so a host who strips `.git` from a clone to get past the refusal hands over the brief. The README names only deeper links and repositories as the host's duty, and the refusal message ("a dependency tree inside a repository ...") can read as "remove the `.git`". **Fix:** in the header and README step 3, say that the guard detects repositories, not content. A directory whose parents hold any of the subject's files (an export, a copy, a work tree whose git directory lies elsewhere) is the host's to avoid. The recommended install location (a history-less checkout of the case base, outside the pack) stays the safe one. |
| LC4-4 | S4 | **Two guards no test can see removed.** (1) The `FILE_ATTRIBUTE_REPARSE_POINT` half of the native `is_link`. Integration 4 lists it as unproven. I proved that it works: with the shell's top-level loop disabled (R6), a DIR whose top-level entry `j` is a junction into a repository (Python 3.14: `is_symlink()` False, `is_junction()` True) is refused natively, and a junction to a free directory is accepted. With `is_link` reduced to `is_symlink()` as well, the same DIR is accepted, and `node_modules/j/` lists the repository's `docs`. No kit test makes a junction, so dropping that half leaves every test green. (2) `--link NAME` may name a path inside `.git`. `--link .git/hooks=<free dir>` is accepted, and the candidate's commits would then run hooks from a host directory (`.git/objects/info` and `.git` are accepted too, and the object proof still holds). That is no path to the fix, but nothing stops a mistyped NAME there. **Fix:** a junction case in the native test (`_winapi.CreateJunction`, under the R6-style pin), and refuse a NAME whose first segment is `.git`. |

## Claims, attacked

Fixtures under `<fx>`:

- `pack/` (not a repository), holding `repo` (base and `fix` commits) and `extra/`;
- `other` (a work tree with history, `node_modules/pkg`, `docs/`), its linked worktree `wt` (a `.git` file), and
  `bare.git/deps`;
- `free/node_modules`, outside every repository;
- links made with Python `os.symlink`, and junctions made with `_winapi.CreateJunction`.

Hermetic git config. "N" marks a refusal by the native layer ("as native programs resolve it"), "S" a refusal by the
shell layer. Every refusal below made nothing: no `out/tN` directory, and the watched trees are unchanged.

| attack | result |
|---|---|
| control: `free/node_modules`, with and without `--pack`; a GUID link to it; the Windows user temp directory on another drive (outside every repository) | accepted, exit 0 |
| IC4-1, with and without `--pack` (22 runs): the clone's `node_modules` directly | refused, S |
| a GUID link, `GLOBALROOT\DosDevices`, `GLOBALROOT\Device\HarddiskVolumeN` (new spelling), a plain symlink to the GUID link | refused, N |
| a `\\.\C:\...` link, a junction, a GUID link to the clone used as an ancestor (`gl/node_modules`) | refused, S |
| a clean DIR whose top-level entry is a GUID link to the clone, or a hidden `.h` `HarddiskVolume` link to it | refused, N |
| a top-level junction into the clone's `docs` | refused, S; with the shell loop disabled, refused N (LC4-4) |
| spellings of `other/node_modules`: 8.3 short name, upper case, lower case, `/proc/cygdrive/c/...`, `\\?\C:\...` (via `printf`), `//?/C:/...` | refused, S |
| UNC `//localhost/C$/...` | refused, "is not a local path" |
| `//./C:/...` of a free directory | refused, "no directory" (over-refusal only) |
| a Git Bash mount: `/tmp/...` (Git Bash mounts `/tmp` on the Windows user temp directory, another drive here) naming a repository's `node_modules` | refused, S |
| a linked worktree (`.git` file), a bare repository, `.git/objects`; a GUID link to the worktree, or to the bare repository | refused (S; N for the GUID links) |
| a `commondir` git directory, a symlink-HEAD bare repository, a `refs`-file bare repository | **accepted; the fix commit readable from the checkout (LC4-1)** |
| a `core.worktree` work tree with no `.git` in its ancestry | **accepted; its files readable through `node_modules/..` (LC4-3)** |
| `subst Q: <other>/node_modules`, DIR `Q:/` | refused, N (the shell layer alone accepts it) |
| `subst Q: <free>`, DIR `Q:/` | accepted |
| `subst Q: <pack>`, TARGET `/q/co` with `--pack` | refused, S ("inside the pack") |
| `subst Q: <other>/docs`, TARGET `/q/co`, with and without `--pack` | refused, N |
| TARGET through a GUID link into the pack (`--pack`), and through a `GLOBALROOT` link into `other` (both flag sets) | refused, N, nothing made |
| without `--pack`, a TARGET through a GUID link into `pack/extra` | accepted, as designed: `pack/` is no repository, and only `--pack` guards it |
| TARGET in a linked worktree, in `bare.git/refs` | refused, nothing made |
| TARGET in the `commondir` git directory | **accepted (LC4-1)** |
| `GIT_TEMPLATE_DIR` and `init.templateDir`, with a live `objects/info/alternates` template | accepted: no alternates, 3 objects, the fix not readable |
| `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_OBJECT_DIRECTORY`, `GIT_DIR`+`GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_CONFIG_PARAMETERS` and `GIT_CONFIG_COUNT`/`KEY`/`VALUE` setting `core.worktree` to `other` | accepted: 3 objects, the fix not readable, files `.git a.txt node_modules`; `other`'s status and HEAD unchanged |
| `--link .git/objects/info=`, `.git=`, `.git/hooks=` (free directories) | accepted (LC4-4) |

Not exercised (untested): a volume mounted at a folder with no drive letter (`mountvol` needs admin), a network drive
letter (`net use`), and hosts other than this Windows 11 / Git Bash one. The first two resolve, as native programs see
them, to a `\\?\Volume{...}` or UNC path, and the layer refuses those by the rule the Mup case proves (expected).

One drive-root spelling: a TARGET written `Q:/co` is refused with "no parent of it exists", because `dirname Q:` is
`Q:`. `/q/co` works. That is an over-refusal with an odd message, not a gap.

## Is the threat model now stated honestly?

Mostly. The header and README step 3 say what each layer resolves and that the native layer runs on Windows only and
fails closed. They say nothing deeper than DIR's top level is followed ("the host's duty"), and that UNC paths are
refused. Two statements are wrong or missing:

- "the test git itself applies" (LC4-1);
- "Windows Python 3.8+" (LC4-2).

One host duty is not named: a subject's files outside any repository (LC4-3). The subject-pack README and the CHANGELOG
clause match the behaviour, apart from the same "inside any git repository" caveat. `run.template.js` differs from
09b476d only in the round-2 comment.

## Rendered prompts

A scratch driver renders `run.template.js` at 09b476d (`git show`) and in the working tree through the test module's
`run_config` / `execute_template` with `GOLDEN_HOST`. It covers the fixture manifest and the shared manifest, each with
`cause_in_prompt` absent, true and false, and compares every call as sorted JSON. The grader, lens and cluster prompts
and `classification.md` are unchanged since 09b476d. Result: **60 calls compared, 0 differ**, and the results are equal.
The fix prompt sha256 prefixes are `5e66cf5f4d0c141c` (fixture) and `54a0353d503c950d` (shared), the
`FIX_PROMPT_GOLDEN` values. Verified.

## Diff, docs, CHANGELOG, hygiene

- `git diff --name-only 16ef0a5 HEAD` lists six files: `historyless-checkout.sh`, `test_calibration_kit.py`, the kit
  README, the subject-pack README, `CHANGELOG.md`, and integration 4's report. These are the files the report names.
  `subject-pack/shared/` (README and manifest) is untouched. Verified.
- `git ls-files --eol` gives `i/lf w/lf` for all eleven files changed since 09b476d. The added lines of the kit files
  and CHANGELOG hold no absolute host path, session or run id, or model name. Verified.
- 91c0485's message has the five parts and names the model only in the trailer. It repeats the 3.8+ claim (LC4-2).
  Verified.

## Guard-removal proofs (re-run, my own driver)

Each mutation ran in its own scratch copy of `tools/test_calibration_kit.py`, `tools/calibration/` and
`tests/fixtures/calibration/`. Each anchor matched exactly once, and every copy passed `bash -n`. Six ran in parallel.
The **control** ran all 16 `historyless` tests: **16 OK, 0 skipped** (1020 s). Each mutation ran the tests integration 4
names as red for it. I read the failure messages of N4, R1, NF, NK, T1 and Mdd. Each fails for its own reason: the
layer pins ("unexpectedly found"), a wrong reason ("holds the accepted fix" not found), an accepted Mup pack, the
object-set proof's own message, and the `cygpath` error before the dot check.

| mutation | red |
|---|---|
| N1 | unc; windows_parents |
| N2 | unc; nothing made |
| N3 | windows_parents |
| N4 | identity; windows_parents |
| N5, N6 | identity |
| N7 | git variables |
| N8 | unc |
| N9 | unc; nothing made |
| N10 | unc; windows_parents |
| N11 | reaches_the_pack; existing target |
| R1 | inside a repository; symlinks_at_the_top; target inside a repository |
| R3 | inside a repository; target inside a repository |
| R4 | inside a repository; symlinks_at_the_top |
| R6, M12, M13, M14, M15 | symlinks_at_the_top |
| M10 | nothing made; target inside a repository |
| NA | native; resolver |
| NB, NC, NY | resolver |
| ND, NE, NF, NG, NH, NI, NJ, NK, NL, NM, NN, NO, NS, NP, NX | native |
| T1 | template (exit 1, the proof's message) |
| T12 | template (alternates copied) |
| Mmk | nothing made; target inside a repository |
| Mdd | nothing made |
| RT | target inside a repository |
| RTM | target inside a repository; native |

**46 of 46 mutations went red, and none survived.** This reproduces integration 4's tables. My own addition is the
manual proof of the reparse-point half of `is_link` (LC4-4), which no test covers.

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` at 91c0485, no `MSYS` | 127 tests OK, 1 skipped (`links_only_on_request`: Git Bash copies without `MSYS`), 1603 s, exit 0. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| the IC4-1 clone | read only, status unchanged. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

## For the lead

1. LC4-1 (S3): replace `is_repo`'s git-directory clause, in both layers, with one that is at least as wide as git's
   `is_git_directory`: any `HEAD` entry, plus `commondir`, or `objects` and `refs` of any type. Then add tests for the
   `commondir`, symlink-HEAD and `refs`-file shapes, as DIR, as a top-level link and as TARGET, including through a
   GUID link.
2. LC4-2 (S4): probe for Python 3.10+, and say so in the header, the README and the message.
3. LC4-3 (S4): state in the header and README step 3 that only repository markers are detected. A subject's files
   outside any repository (an export, a copy, a `core.worktree` work tree) are the host's to keep away from DIR and
   TARGET.
4. LC4-4 (S4): add a junction case for the native `is_link`, and refuse a `--link` NAME under `.git`.

## What I got wrong and fixed

- In my driver, the `\\?\C:\...` spelling lost its backslashes on the way from Windows Python to bash, so that run
  tested a missing path ("no directory"). I re-ran it through `printf '\134...'`: refused, S. Only the re-run is cited.
- My first `/tmp` case assumed that Git Bash's `/tmp` follows `TEMP`. It is the Windows user temp directory (usertemp), so the path did
  not exist. I re-made the repository under that directory and re-ran: refused, S.
- `subst Q: /d` typed in Git Bash became `subst Q: D:/` (MSYS path conversion). The drive stayed mapped to `<fx>/pack`,
  so my next run made a checkout at `<fx>/pack/co`. That run had no `--pack`, so the script accepted it, as designed. I
  removed the drive with `MSYS_NO_PATHCONV=1`, deleted `<fx>/pack/co` (my fixture), and re-ran the subst target cases.
  The clone was never involved.
- My driver's "made on refusal" flag looked at TARGET's parent, which existed beforehand in several cases (`Q:/`,
  `bare.git/refs`, `other/docs`). I checked those cases against the watched trees, which were unchanged, and against
  the `out/tN` directories, of which none was made.
- I expected a refusal for "a target through a GUID link into the pack" without `--pack`. That was my mistake: without
  `--pack` there is no pack check, so it is not a finding.
