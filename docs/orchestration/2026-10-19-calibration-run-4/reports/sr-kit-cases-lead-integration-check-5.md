# sr-kit-cases, lead integration check 5 (refute-first, fresh context): IC4-1 and LC4-1..4 after lead integration 5

Checked: branch `build/sr-kit-cases` at 6b952de (lead integration 5) on 4bcf33c, with lead integrations 2-4, all
against 09b476d. I read the change against IC4-1 (sr-pack-4a integration check 4), check 4's LC4-1..LC4-4, the threat
model that the script's header and README step 3 now state, and the reports of integrations 2-5. I wrote none of the
change. This report is the only file this round adds. Every run had TEMP and TMP on the gittoken `.tmp-gate` folder.
The link cases ran with `MSYS=winsymlinks:nativestrict`, except where a row names `winsymlinks:sys` or `:lnk`. Git ran
with a hermetic config: `GIT_CONFIG_GLOBAL` on a scratch file, and `GIT_CONFIG_NOSYSTEM=1`. I only read the MoonAliza
clone. Its `git status --porcelain --ignored` is the same before and after every run that touched it (`!! node_modules/`,
`!! research/raw/.diagnostics.jsonl`). Below, `<fx>` is my fixture folder under `.tmp-gate`.

**Verdict: FIX**, for one S3 (LC5-1). Integration 5 closes what check 4 named:

- `is_repo` refuses every repository shape git accepts that I could build. It does so in both layers, whether the
  shape is DIR, TARGET or the target of a link at DIR's top.
- Every path spelling from checks 2-4 is refused.
- No `GIT_*` variable or template reaches the checkout.
- Refusals make nothing.
- A DIR outside every repository is still accepted.
- The rendered prompts are byte-identical to 09b476d.
- All 70 of the lead's guard-removal proofs go red.

But one promise fails. The header says the guard checks "each link at DIR's top and the parents of where it leads ...
by any spelling native programs resolve (both layers below)". That is not true for a link that only the shell layer
sees. The shell resolves such a link and checks the result in its own view of the path. The native layer never sees the
link, so it never checks that path as native programs resolve it. So a Git Bash symlink at DIR's top passes both layers
when it points at a volume-GUID link, a subst drive or another native-only path into a repository. From the checkout,
`cd node_modules/s && git log` prints the MoonAliza clone's accepted fix commit (LC5-1). That is IC4-1's leak again,
through the seam between the two layers. Three S4s do not block.

## Findings

