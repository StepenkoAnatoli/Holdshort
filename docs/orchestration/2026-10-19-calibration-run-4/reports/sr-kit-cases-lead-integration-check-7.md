# sr-kit-cases, lead integration check 7 (refute-first, fresh context): LC6-1 after lead integration 7

Checked: branch `build/sr-kit-cases` at 3f23728 (lead integration 7) on e62541d, with lead integrations 2-6, all
against 09b476d. I read the change against check 6's LC6-1, the threat model in the script's header and README step
3, and integration 7's report. I wrote none of the change. This report is the only file this round adds. Every run
had TEMP and TMP on the gittoken `.tmp-gate` folder. Git ran with a hermetic config (`GIT_CONFIG_GLOBAL` on a scratch
file, `GIT_CONFIG_NOSYSTEM=1`). The link cases ran with `MSYS=winsymlinks:nativestrict`, except where a row names a
`sys` or `.lnk` link. Host: Windows 11, Git 2.55.0.windows.5, bash 5.3.15, Python 3.14.7. Below, `<fx>` is my
fixture folder under `.tmp-gate`, and `<LF>`, `<CR>` and `<TAB>` stand for a newline, carriage return or tab inside
a name (MSYS stores them as U+F00A, U+F00D and U+F009). I did not touch the MoonAliza clone this round (see
"Untested").

**Verdict: FIX**, for one S3 (LC7-1) and one S4 (LC7-2). Integration 7 closes LC6-1 as check 6 named it, and every
other variant I could build of a string losing or changing a path between the layers:

- LC6-1: a `sys` link and a `.lnk` shortcut at DIR's top to `x/repo<LF>` (a work tree beside a free `x/repo`) are
  refused, "not proved", with and without `--pack`; nothing is made. e62541d accepts all four, and `git log` in the
  checkout prints the other repository's commit.
- Its CR twin (`x/cr<CR>` beside `x/cr`) and six trailing-dot variants are refused; e62541d accepts them, and two of
  them write into or delete the host's own directory there.
- The LC5-1 variants, 8.3 short names, NFC/NFD twins and a lone-surrogate native link are refused as before.
- The rendered prompts are byte-identical to 09b476d. The full kit suite and the evidence check pass. The
  guard-removal proofs hold (table below).

But one string in `resolve` is still not proved, and integration 7's report calls the case harmless. For a link at
DIR's top that leads to a **file**, `resolve` computes the file's directory as `physd "$(dirname -- "$p")"`. The
inner command substitution strips the trailing newline of the directory's name before `physd` sees it, so `physd`
proves its `pwd -P` against the stripped string, not against the link's directory. The check after it,
`[ "$q" -ef "$p" ]`, compares files, and a hard link is the same file. So a file in `x/hl<LF>` (a work tree) with a
hard-linked twin in a free `x/hl` passes every check, and the parents of `x/hl` are checked instead of the
repository's (LC7-1). Separately, the exclude line the script writes for each link is a string git parses as a
pattern, and nothing proves it ignores the link (LC7-2, older than this round).

## Findings

