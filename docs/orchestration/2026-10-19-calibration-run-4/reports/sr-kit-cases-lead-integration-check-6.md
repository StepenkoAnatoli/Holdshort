# sr-kit-cases, lead integration check 6 (refute-first, fresh context): LC5-1..LC5-4 after lead integration 6

Checked: branch `build/sr-kit-cases` at 2b3a163 (lead integration 6) on 8637e03, with lead integrations 2-5, all
against 09b476d. I read the change against check 5's LC5-1..LC5-4, the threat model in the script's header and README
step 3, and the reports of integrations 2-6. I wrote none of the change. This report is the only file this round adds.
Every run had TEMP and TMP on the gittoken `.tmp-gate` folder. Git ran with a hermetic config (`GIT_CONFIG_GLOBAL` on
a scratch file, `GIT_CONFIG_NOSYSTEM=1`). The link cases ran with `MSYS=winsymlinks:nativestrict`, except where a row
names `winsymlinks:sys` or `:lnk`. I did not touch the MoonAliza clone in this round, not even to read it (see
"Untested"). Below, `<fx>` is my fixture folder under `.tmp-gate`.

**Verdict: FIX**, for one S3 (LC6-1). Integration 6 closes what check 5 named:

- LC5-1: every `sys` and `.lnk` link at DIR's top that leads to a volume-GUID link or a `subst` drive is refused, by
  the native layer, with and without `--pack`. 8637e03 accepts all eight. Links of both kinds to free directories
  are still accepted.
- LC5-2: `SHELLOPTS=noglob` and `BASHOPTS` with `failglob`/`nullglob` no longer turn the top-level loop off.
- LC5-3: a NAME through a tracked `g -> .git` is refused, and nothing is left behind.
- LC5-4: U1 and U2 are killed (table below).
- The rendered prompts are byte-identical to 09b476d. The full kit suite and the evidence check pass.

But the layers still disagree in one place, and both are wrong there. The shell's `resolve` prints the path a link
at DIR's top leads to through `$(...)`, and command substitution drops trailing newlines. A link to a directory whose
name ends in a newline is therefore checked, in both layers, at the name without the newline. That can be a different,
free directory. The native layer gets its `E` item from the shell's output, so it inherits the wrong path. From the
checkout, `cd node_modules/s && git log` prints the other repository's commit (LC6-1). The seam is older than this
round (lead integration 2, 69d1d03). Round 6 did not add it, but it is inside the promise the header makes.

## Findings

| id | severity | finding |
|---|---|---|
| LC6-1 | S3 | **A link at DIR's top whose target ends in a newline is checked at another path, in both layers.** **Mechanism.** `real=$(resolve "$entry")`: `resolve` ends in `physd`, which is `$(cd -P -- "$1" && pwd -P)`. Both command substitutions strip every trailing newline. `pwd -P` prints `<fx>/x/repo<LF>`, and the script keeps `<fx>/x/repo`. `guard_link` then checks that path. Its ancestors and `is_repo` all read a directory that is not where the link leads. Nothing checks that the resolved path exists, or that it is the entry's own target. The native layer checks `REAL_PATHS` (`E` items), which hold the same stripped string. For a `sys` or `.lnk` link, Windows sees a plain file, so the native scan of DIR's top cannot check it either. MSYS stores a newline in a name as U+F00A, so the two directories can sit side by side. **Reproduced** on this host (Git 2.55.0.windows.5, bash 5.3.15, Python 3.14). `<fx>/x/repo` is a free, empty directory. `<fx>/x/repo<LF>` (`repo\uf00a` to Windows) is a work tree with history and a commit `SECRET-FIX-COMMIT`. `<fx>/dep/s` was made with `MSYS=winsymlinks:sys ln -s <fx>/x/repo<LF>`. `--link node_modules=<fx>/dep` exits 0 with "ok", with and without `--pack` (`out/co1`, `out/co2`). In each checkout, from `node_modules/s`: `git rev-parse --show-toplevel` names the newline directory, `git log --oneline -1` prints `d7cf399 SECRET-FIX-COMMIT`, and `cat brief.md` prints its file. The same with an `MSYS=winsymlinks:lnk` shortcut (`out/c5`): exit 0, and `git log` prints the commit. 8637e03 accepts it as well. **Controls, as expected:** a native symlink to the same directory is refused by the native scan, which follows it to the real name (`out/c3`, exit 2, nothing made); and a `sys` link to a newline directory with no free twin is refused natively, because the stripped path "does not resolve" (`out/c4`, exit 2). **Where else** (reading, untested): the same stripping applies to each `readlink` hop in `resolve`, and to `real=$(physd "$up")` in the new link-parent check (LC5-3). On a host whose file names can hold a newline, a tracked symlink `a<LF> -> .git` next to a tracked directory `a`, with NAME `a<LF>/hooks`, would be checked at `a` and made in `.git` (LC5-3's class, S4). On Linux or macOS, only the shell layer runs, so a plain symlink at DIR's top to a newline-named repository would pass (expected, untested). **Why S3** (the rubric of LC2-1 to LC5-1): the header promises that no link at DIR's top, nor the parents of where it leads, "reaches a git repository ... by any spelling native programs resolve (both layers below)". That fails on the kit's own host, and the checkout reaches a repository's history and files. The link is at DIR's top, which the docs place inside the guard; nothing assigns odd file names to the host. It is not S2, because the host must create a repository directory whose name ends in a newline, on purpose or through an unusual tool. **Fix (the lead decides):** check identity, not only spelling: after `resolve`, refuse unless `[ "$entry" -ef "$real" ]`, which follows the link the way MSYS tools do. I verified on this host that the test is false for the newline case and true for a free control and for a `sys` link to a GUID link (its resolved path is the GUID link itself, which `-ef` sees through; verified). Do the same for the link-parent check (`[ "$up" -ef "$real" ]`). Alternatively, keep the trailing newlines (`p=$(cd -P -- "$1" && pwd -P && echo .)`, `p=${p%.}`, `p=${p%$'\n'}`) in `phys`, `physd`, `resolve` and each `readlink`. Add a test: a `sys` link and a `.lnk` shortcut at DIR's top to a newline-named work tree that has a free twin, refused with and without `--pack`; and a guard-removal proof. |

