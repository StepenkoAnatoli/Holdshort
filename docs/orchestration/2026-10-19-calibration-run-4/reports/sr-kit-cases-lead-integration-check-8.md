# sr-kit-cases, lead integration check 8 (refute-first, fresh context): LC7-1 and LC7-2 after lead integration 8

Checked: branch `build/sr-kit-cases` at f06353f (lead integration 8) on d4c2c8f, with lead integrations 2-7, all
against 09b476d. I read the change against check 7's LC7-1 and LC7-2, the threat model in the script's header and
README step 3, and integration 8's report. I wrote none of the change. This report is the only file this round adds.
Every run had TEMP and TMP on the gittoken `.tmp-gate` folder. Git ran with a hermetic config (`GIT_CONFIG_GLOBAL` on
a scratch file, `GIT_CONFIG_NOSYSTEM=1`). The link cases ran with `MSYS=winsymlinks:nativestrict`, except where a row
names a `sys` or `.lnk` link or another MSYS mode. Host: Windows 11, Git 2.55.0.windows.5, bash 5.3.15, Python
3.14.7. Below, `<fx>` is my fixture folder under `.tmp-gate`, and `<LF>`, `<CR>` and `<TAB>` stand for a newline,
carriage return or tab inside a name (MSYS stores them as U+F00A, U+F00D and U+F009).

**Verdict: ACCEPT.** There is no S1-S3. Integration 8 closes LC7-1 and LC7-2 as check 7 named them:

- LC7-1: `sys` links (plain and `--pack`) and `.lnk` shortcuts (plain and `--pack`) to `x/hl<LF>/brief.md`, with a
  hard link of it in a free `x/hl`, are refused "not proved", with nothing made (4 of 4). d4c2c8f accepts all four.
- LC7-2: 59 NAMEs, each with nothing staged but what the candidate made. The name rule, the plain-path rule, the
  `.git` rule or the `check-ignore` proof refuses each name that is not a plain, ignorable name. A tracked
  `.gitignore` that re-includes a name is refused, and so is a NAME below a tracked symlink, which d4c2c8f would stage (expected from its code).
- The LC6-1 and LC5-1 variants, the round-7 regressions and six MoonAliza cases are refused as before.
- The rendered prompts are byte-identical to 09b476d. The full kit suite (140 OK) and the evidence check pass. The
  guard-removal proofs hold (table below).

Three S4s remain. LC8-1 is older than this round, but this round's proof does not reach it. Under
`MSYS=winsymlinks:lnk`, the script's own `ln -s` makes `NAME.lnk`, a shortcut file. The proof checks NAME, which is
ignored and does not exist. It does not check the file that `ln -s` made, and `git add -A` stages that file. The blob
holds the host's absolute path. LC8-2 is a wrong line in integration 8's report. LC8-3 is a test gap: no test fails
when only the first link's `check-ignore` proof is kept.

## Findings