| id | severity | finding |
|---|---|---|
| LC5-1 | S3 | **A link at DIR's top that only the shell sees, pointing at a path that only native programs resolve, passes both layers.** **Mechanism.** Git Bash makes "sys" symlinks with `MSYS=winsymlinks:sys`, and Windows shortcut symlinks with `MSYS=winsymlinks:lnk`. Both are plain files to Windows: Git Bash and every MSYS tool follow them, but they are no reparse point, so Python's `os.scandir`/`is_link` and node do not see a link. **The shell layer** sees the entry (`-L`), resolves it with `resolve` to a POSIX path, and runs `guard_link` on that path. Its `-ef` and `is_repo` checks then use Git Bash's view of the path, and Git Bash cannot see through a volume-GUID link (`mklink /D g \\?\Volume{...}\...`) or a subst drive. **The native layer** checks DIR, the source, the pack and TARGET's parents, and it scans DIR's top for reparse points. The shell's resolved `$real` is never passed to it (the top-level loop at lines 273-277 and the native invocation at lines 442-461 of the script). So the path where the link leads is never resolved natively. **Reproduced** on this host (Git 2.55.0.windows.5, Python 3.14). **(a)** `<fx>/mix/L/g` is a GUID symlink to `<fx>/other/node_modules`, where `other` is a work tree with history and the fix commit. `<fx>/mix/dep/s` is made with `MSYS=winsymlinks:sys ln -s <fx>/mix/L/g`. `--link node_modules=<fx>/mix/dep` exits 0 with "ok", with and without `--pack` (`out/mix1`, `out/mix2`). In the checkout, `cd node_modules/s && git rev-parse --show-toplevel` prints `<fx>/other`, and `git log --oneline -3` prints `2f8fe1b f` and `93bad48 b`. Python's `os.path.realpath('.')` and node's `fs.realpathSync.native('.')` there both name `other/node_modules`, and through that path's parent `docs/brief.md` reads. **(b)** The same with a subst drive: `subst R: <fx>/other/node_modules` and a sys symlink to `/r/pkg` are accepted (`out/mix3`), and `git log` from it prints the fix. **(c)** An `MSYS=winsymlinks:lnk` shortcut (`s.lnk`) to `<fx>/mix/L/g` is accepted with `--pack` (`out/mixl1`), and `git log` from `node_modules/s` prints `2f8fe1b f`. **(d) Against the read-only MoonAliza clone:** `<fx>/mixm/L/g` is a GUID symlink to the clone's `node_modules`, and `<fx>/mixm/dep/s` is a sys symlink to it. `--link node_modules=<fx>/mixm/dep` exits 0 with "ok", with and without `--pack` (`out/mixm1`, `out/mixm2`). In `out/mixm1/node_modules/s`: `git rev-parse --show-toplevel` prints the clone; `git cat-file -t 01a8604` prints `commit`; and `git log --oneline -1 01a8604` prints the accepted fix, "test(github-sign-in): X2-1 rows cover a refresh after its first commit, ...". The clone's orchestration folders are listed through `docs/orchestration`, and the clone's status is unchanged. **Why S3** (the rubric of LC2-1, LC3-1 and LC4-1): the header's own "What the guard covers" sentence and Item 2 fail on the kit's own host. A path the checkout gets from the script (a link at DIR's top, and where it leads) reaches a git repository and its accepted fix. This is inside the stated threat model: the link is at DIR's top, not deeper; the header says that "both layers below" check it; and nothing in the docs assigns MSYS-only links to the host. It is not S2, because a host must build a two-step link (an MSYS link to a native-only path), on purpose or through an unusual tool chain. It is not from round 5 alone: the seam dates from round 4, when the native layer was added. **Fix (the lead decides):** pass every path the shell resolves for a top-level link (each `$real` in the loop) to `native_guard` as an item. Resolve and check it there like DIR: `final()`, the repository walk, the source and the pack. Then add a test with three links at DIR's top: an `MSYS=winsymlinks:sys` link to a GUID link into another repository, one to a subst path, and an `MSYS=winsymlinks:lnk` shortcut. Each must be refused natively, with and without `--pack`, and a control to a free directory must be accepted. |
| LC5-2 | S4 | **An inherited `SHELLOPTS=noglob` turns off the shell's top-level link loop.** The loop is `for entry in "$dep"/* "$dep"/.[!.]* "$dep"/..?*`. Bash imports `SHELLOPTS` from the environment. With `noglob` the patterns stay literal, so no entry is checked. With a sys symlink `<fx>/env1/s` -> `<fx>/other/node_modules`, `env SHELLOPTS=noglob bash historyless-checkout.sh ... --link node_modules=<fx>/env1` exits 0, and `cat out/e2/node_modules/s/../docs/brief.md` prints the brief. Without the variable, the shell refuses it. On this host the native layer catches every reparse-point link at the top, so the bypass needs an MSYS-only link here. On Linux or macOS, where only the shell layer runs, any symlink at DIR's top would pass (expected, untested). `BASHOPTS=failglob` makes the script exit 1 before anything is made, so it fails closed. **Why S4:** this is the host's environment, the class of LC2-3 (`GIT_DIR`) and LC3-2 (`GIT_TEMPLATE_DIR`). **Fix:** `set +f` and `shopt -u nullglob failglob` at the top of the script, and a test with `SHELLOPTS=noglob` exported. |
| LC5-3 | S4 | **A link NAME through a tracked symlink to `.git` passes the NAME check.** The NAME rule looks only at NAME's spelling. A case base may track a symlink to `.git` (mode 120000), and a host with `core.symlinks=true` checks it out as a link. My `pack2/repo` base tracks `g -> .git`. With `core.symlinks=true`, `--link g/hooks=<fx>/free/hooks` exits 0. `out/n1/.git/hooks` is then a link to that host directory, and a candidate's `git commit` in the checkout runs the host's `pre-commit` (it printed `HOSTHOOK-RAN`). That gives no path to the fix, so this is LC4-4's class (S4). **Fix:** after the links are made and before the proof, check in both layers, by identity, that each link's real parent lies inside TARGET and outside TARGET's `.git`; refuse and remove the checkout otherwise. Alternatively, refuse a NAME whose existing prefix in the base tree is a symlink. |
| LC5-4 | S4 | **Two guards that no test sees removed (my own mutants, below).** **(1) U2:** the NAME check is skipped for every `--link` after the first (`rest=$name; [ ${#LINK_NAMES[@]} -eq 0 ] \|\| rest=""`). The link-name test passes a single `--link` per run, so it stays green. With the mutant, `--link a=<free> --link .git/hooks=<free>` exits 0, and `.git/hooks` is a link to the host directory; 6b952de refuses the same call. **(2) U1:** the native `is_link` treats an entry that cannot be read as a link (fail closed). With that branch turned to `return False`, the native and junction tests stay green: no test makes an entry whose `stat` fails. **Fix:** give the link-name test a run with a refused NAME after an accepted one. Add a unit case that patches `DirEntry.stat` to raise, like the unreadable-marker test does for `os.lstat`. |

## Claims, attacked

Fixtures under `<fx>`:

- `pack/`, which is not a repository, holding `repo` (with `base` and `fix` commits).
- `other`: a work tree with history and the fix, `node_modules/pkg` and `docs/brief.md`. It has a linked worktree, `sh/wt`.
- Repository shapes under `sh/`, each with an empty `deps/` inside.
- Links:
  - volume-GUID links (`\\?\Volume{...}\...`, made with `mklink /D`);
  - junctions (`_winapi.CreateJunction`);
  - chains (a plain link to a GUID link);
  - subst drives.

"N" marks a refusal by the native layer ("as native programs resolve it"), and "S" one by the shell layer. Every refusal
below exited 2 and made nothing: no `out/` directory, and no missing parent of TARGET was created.

### Every repository shape git accepts

Each shape was used three ways:

- as DIR (`--link node_modules=<shape>/deps`);
- as TARGET (`<shape>/deps/coN`);
- as the target of a symlink at the top of an otherwise clean DIR.

| shape | DIR | TARGET | top-level link |
|---|---|---|---|
| `commondir` admin directory (only `HEAD` and `commondir`, pointing at `other/.git`) | refused, S | refused, S | refused, S |
| bare clone, `pack-refs --all`, `HEAD` a dangling symlink to `refs/heads/main` | refused, S | refused, S | refused, S |
| bare clone, `pack-refs --all`, `refs` a file | refused, S | refused, S | refused, S |
| a reftable repository (`init --ref-format=reftable`): its `.git`, and its work tree | refused, S | refused, S | refused, S |
| a bare repository | refused, S | refused, S | refused, S |
| a work tree whose `.git` is a junction to another git directory | refused, S | refused, S | refused, S |
| a dangling `.git` symlink | refused, S | refused, S | refused, S |
| `HEAD` a directory (with `objects` and `refs`) | refused, S | refused, S | refused, S |
| a linked worktree's admin directory (`other/.git/worktrees/wt`) | refused, S | refused, S | refused, S |
| a linked worktree (a `.git` file) | refused, S | refused, S | refused, S |
| control: `objects/` alone, no `refs` (git does not take it either) | accepted | accepted | accepted |

The last row is an observation, not a finding: a loose object store holds content, not a repository git discovers.

### Every path spelling from checks 2-4, on the new shapes

I tried each spelling below on three shapes: `sym.git`, `cgd` (the `commondir` directory) and `rf.git` (the `refs`-file
shape). Each was used as DIR and as TARGET.

| spelling | result |
|---|---|
| a GUID link to the shape | refused, N |
| a chain: a plain symlink to the GUID link | refused, N |
| a junction to the GUID link | refused, N |
| a DIR whose top-level entry is a junction to the GUID link | refused, N |
| a `GLOBALROOT\Device\HarddiskVolumeN` link | refused, "no directory" (Git Bash cannot open it; check 4 proved the native refusal) |
| upper case, the 8.3 short name, `/proc/cygdrive/c/...`, `//?/C:/...` | refused, S |
| UNC `//localhost/C$/...`, as DIR and as TARGET | refused, "not a local path" |
| `subst Q: <sym.git>/deps`, as DIR `Q:/` and as TARGET `/q/co` | refused, N |
| control: `subst Q: <free>`, as DIR `Q:/` | accepted |

### IC4-1, against the read-only MoonAliza clone

Each variant ran with and without `--pack`, 18 runs in all:

- refused by the shell (S): the clone's `node_modules` directly, its 8.3 spelling and its upper-case spelling;
- refused natively (N): a GUID link to it, a chain to that link, and a junction to it;
- a clean DIR whose top-level entry is a GUID link (N), a junction (N) or a native symlink (S) to the clone.

All exited 2, none made anything, and the clone's status was unchanged. **One more variant passes: a sys symlink at the
top that points at the GUID link (LC5-1).**

### Git variables and templates

I tried each of these:

- `GIT_DIR`+`GIT_WORK_TREE` (at `other`);
- `GIT_COMMON_DIR`;
- `GIT_OBJECT_DIRECTORY`;
- `GIT_ALTERNATE_OBJECT_DIRECTORIES`;
- `GIT_INDEX_FILE`;
- `GIT_TEMPLATE_DIR`, with a live `objects/info/alternates` template;
- `init.templateDir` through `GIT_CONFIG_GLOBAL`;
- `GIT_CONFIG_COUNT`/`KEY`/`VALUE` and `GIT_CONFIG_PARAMETERS`, setting `core.worktree` to `other`.

All were accepted. Each checkout holds the base's 5 objects only, with no alternates, and the fix is not readable
(`cat-file -e` fails). `other`'s status and `HEAD` are unchanged. Verified.

### Targets inside a repository or the pack, and refusals that make nothing

| attack | result |
|---|---|
| TARGET `<fx>/other/a/b/co` (two missing parents) | refused, S; `other/a` not made |
| TARGET through a GUID link into `sym.git/deps`, two missing parents | refused, N; nothing made under `sym.git/deps` |
| TARGET `<fx>/pack/x/y/co`, with `--pack` | refused, S; `pack/x` not made |
| every TARGET refusal in the tables above | nothing made |

### A DIR outside every repository is still accepted

| control | result |
|---|---|
| `free/node_modules`, with and without `--pack` | accepted, one commit |
| a DIR on the scratch drive (`E:`) | accepted |
| a DIR and a TARGET in the Windows user temp directory (another drive) | accepted |
| a subst drive to a free directory | accepted |
| the host's own ancestor directories (gittoken, Desktop, the user folder, the drive root) | hold no marker the new rule counts, so nothing is refused for them. Verified |

## Is the threat model stated honestly?

Mostly, and much better than in round 4:

- The header's "What the guard covers, and what it cannot" paragraph and README step 3 name the host's duties that the
  guard cannot see: a copy or an export, a `core.worktree` work tree, deeper links, and anything known only by content.
- They say that a refusal never means "remove the `.git`".
- The subject-pack README sentence and the CHANGELOG clause match the behaviour.
- The Python 3.10 probe, the header, the README and the message agree.

Two statements promise more than the code does:

- "each link at DIR's top and the parents of where it leads ... by any spelling native programs resolve (both layers
  below)": this is not true for a link only the shell sees (LC5-1). It is a code defect, not a documentation one: the
  docs state the right promise.