| id | severity | finding |
|---|---|---|
| LC7-1 | S3 | **A link at DIR's top to a file in a newline-named work tree is checked at another directory, through a hard link.** **Mechanism.** `resolve`, file branch: `d=$(physd "$(dirname -- "$p")")`. `dirname` prints `<fx>/x/hl<LF>` and its own newline, and `$(...)` strips both, so `physd` gets `<fx>/x/hl`. `physd` proves its `pwd -P` against its argument (`[ "$p" -ef "$1" ]`), which is that stripped string, so the proof holds. `q=<fx>/x/hl/brief.md`, and `[ "$q" -ef "$p" ]` holds because `<fx>/x/hl/brief.md` is a hard link of `<fx>/x/hl<LF>/brief.md` (the same file id, verified with `ls -i`). `guard_link` then checks `<fx>/x/hl` and its parents, which are free. The native `E` item gets the same string, and its samestat holds for the same reason. For a `sys` or `.lnk` link Windows sees a plain file, so the native scan of DIR's top cannot see where it leads. **Reproduced** on this host: `<fx>/x/hl<LF>` is a work tree with a commit `SECRET-HL` and a file `brief.md` (`SECRET-BRIEF`); `<fx>/x/hl` is a free directory holding a hard link of that `brief.md`; `<fx>/dephl/s` is a `sys` link and `<fx>/dephll/s` a `.lnk` shortcut, each to `<fx>/x/hl<LF>/brief.md`. `--link node_modules=<fx>/dephl` exits 0 with "ok", with and without `--pack`, and so does the `.lnk` case (3 of 3); e62541d accepts all three too. In each checkout `cat node_modules/s` prints `SECRET-BRIEF`; `readlink node_modules/s` names `<fx>/x/hl<LF>/brief.md`, and `cd` to that link text's directory, then `git log --oneline -1`, prints `e91fef2 SECRET-HL`, with `git rev-parse --show-toplevel` naming `<fx>/x/hl<LF>`. **What it does not reach:** `node_modules/s/..` fails ("Not a directory"), so the checkout cannot climb to the repository through the link itself, and the file read through it is the host's own hard-linked copy. The repository is reached through the path the script wrote into the link, which a candidate can read. **Integration 7's report is wrong here:** its observation says a hard link "changes no check", because a link to a file "is followed to its directory's physical path"; that path is computed from the stripped string. **Why S3** (the rubric of LC2-1 to LC6-1): the header and README step 3 promise that no link at DIR's top, nor the parents of where it leads, reaches a git repository by any spelling, and integration 7 claims every resolved path string is proved by identity. Both fail on the kit's own host for this string. It is not S2: the host must make a newline-named work tree and a hard link out of it. It is narrower than LC6-1 (no climb through the link), which the owner may weigh. **Fix (verified on a scratch copy; the lead decides):** in `resolve`, take the parts through the round's own helpers: `spell_dir d "$p"; d=$(physd "$d") \|\| return` and `spell_base t "$p"; q=${d%/}/$t`. Then `physd` proves `pwd -P` against the exact directory and fails closed: on my copy all three cases exit 2 with nothing made ("the path it resolves to is not proved to name the file it came from"), and a `sys` link to a free directory is still accepted. Add a test (a `sys` link and a `.lnk` shortcut to a file in a newline-named work tree whose free twin holds a hard link of it, with and without `--pack`) and a guard-removal mutant that restores the inner `$(dirname)`. |
| LC7-2 | S4 | **The exclude line for each link is not proved to ignore it; git parses it as a pattern.** The script writes `printf '/%s\n' "$NAME" >> .git/info/exclude` and promises (header, `--link`) "so a candidate's `git add -A` never commits it". Nothing checks that the line ignores the link. Reproduced with a `nativestrict` link to a free directory, then `git add -A` in the checkout: NAME `[x]` is read as a character class, so the link stays untracked and is staged as a 120000 symlink whose blob is the host's absolute path. NAMEs `q?m` and `lt<` are stored by MSYS as U+F03F and U+F03C, so the ASCII pattern misses and the link is staged. NAME `trs ` (trailing space) loses the space to gitignore parsing, and `git add -A` fails ("unable to stat 'trs '"). NAME `a<LF>b` writes the two lines `/a` and `b`: the link is untracked, and `b` hides every file named `b` in the tree, so a candidate's new `src/b` is silently left out of its commit (`git check-ignore -v src/b` names `.git/info/exclude:2:b`). A plain NAME is clean. **Why S4:** it reaches no repository and NAME is the host's own argument, but it breaks a header promise about what a candidate commits (an absolute host path in a commit, or a file dropped). The line dates from dc2d8c9, so it is older than this round, like LC3-2..LC3-4. **Fix (the lead decides):** refuse a NAME outside a safe set (for example `[A-Za-z0-9._-]` and `/`, no segment ending in a space or dot) or escape the pattern, and after writing it prove each link is ignored (`git -C "$TARGET" check-ignore -q --no-index -- "$NAME"`), refusing otherwise. |