| id | severity | finding |
|---|---|---|
| LC8-1 | S4 | **Under `MSYS=winsymlinks:lnk`, the link `--link` makes is `NAME.lnk`, which the exclude line does not ignore, and `git add -A` stages it with the host's path.** **Mechanism.** Under `winsymlinks:lnk`, MSYS `ln -s TARGET NAME` writes a Windows shortcut file `NAME.lnk`, and the MSYS tools show it as `NAME`. Git is a native program, so it sees `NAME.lnk`. The script writes `/NAME` to `.git/info/exclude` and proves it with `git check-ignore -q -- "$NAME"`. That proves the *name* is ignored. The name is ignored, and it is not on disk. Nothing checks the file that was made. **Reproduced** on this host. Under `MSYS=winsymlinks:lnk`, `--link node_modules=<fx>/free/dd` exits 0 with "ok". In the checkout, `git status --porcelain` prints `?? node_modules.lnk`, and `git check-ignore node_modules.lnk` exits 1. `git add -A` stages `node_modules.lnk` (mode 100644, 1103 bytes). Its blob holds `<fx>/free/dd` in both the MSYS spelling and the `C:` spelling. d4c2c8f does the same, so this dates from dc2d8c9's `--link`. Under `sys`, `native`, `nativestrict` and with MSYS unset, nothing is staged (`sys` makes a system file named NAME; with MSYS unset, Git Bash copies the target to NAME). **Not assigned to the host.** The header and README step 3 discuss `winsymlinks:sys` and `:lnk` only for links found at DIR's top. They do not ask the host to pin the mode `--link` makes links with. They promise that "a candidate's `git add -A` never commits" a link. **Why S4** (LC7-2's rubric): it reaches no repository, but it breaks a header promise about what a candidate commits, with an absolute host path in the commit. It needs a host that sets `winsymlinks:lnk`. **Fix (verified on a scratch copy; the lead decides):** prove the files actually made, not the names. The checkout is fresh, so after the links are made, `git -C "$GIT_TARGET" ls-files --others --exclude-standard --directory` must print nothing; otherwise `refuse_made`. On my copy, `lnk` mode is refused, naming `node_modules.lnk src/vendor.lnk`, and the checkout is removed. `sys`, `nativestrict` and a run without `--link` are still accepted. Pinning `MSYS=winsymlinks:nativestrict` for the `ln -s` call would also stop the `.lnk`. It changes what the script makes, so I would keep the `ls-files` proof either way. Add a test that runs with `MSYS=winsymlinks:lnk`, plain and `--pack`. |
| LC8-2 | S4 | **One of integration 8's "Behaviour changes" lines is wrong.** It says that a link at DIR's top "to a file whose directory name ends in a newline is now accepted when that directory is free". On this head, a `sys` link to a file `g` inside a free directory `ff/f<LF>` is still refused "not proved". `physd` runs `pwd -P` inside a command substitution, which drops the directory's trailing newline. The `-ef` proof then fails, and the script fails closed. This is safe, and integration 8's own observation about a checkout path ending in a newline describes the same cause. What is newly accepted is the case the LC7-1 test's control builds: a link to a file whose **own name** ends in a newline (`ff/f<LF>` as the file). d4c2c8f refused that; this head accepts it. Verified both. The kit and the tests are right; only the report line is inaccurate. **Fix:** correct the line in the next report, or in the CHANGELOG if it is carried there (it is not now). |
| LC8-3 | S4 | **The `check-ignore` proof is pinned for one link, not for each.** The mutant Y6 keeps the proof for the first link only (`[ "$i" -gt 0 ] \|\| git ... check-ignore ...`). All three of this round's tests stay green. The LC7-2 test's re-include cases each pass a single `--link`, so a second link that is re-included is never tested. Integration 8 says "Every guard this round adds is pinned by a test"; that holds for the guard, but not for its per-link loop. The code is right. Verified (mutant run). **Fix:** add a re-include case whose re-included name is the second `--link` (for example `--link node_modules=... --link deps=...` against `!/deps`), plain and `--pack`, and keep Y6 as its mutant. |

## LC7-1 and its class, re-run

Each row compares head (f06353f) with d4c2c8f, using the same fixture and the same arguments. "Refused" means exit 2,
nothing made, and the host's directories untouched.