## Check 5's findings, re-run

### LC5-1, against my own fixture

`other` is a work tree with history, holding `node_modules/pkg`. `L/g` is a symlink to the volume-GUID spelling of
`other/node_modules`, and `L/f` one to a free directory. Git Bash does not see `L/g` as a link (verified). `R:` was
`subst`-mapped to `other/node_modules` for the run and removed after it.

| link at DIR's top | head 2b3a163 (plain / `--pack`) | 8637e03 (plain / `--pack`) |
|---|---|---|
| `sys` -> `L/g` | refused N / refused N | accepted / accepted |
| `.lnk` -> `L/g` | refused N / refused N | accepted / accepted |
| `sys` -> `/r/pkg` (subst) | refused N / refused N | accepted / accepted |
| `.lnk` -> `/r/pkg` (subst) | refused N / refused N | accepted / accepted |
| control: `sys` -> `L/f` | accepted / accepted | accepted / accepted |
| control: `.lnk` -> `L/f` | accepted / accepted | accepted / accepted |
| control: `sys` -> free directory | accepted / accepted | accepted / accepted |

"N" is a refusal "as native programs resolve it". Every refusal exited 2 and made nothing. Verified.

### LC5-2

A `sys` link at DIR's top to `other/node_modules`, which only the shell layer refuses:

| environment | head (plain / `--pack`) | 8637e03 (plain / `--pack`) |
|---|---|---|
| `SHELLOPTS=noglob` | refused / refused | accepted / accepted |
| `SHELLOPTS=braceexpand:noglob` | refused / refused | accepted / accepted |
| `BASHOPTS=failglob` | refused / refused | exit 1 ("no match"), nothing made |
| `BASHOPTS=nullglob` | refused / refused | refused / refused |
| `SHELLOPTS=noglob BASHOPTS=failglob:nullglob` | refused / refused | accepted / accepted |

I also checked the lead's statement that bash does not apply an inherited `GLOBIGNORE`. Exported as `g/*:g/.*`, it
arrives as a variable, but globs still match. Set inside the script, it hides the entries. Verified.

### LC5-3

The base tracks `g -> .git` (mode 120000) and is checked out with `core.symlinks=true`:

| NAME | head | 8637e03 |
|---|---|---|
| `g/hooks` | refused, "is inside the checkout's git directory"; nothing left | accepted: `.git/hooks` is a link to the host directory |
| `g/info/x` | refused; nothing left | exit 1 from `ln`, and the checkout is left behind |

The host hooks directory is unchanged after every run. Verified.

### LC5-4

U1 and U2 are in the guard-removal table below.

## Hunting for other disagreements between the layers

What I tried besides LC6-1, with the results:

| attempt | result |
|---|---|
| `GLOBIGNORE` exported to hide DIR's entries from the loop | not applied by bash; no effect (verified) |
| a trailing-dot NAME (`nm.`): would Windows drop the dot so that the exclude line misses the link? | MSYS keeps the dot (`nm.` on disk), `git status` is clean (verified) |
| a relative `sys` target through a GUID link at DIR's top (`g/../..`) | by reading: Git Bash and Windows both drop `..` by spelling here, so the shell's resolution is where MSYS tools land, and `E` checks it natively (expected, untested) |
| a `sys` link whose target ends in a trailing dot or space | by reading: MSYS keeps the name as written, so the shell checks the real directory and refuses it there; the native `E` item may check another spelling, but a path must pass both layers (expected, untested) |
| the native removal (`--discard`) meeting a `sys` link or a junction inside the checkout | by reading: a `sys` link is a plain file to Windows and is unlinked; reparse points are removed as entries. Mutants D1-D3 pin it |
| `CDPATH` from the environment with a relative TARGET or DIR | by reading: `cd` may print the path twice and the check reads a garbled path, but the checkout is made, or the link points, at that same string, so check and use agree; on Windows the native `T` item fails closed |

## Rendered prompts