## LC6-1 and its class, re-run

Each row: head (3f23728) against e62541d, same fixture, same arguments. "refused" means exit 2, nothing made, and
the host's directories untouched.

| case | fixture | head | e62541d |
|---|---|---|---|
| LC6-1, `sys`, plain | `<fx>/dep/s` -> `x/repo<LF>`, a work tree beside a free `x/repo` | refused, "not proved" | exit 0; `git log` in `node_modules/s` prints `SECRET-FIX-COMMIT` |
| LC6-1, `sys`, `--pack` | the same | refused | exit 0, the same |
| LC6-1, `.lnk`, plain and `--pack` | a shortcut to the same | refused (2 of 2) | exit 0 (2 of 2) |
| controls | `sys` and `.lnk` links to a free directory | accepted | accepted |
| CR twin | `sys` link to `x/cr<CR>` (work tree) beside a free `x/cr` | refused | exit 0 |
| tab name | `sys` link to `x/tb<TAB>` (work tree) | refused ("inside the git repository") | refused |
| R12-dot | target `tw/co.` beside the host's `tw/co` | refused, `tw/co` untouched | exit 0, wrote `.git`, `README.md` and `a` into the host's `tw/co` |
| R13-dot | the same with `--link` | refused | exit 0, then deleted the host's `tw2/co` and its `host.txt` |
| R14-dot | source `x3/rs.` beside a clone `rs` | refused | exit 0 |
| R8-dot | DIR `x2/gd.`, a volume-GUID link into a repository, beside a free `gd` | refused natively | exit 0 |
| R9-dot | a `sys` link to `x2/gd.`, `--pack` | refused natively | exit 0 |
| R10-dot | entry `s.`, a volume-GUID link into a repository, beside a free `s` | refused natively | exit 0 |
| LC7-1 | `sys` (plain, `--pack`) and `.lnk` links to `x/hl<LF>/brief.md`, hard-linked into a free `x/hl` | **exit 0 (3 of 3)** | exit 0 (3 of 3) |

## LC5-1 and check 6's regressions, re-run

LC5-1 variants: `sys` and `.lnk` links at DIR's top to `L/g` (a volume-GUID link to `other/node_modules`, inside a
work tree), to `/r/pkg` (`R:` `subst`-mapped to `other/node_modules` for the run and removed after it), and to `L/f`
(free), each plain and with `--pack`: 12 runs per script. Head: the 8 `g` and `r` runs are refused "as native
programs resolve it", and the 4 `f` runs are accepted. e62541d: the same. Verified. The suite's tests for LC5-2,
LC5-3, LC5-4 and LC6-1 pass at head (below).

## Hunting for other disagreements between the layers