- The header does not say that the script trusts the shell options it inherits (LC5-2).

## Rendered prompts

A scratch driver renders `run.template.js` at 09b476d (`git show`) and in the working tree, through the test module's
`run_config` / `execute_template` with `GOLDEN_HOST`. It covers the fixture and shared manifests, each with
`cause_in_prompt` absent, true and false, and compares every call as sorted JSON. **60 calls compared, 0 differ.** The
fix prompt sha256 prefixes are `5e66cf5f4d0c141c` (fixture) and `54a0353d503c950d` (shared), the `FIX_PROMPT_GOLDEN`
values. The grader, lens and cluster prompts and `classification.md` are unchanged since 09b476d. Verified.

## Diff, docs, CHANGELOG, hygiene

- `git diff --name-only 4bcf33c 6b952de` lists six files: `historyless-checkout.sh`, `test_calibration_kit.py`, the
  kit README, the subject-pack README, `CHANGELOG.md`, and integration 5's report. `subject-pack/shared/` and
  `run.template.js` are untouched. Verified.
- `git ls-files --eol` gives `i/lf w/lf` for every file changed since 09b476d. The added lines hold no absolute host
  path, session or run id, or model name. Verified.
- 6b952de's message has the five parts and names the model only in the trailer. Verified.

## Guard-removal proofs (re-run, my own driver)