| case | fixture | head | d4c2c8f |
|---|---|---|---|
| LC7-1, `sys`, plain and `--pack` | `<fx>/dephl/s` -> `x/hl<LF>/brief.md`, a work tree; a hard link of `brief.md` in a free `x/hl` | refused, "not proved" (2 of 2) | exit 0 (2 of 2) |
| LC7-1, `.lnk`, plain and `--pack` | a shortcut to the same | refused, "not proved" (2 of 2) | exit 0 (2 of 2) |
| control | `sys` link to a free directory | accepted | accepted |
| control | `sys` link to a file named `f<LF>` in `ff` (no twin) | accepted | refused "not proved" (false refusal) |
| control | `sys` link to `ff/f<LF>/g` (a free directory ending in a newline) | refused "not proved" (fails closed; LC8-2) | refused |
| twin directory, file branch | `sys` link to a file in `x/repo<LF>` (a work tree), where `x/repo` is a `sys` or native symlink twin to it | refused, "inside the git repository" | refused |
| twin directory, directory branch | a volume-GUID link named `x/repo<LF>` into a work tree, a `sys` twin `x/repo` | refused natively (`cygpath -m` of `x/repo` resolves the MSYS link and names `repo<U+F00A>`) | refused |
| control | a volume-GUID link to a free directory | accepted | accepted |
| LC6-1, `sys` and `.lnk`, each plain and `--pack` | a link at DIR's top to `x/repo<LF>`, a work tree beside a free `x/repo` | refused (4 of 4) | refused (4 of 4) |
| LC6-1 CR twin | `sys` link to `x/cr<CR>` beside a free `x/cr` | refused | refused |
| LC5-1 | `sys` and `.lnk` links to a volume-GUID link into a repository, plain and `--pack`; `sys` links into a `subst` drive (`R:`) of a repository, plain and `--pack` | refused (all) | refused (all) |
| LC5-1 control | `sys` link to a free directory, plain and `--pack` | accepted | accepted |
| R12-dot | target `tw/co.` beside the host's `tw/co` | refused, `tw/co` untouched | refused |
| R13-dot | the same with `--link` | refused, `tw2/co` and its `host.txt` untouched | refused |

I removed the `subst` drive after the run.

## LC7-2: every NAME class

Each NAME ran as `--link NAME=<fx>/free/dd` on a base tree that holds `README.md`, `b`, `src/b`, `src/x.js`, `docs/`,
`docs/.venv` and `.gitignore`. When a checkout was made, I added a new candidate file and ran `git add -A`, then read
`git diff --cached --name-status` and `git ls-files -s` for a 120000 entry.