| attempt | result |
|---|---|
| 8.3 short names (`LONGRE~1`; on for this volume): a `sys` link to one, a target under one, a DIR under one | all refused ("inside the git repository"); MSYS resolves short names, and `-ef` holds. Verified |
| an NFD-named repository beside an NFC-named free twin | refused; NFC and NFD names are distinct and round-trip. The NFC control is accepted. Verified |
| a native link named with a lone high surrogate (`b\ud800x`) beside its MSYS twin `b➳x` | refused natively at both heads (MSYS cannot address the name; the native scan follows it). Verified |
| `:` streams and Win32-only spellings (`other::$INDEX_ALLOCATION`, `other:x`, `other.`, `other `, `OTHER~1`) | MSYS reads them literally (no such directory); `cygpath -m` maps the special characters to private-use code points, and each result passes `-ef`. Verified |
| a backslash in a target | `dirname` and `basename` split on `\` as MSYS path conversion does; consistent. Verified |
| argv from MSYS to the native layer: tabs, newlines, quotes, empty strings, backslashes | round-trip; the four-word item grouping cannot shift. Verified |
| case, and the Kelvin sign (U+212A) | the native `same()` uses `normcase` (LCMapString), so a Kelvin-sign twin is a false refusal only, in the native "inside" test; the shell's `-ef` decides the real case. Verified |
| a path replaced between check and use | by reading: a change by the host's own processes during the run, like one after it; the lead notes the `mkdir` race. Not a finding (the host's concurrency, outside the threat model) |
| a `readlink` hop whose text ends in a newline | by reading: the hop's `-ef` holds through a hard link too, but the hop's directory is then the same directory, so no other parents get checked; only the file branch's `$(dirname)` (LC7-1) changes the directory. Expected, untested |

## Rendered prompts

My render driver renders `run.template.js` at 09b476d and in the working tree through the test module's
`run_config`/`execute_template` with `GOLDEN_HOST`, for the fixture and shared manifests, each with
`cause_in_prompt` absent, true and false, and compares every call as sorted JSON. **60 calls, 0 differ.** The fix
prompt sha256 prefixes are `5e66cf5f4d0c141c` (fixture, 2580 bytes) and `54a0353d503c950d` (shared, 3066 bytes),
the `FIX_PROMPT_GOLDEN` values. `run.template.js` differs from 09b476d by one comment. The prompt files,
`classification.md` and `protocol.template.json` are identical to 09b476d. Verified.

## Diff and hygiene

- `git diff --name-only e62541d 3f23728` lists five files: `historyless-checkout.sh`, `test_calibration_kit.py`, the
  kit README, `CHANGELOG.md` and integration 7's report. All are permitted. Verified.
- `git ls-files --eol` gives `i/lf w/lf` for all five; `bash -n` passes. The added lines hold no absolute host path,
  session or run id, or model name (grep). Verified.
- 3f23728's message has the five parts, and it names the model only in the trailer. Verified.

## Guard-removal proofs (re-run in scratch copies)

I re-ran the lead's mutation driver from my own copy, into my own scratch folder, after reading it. For each old
mutant it diffs the earlier checks' mutant script against 6b952de's script (I confirmed `base6.sh` is byte-identical
to 6b952de's) and re-applies the diff to 3f23728's script; the new mutants are exact replacements. Each runs in a
plain copy of `tools/test_calibration_kit.py`, `tools/calibration` and `tests/fixtures/calibration`, four in
parallel, with `MSYS=winsymlinks:nativestrict`. I added three mutants of my own. A dry run applied all 111.

- **Control:** 3f23728 on the union of the mutants' tests: **24 tests, 0 red.**
- **Old mutants (rounds 4-6): 70 of 70 red, each with exactly its earlier red set** (0 differ). 29 hunks no longer
  apply with `patch -F0`, because this round's lines sit in their context: 13 were applied as one exact replacement
  (the removed block is unique) and 16 through the lead's ports to the new lines, which I read.
- **New mutants**, first pass on all nine of the round-6 and round-7 tests, then (the shared machine ran about two
  mutants per ten minutes) a second pass of the rest on the tests the lead's own runs found red, read from its
  summaries; my X mutants ran the four round-7 tests:

| mutant | removes | result |
|---|---|---|
| V1, V2 | `E` items not handed over / not checked | red: LC5-1 test (V1 also the native same-file test); all nine tests run |
| O1, O2 | `set +f` / the `shopt` line | red: options test; all nine tests run |
| O3 | `failglob` not reset | red: options test |
| O4 | `failglob` reset only (`nullglob` kept) | green, equivalent, as in check 6 |
| K1-K6 | each shell and native part of the link-parent check | red: link-parent test |
| D1, D2, D3 | removal by `rm -rf` / no removal / removal that enters links | red: link-parent test, plus the round-7 tests the lead named |
| W2, W4 | check 6's mutants | red: LC5-1 and native same-file tests / link-parent and path-string tests |
| U1, U2 | check 5's survivors | red: unreadable-marker test, link-name test |
| I1-I9 | each identity proof of this round (shell `-ef` in `phys`, `physd`, the `resolve` join and hop, `ancestors`, `add_native`, the discard; the native literal samestat; discard by literal) | red, each on the test the lead named (I5 on the mounted-directory test) |
| S1-S6 | each `spell_dir`/`spell_base` back to `$(...)`, and `.`/`..` allowed as the target's last segment | red: path-string test |
| G1, G2, G3 | git given the shell's target / source spelling; git makes the target | red |
| X1 (mine) | `unproved` drops the "not proved" refusal and reports only the plain one | red: path-string and mounted-directory tests |
| X2 (mine) | the native proof stats the plain string instead of its literal spelling | red: native same-file test |
| X6 (mine) | the source checked natively only with `--link` (as before this round) | red: native same-file and Windows-spelling tests |

No test pins LC7-1, and no mutant can show it: restoring the inner `$(dirname)` in `resolve` is the current code.
Its fix needs a test and a proof of its own.

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` at 3f23728, `MSYS=winsymlinks:nativestrict` | 138 tests OK, 0 failed, 0 skipped, 4199 s (the machine was shared), exit 0. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| LC6-1 and its class, head against e62541d | closed (table above). Verified |
| LC5-1 variants, head against e62541d | refused as before (above). Verified |
| LC7-1 reproduction | accepted at head and at e62541d (`sys` plain and `--pack`, `.lnk`). Verified |
| LC7-1 fix on a scratch copy | the three cases refused, the control accepted. Verified (the suite did not run on it) |
| LC7-2 reproduction | as in the finding. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