How the driver works:

- Each mutant is a `git archive` copy of 6b952de's `tools/test_calibration_kit.py`, `tools/calibration` and
  `tests/fixtures/calibration`, with one change to the script.
- Four ran in parallel, with `MSYS=winsymlinks:nativestrict`, each through `python -m unittest -f` on the tests named
  for it.
- I took the lead's 70 mutant scripts from the lead's scratch copies. Before running them, I read each one's diff
  against 6b952de: each holds exactly the change the lead's table names.
- **Control:** all 21 `historyless` tests, **21 OK, 0 skipped** (1915 s).

| mutants | red on |
|---|---|
| round 4's 45 (N1-N11, NA-NY, R1, R3, R4, R6, M10, M12-M15, Mmk, Mdd, RT, RTM, T1, T12) | the tests the lead names for each |
| R0, RH, RC, RG, RO, RL | shell LC4-1 (`refuses_every_directory_git_takes_for_a_repository`) |
| RE | shell LC4-1, link-repository, target-repository |
| Q0, QC, QD, QG, QH, QI, QO | native LC4-1 (`..._as_native_programs_resolve_it`); Q0, QD and QH also on the unreadable-marker test |
| QL, QX | the unreadable-marker test |
| Z1-Z7 | the link-name test |
| PV | the Python 3.10 test |
| JR | native LC4-1 (the junction case) |