| NAMEs | head |
|---|---|
| `[x]`, `q?m`, `a]b`, `[`, `" lead"`, `"trail "`, `a<LF>b`, `nm<LF>`, `#c`, `!n`, `nm*`, `\xff`, `x.`, `.`, `a//b`, `x/`, `<TAB>`, `~1`, `a,b`, `a'b`, `a"b`, `a\|b`, `a<b`, `$x`, `%x`, `^x`, `{x}` | refused by the name rule, nothing made |
| `a\b`, `..x`, `x..y` | refused as not a plain relative path (`x..y` is a false refusal; harmless) |
| `GIT~1` | refused as a spelling of `.git` |
| `README.md`, `readme.md` (case twin), `b`, `src/b`, `docs`, `.gitignore`, `docs/.venv` | refused: the checkout already holds the name |
| `newdir/x`, `src/x.js/y` | refused: the parent is not a directory of the checkout |
| `nul`, `aux`, `con.x`, `com1`, `NUL`, `lpt1.txt`, `-x`, `@`, `a+b`, `.venv`, `src/node_modules`, `node_modules`, `lib/vendor`, `Docs/x`, `x.y.z`, `_`, `+`, `9` | made; `git add -A` staged only my new file, no link. Windows 11 made the reserved device names as real symlinks (Python's `os.path.islink` holds), so this is harmless |
| `a=b` | parsed as NAME `a` and DIR `b=...` (the first `=` splits), so it is not a name case |

**Re-include and symlink cases.** The base tree's tracked `.gitignore` holds `!/deps` and `!src/vendor`. The NAMEs
`deps`, `Deps`, `src/vendor`, `src/Vendor` and `deps` with `--pack` are refused by the `check-ignore` proof, and the
checkout is removed. A base tree with a tracked symlink `lnk -> lib` checks out with `core.symlinks=true`. With NAME
`lnk/vendor`, the script refuses: `check-ignore` stops at "beyond a symbolic link" and exits 128, so the script fails
closed. d4c2c8f would stage `lib/vendor`, a symlink to the host's path, in the same case: its line `/lnk/vendor` does
not match `lib/vendor` (expected from the code, not run). With NAME `[x]`, d4c2c8f stages the
link `[x]` (check 7's reproduction, confirmed).

**Neighbours.** I ran a checkout with eight links, then made 14 files that sit beside the link names (`node_modulesx`,
`src/node_modules`, `.venvx` and the like) and ran `git add -A`. All 14 were staged, and no 120000 entry was.

**`git add -A` never stages a link:** this holds under `nativestrict`, `native`, `sys` and with MSYS unset, for every
NAME the rule admits. It does not hold under `lnk` (LC8-1).

## Hunting: other string round trips

| string | separated from its proof? | why |
|---|---|---|
| `spell_dir`, `spell_base`, `spell_link` (`$(cmd && echo .)`, then the marker and one newline cut) | no | exact by construction; the LF and CR rows above ran through them |
| `resolve` sets `RES`; the caller reads `real=$RES` | no | no substitution left between `resolve`'s proof and the caller |
| `physd`: `p=$(cd -P ... && pwd -P)`, then `[ "$p" -ef "$1" ]` | the substitution comes before the proof, but the proof is against the exact argument | a stripped newline makes the proof fail closed (LC8-2's case). A twin that passes `-ef` names the same directory, by symlink, not hard link (directories cannot be hard-linked here). Then `canon` and the native layer see that same directory. I built symlink twins in both branches of `resolve`, and all were refused (table above) |
| `w=$(cygpath -m -- ...)` | no | `cygpath -m` writes a trailing newline as U+F00A (verified), so it is lossless, and each is proved against the original. It also follows MSYS-only links, so the native layer gets the MSYS-physical path. This is why the twin variants are refused |
| the native layer's `\\?\` spelling, `os.path.realpath(strict=True)`, samestat | no | unchanged since round 7; the LC5-1 rows re-ran |
| the exclude line `printf '/%s\n' "$NAME"` | proved by `check-ignore` for the NAME | but not for the file `ln -s` made (LC8-1) |

**Overstated, not a finding:** the header line "No part of a path is taken through a command substitution between the
path and its proof" overstates the code: `physd`'s `pwd -P` is one. As above, it fails closed. A future edit should
not rely on the wording.

## Rendered prompts

`run.template.js` at 09b476d and now, rendered through the test module's `run_config`/`execute_template` with
`GOLDEN_HOST`, for the fixture and shared manifests with `cause_in_prompt` absent, true and false: **60 calls, 0
differ.** The fix prompts are 2580 bytes `5e66cf5f4d0c141c` and 3066 bytes `54a0353d503c950d`. The prompt files,
`classification.md` and `protocol.template.json` are identical to 09b476d. `run.template.js` differs from 09b476d only
by a comment (3 lines). Verified.

## Diff and hygiene

`git diff --stat d4c2c8f..f06353f` lists six files:

- `CHANGELOG.md`
- integration 8's report
- `tools/calibration/README.md`
- `tools/calibration/historyless-checkout.sh`
- `tools/calibration/subject-pack/README.md`
- `tools/test_calibration_kit.py`

All six are permitted for this unit. `git ls-files --eol` shows LF on all six, and `bash -n` passes on the script. A
grep of the added lines finds no absolute host path, session or run id, or model name. Verified.

## Guard-removal proofs

I used integration 8's mutation driver setup, rebuilt in scratch from check 7's copy, and ran it with this head's
script. Each mutant runs in a plain copy of `tools/test_calibration_kit.py`, `tools/calibration` and
`tests/fixtures/calibration`, three in parallel, with `MSYS=winsymlinks:nativestrict`. Old mutants are re-applied from
their diffs, and drifted hunks get the exact-replacement ports. A dry run applied all 122: 13 drifted hunks were
replaced exactly and 16 were ported.

- **Control:** this head on the union of the mutants' tests: **26 tests, 0 red.** Verified.
- **Old mutants (rounds 4-6): 70 of 70 red, each with exactly its earlier red set.** Verified.
- **Rounds 6-7 and check 7's: 36 of 40 with exactly their earlier red sets.** Four do not match, as integration 8
  reported:
  - O4: green, equivalent.
  - I3 and I4: green. I agree they are equivalent now. The join and the hop are exact, so the `-ef` after each always
    holds. That leaves them as defense in depth.
  - D3: red on the link-parent test only. Verified.
- **This round's mutants (R1-R4, N1-N3): 7 of 7 red, each with exactly integration 8's red set.** R1 and R4 are red on
  the LC7-1 test. R2 and R3 are red on the LC7-1 and LC6-1 tests. N1 is red on the LC7-2 and LC6-1 tests. N2 and N3
  are red on the LC7-2 test. Verified.
- **My mutants, on the three new or changed tests:**

| mutant | removes | red |
|---|---|---|
| Y1 | the name rule's `*/` alone | the LC7-2 test |
| Y2 | `*//*` alone | the LC7-2 test |
| Y3 | `*.` alone | the LC7-2 test |
| Y4 | `*./*` alone | the LC7-2 test |
| Y6 | `check-ignore` for every link but the first (`[ "$i" -gt 0 ] \|\| git ... check-ignore ...`) | **none: survives** (LC8-3) |

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py`, `MSYS=winsymlinks:nativestrict` | 140 tests OK, 3214 s, exit 0; the worktree is clean afterwards. Integration 8's gate-timeout flake did not recur. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| the MoonAliza clone (read only): `node_modules` directly, plain and `--pack`; a volume-GUID link to it; a `sys` link to a volume-GUID link to it, plain and `--pack`; a `.lnk` link to the same | 6 of 6 refused, exit 2, nothing made. The clone's `.git/index` mtime and the sha of `GIT_OPTIONAL_LOCKS=0 git status --porcelain --ignored` are the same before and after. Nothing was written in the clone. Verified |
| the full regression gate, through the pre-commit hook, on this commit | verified by the commit landing |

## Untested

- Hosts other than this Windows 11 / Git Bash one. LC8-1 is specific to MSYS's `lnk` mode; Cygwin has a similar
  `winsymlinks:lnk` setting (expected the same, untested).
- My LC8-1 fix only ran on a scratch copy, with four cases (`lnk`, `sys`, `nativestrict`, and no `--link`). It did not
  run against the full suite.
- A `.lnk` twin in a native path (`x/repo<U+F00A>` made through Python): my fixture failed to build, because MSYS
  mangled the argument. `cygpath -m` was already shown to resolve twins, so I dropped it.
- I re-ran six MoonAliza cases, not integration 8's 24.

## For the lead

- LC8-1: prove the made files with `git ls-files --others --exclude-standard` in the fresh checkout (the scratch fix
  above), and add a `winsymlinks:lnk` test, plain and `--pack`. Consider pinning `MSYS=winsymlinks:nativestrict` for
  `ln -s`, too.
- LC8-2: correct the "Behaviour changes" line in the next report.
- LC8-3: add a two-link re-include case, so Y6 turns red.
- The header and README line about command substitutions could name `physd`'s `pwd -P` as the one that fails closed.

## What I got wrong and fixed

- **An edit to my mutation driver through a shell heredoc lost its escapes**, so its own anchor assertion failed (0
  matches). I made the edit with a file edit instead. The dry run then applied every mutant.
- **My first `.lnk`-twin fixture failed:** MSYS mangled a `$''` argument to Python. I dropped that variant
  (see "Untested") rather than count it.
- **I first read LC8-2's line as matching the test's control.** On rereading, the test's control is a file whose own
  name ends in a newline, and the report line speaks of the directory. I built both cases before calling it.