The lead's render driver (read before use: it renders `run.template.js` at 09b476d and in the working tree through
the test module's `run_config`/`execute_template` with `GOLDEN_HOST`, for the fixture and shared manifests, each with
`cause_in_prompt` absent, true and false, and compares every call as sorted JSON). **60 calls, 0 differ.** The fix
prompt sha256 prefixes are `5e66cf5f4d0c141c` (fixture) and `54a0353d503c950d` (shared), the `FIX_PROMPT_GOLDEN`
values. `run.template.js` differs from 09b476d by one comment. The prompt files, `classification.md`,
`protocol.template.json` and `subject-pack/shared/` are unchanged. Verified.

## Diff and hygiene

- `git diff --name-only 8637e03 2b3a163` lists six files: `historyless-checkout.sh`, `test_calibration_kit.py`, the
  kit README, the subject-pack README, `CHANGELOG.md` (one clause in the existing entry) and integration 6's report.
  All are permitted. Verified.
- `git ls-files --eol` gives `i/lf w/lf` for every file changed since 09b476d. The added lines hold no absolute host
  path, session or run id, or model name (grep). Verified.
- 2b3a163's message has the five parts, and it names the model only in the trailer. Verified.

## Guard-removal proofs (re-run in scratch copies)

I re-ran the lead's mutation driver from my own copy, into my own scratch folder, after reading it. For each old
mutant, it diffs check 5's mutant script against 6b952de's script (I confirmed that `base6.sh` is byte-identical
to 6b952de's) and re-applies the diff to 2b3a163's script. The new mutants are exact replacements. Each runs in a
plain copy of `tools/test_calibration_kit.py`, `tools/calibration` and `tests/fixtures/calibration`,
four in parallel, with `MSYS=winsymlinks:nativestrict`. I added two mutants of my own.

- **Control:** 2b3a163 on the union of the mutants' tests: **21 tests, 0 red.**
- **Old mutants (rounds 4 and 5): 70 of 70 red, each with exactly round 5's red set** (0 differ). Seven hunks
  (M14, ND, NJ, NN, NP, NS, R6) no longer apply with `patch -F0`, because new lines sit in their context. They were
  applied as one exact replacement each, only where the removed block is unique, as the lead did. JR is red on the
  new volume-mount-point junction case.
- **New mutants:**

| mutant | removes | result |
|---|---|---|
| V1, V2 | `E` items not handed over / not checked | red: LC5-1 test |
| O1, O2, O3 | `set +f` / the `shopt` line / `failglob` not reset | red: options test |
| O4 | `failglob` reset only (`nullglob` kept) | green, equivalent: I agree with the lead's reasoning (an unmatched pattern dropped by `nullglob` is a word the loop skips anyway) |
| K1-K6 | each shell and native part of the link-parent check | red: link-parent test |
| D1, D2, D3 | removal by `rm -rf` / no removal / removal that enters links | red: link-parent test |
| U1, U2 | check 5's survivors | red: unreadable-marker test, link-name test |
| W2 (mine) | the `E` item gets DIR instead of the path the shell resolved | red: LC5-1 test |
| W4 (mine) | the native removal does not clear read-only files (git's objects) | red: link-parent test |

No test pins LC6-1, so no mutant can show it. Its fix needs a test and a proof of its own.

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` at 2b3a163, `MSYS=winsymlinks:nativestrict` | 135 tests OK, 0 failed, 0 skipped, 1827 s, exit 0. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| LC5-1..LC5-3 reproductions, head against 8637e03 | closed (tables above). Verified |
| LC6-1 reproduction | accepted at head and at 8637e03 (`sys` and `.lnk`). Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

**Untested:**

- The IC4-1 and LC5-1 runs against the read-only MoonAliza clone. I reproduced LC5-1 and LC6-1 on my own fixtures
  only. The lead's report gives 24 refused clone variants, which I did not repeat.
- Hosts other than this Windows 11 / Git Bash one (LC6-1 on POSIX hosts is expected, see above).
- The newline variants at `readlink` hops and in the link-parent check (by reading).

## For the lead

1. **LC6-1 (S3):** do not trust a path that came through `$(...)` as a link's destination. Either refuse unless
   `[ "$entry" -ef "$real" ]` after `resolve`, and `[ "$up" -ef "$real" ]` in the link-parent check, or keep the
   trailing newlines in `phys`, `physd`, `resolve` and each `readlink`. Add a test: a `sys` link and a `.lnk` shortcut at DIR's top to a
   newline-named work tree that has a free twin, refused with and without `--pack`, with a control. Add a
   guard-removal proof.

## What I got wrong and fixed

- **My first fixture tried `git init "x/repo<LF>"`.** Native git got a raw newline in its argument and failed
  ("Invalid argument"). I made the repository from inside the directory instead, where git gets the mapped name as
  its working directory.
- **`cmd //c mklink /D` failed under Git Bash's argument conversion** ("Invalid switch"). I made the GUID links with
  Python's `os.symlink` instead.
- **My first edit to the mutation driver went through a shell heredoc**, which collapsed the backslashes and left the
  driver unparsable. I restored the copy and made the edit with the file tools. The driver parses (`ast.parse`)
  before the run.