**The lead's 70 mutants: 70 red**, which reproduces integration 5's table. My four:

| mutant | change | result |
|---|---|---|
| U3 | the shell's TARGET repository walk checks TARGET's first existing parent only | red: target-repository |
| U4 | the native TARGET walk checks the first parent only | red: native LC4-1 |
| U2 | the NAME check is skipped for every `--link` after the first | **green (survives): LC5-4** |
| U1 | the native `is_link` counts an unreadable entry as no link | **green (survives): LC5-4** |

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` at 6b952de, `MSYS=winsymlinks:nativestrict` | 132 tests OK, 0 skipped, 2954 s, exit 0. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| the IC4-1 clone | read only, status unchanged after every run. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

**Untested:**

- hosts other than this Windows 11 / Git Bash one;
- a volume mounted at a folder with no drive letter (`mountvol` needs admin);
- a network drive letter.

By LC5-1's mechanism, any of these behind an MSYS-only link at DIR's top would pass as well (expected).

## For the lead

1. **LC5-1 (S3):** hand every path the shell layer resolves for a link at DIR's top to `native_guard`, and check it
   there as native programs resolve it: the repository walk, the source and the pack. Add a test with a
   `winsymlinks:sys` link at DIR's top pointing at a GUID link into another repository, one pointing at a subst path,
   and a `winsymlinks:lnk` shortcut. Each must be refused natively, with and without `--pack`, and a control to a free
   directory must be accepted. Add a guard-removal proof: drop the new items, and the test must go red.
2. **LC5-2 (S4):** reset the shell options the loop depends on (`set +f`, `shopt -u nullglob failglob`) at the top of
   the script, and test with `SHELLOPTS=noglob` exported.
3. **LC5-3 (S4):** before the proof, check each made link's real parent: it must lie inside TARGET and outside
   TARGET's `.git`. Alternatively, refuse a NAME whose existing prefix in the base tree is a symlink.
4. **LC5-4 (S4):** give the link-name test a refused NAME after an accepted one. Add a unit case for an unreadable entry
   in the native `is_link`.

## What I got wrong and fixed

- **The host's hooks ran in my first runs.** My first run with `noglob` failed with "reference-transaction hook
  aborted": git used the host's global `core.hooksPath`, and its hook inherited `SHELLOPTS`. I made the git config
  hermetic for every run (`GIT_CONFIG_GLOBAL` on a scratch file, `GIT_CONFIG_NOSYSTEM=1`) and re-ran. Only the
  hermetic runs are cited.
- **My IC4-1 driver first held a TARGET reached through a GUID link into the clone.** If the guard had failed, that case
  would have written in the read-only clone. I stopped the driver and removed the case. The process already running it
  still ran it once: it was refused natively, and nothing was made. I verified that no checkout exists under the
  clone's `node_modules`, that `node_modules`' modification time is older than this check, and that the clone's status
  is unchanged. The re-run uses targets under `<fx>` only.
- **The GLOBALROOT links I made could not be opened by Git Bash** ("no directory"). That is still a refusal, and check 4
  had proved the native refusal of that spelling, so I cite them only as refused.
- **My first proof of U2 passed the arguments in the wrong order** and got the usage message. I re-ran it with the
  options first: the mutant accepts `.git/hooks` as the second link, and 6b952de refuses it.