**Untested:**

- The IC4-1 and LC5-1 runs against the read-only MoonAliza clone. I reproduced on my own fixtures only, and did not
  repeat the lead's clone runs.
- Hosts other than this Windows 11 / Git Bash one. On Linux or macOS only the shell layer runs, so LC7-1 would hold
  there as well, wherever names can end in a newline (expected, untested).
- The full suite on the LC7-1 fix (only my three cases and a control ran on it).

## For the lead

1. **LC7-1 (S3):** in `resolve`'s file branch, use `spell_dir` and `spell_base` instead of the inner `$(dirname)` and
   `$(basename)`, so `physd` proves its result against the exact directory. Correct integration 7's observation
   about hard links. Add the test and the mutant above. Look for any other `$(...)` result passed into a function
   that then proves only against its own argument.
2. **LC7-2 (S4):** refuse or escape NAMEs git would parse as patterns, and prove each link is ignored with
   `git check-ignore` before reporting "ok".

## What I got wrong and fixed

- **My first volume-GUID links were bogus.** I passed the `\\?\Volume{...}` spelling to Python through a bash
  argument, and MSYS rewrote `\\?\` to `\?\`, so the links led nowhere and bash called them unresolvable. I computed
  the GUID inside Python instead (`GetVolumeNameForVolumeMountPointW`), made each link at its literal `\\?\` path,
  and removed the bogus ones.
- **`os.symlink` to `x2/gd.` failed**, because Win32 strips a trailing dot. I made the link at its literal `\\?\`
  path.
- **My first edit to the mutation driver went through a shell heredoc into a Python string**, which turned the `\n`
  escapes into real newlines and left the driver unparsable (check 6 recorded the same mistake). I restored the copy
  and made the edit with the file tools; a dry run applied all 111 mutants before the real run.
- **My first run of the LC7-1 fix did not source my environment file**, so the fixture paths were empty and its
  refusal ("no directory") proved nothing. I re-ran it with the environment; the refusal then names the unproved
  path.
- **I started the new mutants on all nine tests each**, which the shared machine could not finish in reasonable time
  (about two mutants per ten minutes). I stopped the driver after the control, the 70 old mutants and V1, V2, O1, O2,
  and re-ran the remaining 36 on the tests the lead's runs found red (my X mutants on the four round-7 tests). So a
  second-pass mutant is shown red on the lead's tests, not on all nine.
- Some fixture runs hit the two-minute tool timeout under load (other sessions share the machine); I moved them to
  the background and let them finish.
