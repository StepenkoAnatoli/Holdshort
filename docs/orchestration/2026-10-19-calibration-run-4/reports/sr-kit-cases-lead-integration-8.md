# sr-kit-cases, lead integration 8: no path part taken through a command substitution before its proof (LC7-1), and each link proved ignored (LC7-2)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of d4c2c8f (lead integration check 7, FIX:
LC7-1 S3, LC7-2 S4). The change is one commit through the pre-commit hook. This report is part of that commit, so it
cannot name its own sha (the returned gist does). Every run had TEMP and TMP on the gittoken `.tmp-gate` folder. Git
ran with a hermetic config (`GIT_CONFIG_GLOBAL` on a scratch file, `GIT_CONFIG_NOSYSTEM=1`), and the link cases with
`MSYS=winsymlinks:nativestrict`, except where a row names a `sys` or `.lnk` link. Host: Windows 11, Git
2.55.0.windows.5, bash 5.3.15, Python 3.14.7. Below, `<fx>` is a fixture folder under `.tmp-gate`, and `<LF>` stands
for a newline inside a name (MSYS stores it as U+F00A).

**Verdict: DONE.** Both findings are fixed in `historyless-checkout.sh`, each with a test that is red at d4c2c8f and
green now, and each new check has a guard-removal mutant that turns a test red.

- **LC7-1.** `resolve` now spells every part it takes of a path exactly (`spell_dir`, `spell_base`, and a new
  `spell_link` for the `readlink` hop), and hands its result back in `RES`, not through its caller's `$(...)`. So
  `physd` proves the link's real directory, not a string whose trailing newline is already gone. The class is closed:
  no command substitution now sits between a path and its proof anywhere in the script (the audit is below).
- **LC7-2.** A `--link` NAME is kept to letters, digits and `.`, `_`, `-`, `+`, `@`, in `/`-separated parts that are
  not empty and do not end in a dot; anything else is refused before anything is made. After writing each exclude
  line, `git check-ignore` must say that git ignores the link, or the checkout is removed and refused (fail closed).
  That second check also catches a case the character rule cannot: the base tree's own `.gitignore` can re-include
  the name with `!`, and it outranks `.git/info/exclude`.

## LC7-1: the fix and the class

At d4c2c8f, `resolve`'s file branch was `d=$(physd "$(dirname -- "$p")")`. The inner substitution strips the
trailing newline of `<fx>/x/hl<LF>`, and `physd` proves `pwd -P` against its own argument, so the proof held for
`<fx>/x/hl`. The file check after it, `[ "$q" -ef "$p" ]`, holds through a hard link. So a link to
`<fx>/x/hl<LF>/brief.md` (a work tree) whose hard link sits in a free `<fx>/x/hl` was checked at `<fx>/x/hl`.

Now:

```
spell_link() { local r; r=$(readlink -- "$2" && echo .) || return 1; printf -v "$1" '%s' "${r%$'\n.'}"; }
...
    spell_dir d "$p"
    d=$(physd "$d") || return
    spell_base b "$p"
    q=${d%/}/$b
    [ "$q" -ef "$p" ] || return 3
...
    spell_link t "$p" || return 1
```

`resolve` sets `RES` instead of printing, and its caller reads `real=$RES`. The directory branch keeps
`RES=$(physd "$p")`: `physd` proves the string it prints, and that string cannot end in a newline (the inner
`$(pwd -P)` already stripped any), so the outer substitution changes nothing.

**Integration 7's report was wrong here.** Under "Observations" it said a hard link "changes no check", because a
link to a file is followed to its directory's physical path and a directory cannot be hard-linked. That holds only if
the directory string is proved against the link's own directory. It was not: the directory came through `$(dirname)`,
so the proof was made against the stripped twin, and the hard-linked file made the one check that did compare
against the original pass. Check 7 found this (LC7-1). This report corrects the claim; integration 7's report is left
as written.

**The class, audited.** I listed every `$(...)` in the script (`grep -n '\$('`) and sorted each by what it feeds:

| substitution | before its proof? | why it is safe now |
|---|---|---|
| `spell_dir`, `spell_base`, `spell_link` (`$(cmd; echo .)`, then the marker and one newline cut) | no: exact by construction | the `.` marker keeps every trailing newline of the name |
| `phys`, `physd`: `p=$(cd ... && pwd -P)` | no: proved by `[ "$p" -ef "$1" ]` against their own argument | each argument is now an exact string: a user argument, a `spell_*` result, a glob entry, or `$p` itself (LC7-1 was the one call site that passed a substitution) |
| callers `X=$(phys ...)`, `X=$(physd ...)`, `RES=$(physd "$p")` | after the proof | the printed string is the proved one and cannot end in a newline, so the outer `$(...)` keeps it exactly |
| `real=$(resolve ...)` (before) | after the proof, but could cut a proved path | replaced by `RES` (R4 below shows a test sees it come back) |
| `w=$(cygpath -m -- ...)` (`ancestors`, `add_native`, the removal) | no: each proved by `[ "$w" -ef <original> ]` | `cygpath -m` writes a trailing newline in a name as U+F00A (verified), so its output is lossless; and the proof is against the original |
| `NOUT=$(native_guard ...)`, `GIT_LOCAL_VARS`, `probe`, `uname`, `TREE`, `OBJECTS`, `BASE`, the final counts | not paths | messages, object ids and counts |

The native layer reads its paths from argv, which the shell built from proved strings, and proves its own spellings
with `os.path.samestat` (integration 7).

## LC7-2: the fix

At d4c2c8f the script wrote `printf '/%s\n' "$NAME" >> .git/info/exclude` and checked nothing. My reproduction at
d4c2c8f, a `nativestrict` link to a free directory under each NAME, then `git add -A` in the checkout:

| NAME | d4c2c8f | now |
|---|---|---|
| `[x]` | ok; `git add -A` stages `[x]`, a 120000 symlink holding the host's absolute path | refused, nothing made |
| `q?m`, `lt<` | ok; staged (MSYS stores `?` and `<` as U+F03F and U+F03C, which the ASCII pattern misses) | refused |
| `a<LF>b` | ok; staged, and the line `b` hides every `b` in the tree | refused |
| `trs ` | ok; `git add -A` fails ("unable to stat 'trs '") | refused |
| `nm*`, `#c`, `!n`, `a.` | ok; nothing staged here, but the line is a wildcard, a comment, a negation, or a name Windows reads without its dot | refused |
| `./x` | ok; `git add -A` stages `x` | refused |
| `x/` | exit 1 from `ln` under `set -e`, the checkout left behind | refused, nothing made |
| `a//b` | refused (its parent is no directory) | refused by the name rule |

The rule is a whitelist in one `case` after the `.git` segment loop:
`*[!A-Za-z0-9._@+/-]* | */ | *//* | *. | *./*` (spelled out letter by letter, so no locale's collation can widen a
range). An empty name, a leading `/`, any `..`, `\` and `:` are already refused by the earlier plain-path rule. Then, for each link, after its
exclude line is written:

```
git -C "$GIT_TARGET" check-ignore -q -- "$name" \
  || refuse_made "--link $name: git does not ignore the link in the checkout (git check-ignore), ... (LC7-2)"
```

`check-ignore` runs without `--no-index`, so a tracked path would read as not ignored, which is the safe side; and
the earlier rule already refuses a NAME the checkout holds. A host-wide `core.excludesFile` can only add ignores, and
the exclude line itself already ignores a whitelisted name, so it cannot hide a failure that `git add -A` would not
also skip on that host.

## Tests: red first, then green

Two new tests in `tools/test_calibration_kit.py`, and one extended:

- `test_historyless_checkout_proves_the_directory_of_a_file_a_link_leads_to` (LC7-1). Fixture: `x/hl<LF>` is a work
  tree holding `brief.md`, and a free `x/hl` holds a hard link of it. A `sys` link and a `.lnk` shortcut to
  `x/hl<LF>/brief.md`, each with and without `--pack`, must be refused "not proved", with nothing made. Controls,
  accepted with and without `--pack`: a `sys` link to a file `ff/f<LF>` (a name ending in a newline, no twin) and a
  `sys` link to a free directory.
- `test_historyless_checkout_proves_git_ignores_each_link` (LC7-2). Eighteen NAMEs, each with and without `--pack`,
  must be refused by the name rule with nothing made: `[x]`, `q?m`, `a<LF>b`, `trs `, `lt<`, `nm*`, `#c`, `!n`,
  `s p`, `a<TAB>b`, `xé`, `a//b`, `./x`, `x/`, `a.`, `.`, `src/v.`, `src/./v`. A base tree whose `.gitignore` holds
  `!/deps` and `!/src/vendor` must be refused by the `check-ignore` proof, the checkout removed. Controls: links named
  `node_modules`, `.venv`, `@scope`, `a+b_c-d.e` and `src/vendor` are made; after `git add -A`, the neighbouring files
  (`node_modulesx`, `src/node_modules`, `docs/.venv`, `.venvx`, `@scopex`, `a+b_c-d`, `src/vendorx`, `b`) are all
  staged and no link is.
- `test_historyless_checkout_proves_each_path_string_names_the_file_it_came_from` (LC6-1's test). Each case now
  carries its reason. The `readlink`-hop case (a link `x/t<LF>` into another repository) now expects "resolving to
  `<other>`/README.md, is inside the git repository": the hop is followed exactly now, so the real reason is reported
  instead of "not proved". The `a<LF>` link-name case now expects the name rule. A new case, a checkout `twin/cand<LF>`
  beside a host directory `twin/cand` with `--link node_modules=...`, must be refused "its parent ... not proved",
  leaving `twin/cand` untouched. That case keeps check 7's S5 mutant red: the name rule now refuses `a<LF>`, which S5's
  old case used.

**Red at d4c2c8f** (the three tests against d4c2c8f's script, in a copy): 3 of 3 FAIL. The LC7-1 test fails with
exit 0 where 2 is expected (the hard-link case accepted); the LC7-2 test fails on `[x]` (accepted, "ok"); the LC6-1
test fails at the hop case, whose reason at d4c2c8f is "not proved". Verified.

**Green now:** the three tests pass (343 s). Verified. The full suite: see "Checks".

## Guard-removal proofs

I ran check 7's copy of the mutation driver, adapted in scratch, with this head's script. Each mutant runs in a plain
copy of `tools/test_calibration_kit.py`, `tools/calibration` and `tests/fixtures/calibration`, three in parallel,
with `MSYS=winsymlinks:nativestrict`. The old mutants (rounds 4-6) are re-applied as before. Each round-6 and round-7
mutant, and check 7's X1, X2 and X6, runs on the tests it was red on in integration 7's and check 7's runs; O4 runs on
the options test. The new mutants run on this round's three tests. A dry run applied all 117: 13 hunks whose context
drifted were applied as one exact replacement of the removed block, and 16 through the earlier ports. Two mutants
were updated to this round's lines: I3 now removes the proof after `q=${d%/}/$b`, and the M14 port now writes
`resolve "$entry" || continue`.

- **Control:** this head on the union of the mutants' tests: **26 tests, 0 red.** Verified.
- **Old mutants (rounds 4-6): 70 of 70 red, each with exactly its earlier red set.** Verified.
- **Rounds 6-7 and check 7's: 36 of 40 red with exactly their earlier red sets.** The other four:

| mutant | result | why |
|---|---|---|
| O4 (`nullglob` kept) | green | equivalent, as in checks 6 and 7 |
| I3 (no proof after the `resolve` join) | green, was red | equivalent now: the join is the physical path of the exact directory plus the exact name, so the proof always holds. Kept as defense in depth |
| I4 (no proof after the `readlink` hop) | green, was red | equivalent now: the hop's text is exact and is joined to the link's own physical directory, as the kernel does. Kept as defense in depth |
| D3 (the removal enters links) | red on the link-parent test, no longer on the LC6-1 test | the LC6-1 test reached the removal through `--link a<LF>`, which the name rule now refuses before anything is made; the link-parent test still pins the removal |

- **New mutants (this round), each on the three new or changed tests:**

| mutant | restores or removes | red |
|---|---|---|
| R1 | `d=$(physd "$(dirname -- "$p")")` (LC7-1 itself) | the LC7-1 test |
| R2 | `q=${d%/}/$(basename -- "$p")` | the LC7-1 and LC6-1 tests |
| R3 | `t=$(readlink -- "$p")` | the LC7-1 and LC6-1 tests |
| R4 | `real=$(printf '%s' "$RES")` (the caller's substitution back) | the LC7-1 test |
| N1 | no name rule | the LC7-2 and LC6-1 tests |
| N2 | no `git check-ignore` proof | the LC7-2 test |
| N3 | the name rule's character class only (no `*/`, `*//*`, `*.`, `*./*`) | the LC7-2 test |

All seven red. Verified. Every guard this round adds is pinned by a test.

## Reproductions, re-run on this head

| reproduction | d4c2c8f | now |
|---|---|---|
| LC7-1: `sys` link to `x/hl<LF>/brief.md` (hard link in a free `x/hl`), plain and `--pack`; `.lnk` shortcut | exit 0, "ok" (3 of 3) | refused "not proved", nothing made (3 of 3). Verified |
| control: `sys` link to a free directory | ok | ok. Verified |
| control: `sys` link to a file `ff/f<LF>` (no twin) | refused "not proved" (a false refusal) | ok. Verified |
| LC7-2 NAMEs | the table above | the table above. Verified |
| LC6-1: `sys` link and `.lnk` shortcut at DIR's top to `x/repo<LF>` (a work tree beside a free `x/repo`), plain and `--pack` | refused "not proved" (4 of 4) | refused "not proved", nothing made (4 of 4). Verified |

**IC4-1 and LC5-1, against the read-only MoonAliza clone.** I re-ran the earlier rounds' reproduction script (in scratch) with
this head's script against the clone's `node_modules`: the clone's own `node_modules` directly; a volume-GUID link, a
`GLOBALROOT` link, a chain and a junction to it; a link of each of those kinds at a dependency directory's top; and
MSYS `sys` and `.lnk` links at the top to a volume-GUID link and to a `subst` drive of the tree; each with and without
`--pack`. **24 of 24 refused, exit 2, nothing made**, each for the clone ("is inside the git repository", or the
native layer's reading of the link). The clone's `git status --porcelain --ignored` is the same before and after, and
its `.git/index` mtime did not change. Nothing was written in the clone. Verified.

## Behaviour changes a host can see

- A `--link` NAME outside the rule is refused before anything is made. The usual dependency names (`node_modules`,
  `.venv`) pass it, and the shared pack's `checkout.links` is empty.
- A checkout whose base tree re-includes a link's name (`!/NAME` in a tracked `.gitignore`) is now refused and
  removed.
- A link at DIR's top to a file whose directory name ends in a newline is now accepted when that directory is free
  (a false refusal at d4c2c8f).
- The `readlink`-hop refusal now names where the hop leads ("inside the git repository") instead of "not proved".

## Observations, not fixed

- **A flaky gate-timeout test (grade.sh, out of this round's scope).** In my one full-suite run,
  `test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing` failed once: "the gate command's child outlived
  the timeout and wrote into the checkout". The machine was heavily loaded then (the suite, three mutant jobs and the
  MoonAliza reproduction at once). The test then passed 3 of 3 times on its own, with the mutant jobs still running.
  `grade.sh` is untouched since 7ae4577, so this is not from this round. A likely cause (untested): `run_bash`
  swallows a `taskkill` that fails or overruns its 60 s, and `taskkill /T` takes the process tree at one moment, so a
  child MSYS bash is still forking can be missed. Worth its own unit; I did not change `grade.sh`, which this round
  may not touch.
- A checkout whose own path ends in a newline, with `--link`, is refused: `physd` cannot spell the link's parent
  exactly (`pwd -P` runs in a substitution), so it fails closed. This is a false refusal, older than this round
  (integration 7 kept the checkout's own name exactly; the link step then proves its parent).
- OBS-1 stays out of scope, as briefed.

## Checks

| check | result |
|---|---|
| `python -W error::SyntaxWarning tools/test_calibration_kit.py`, `MSYS=winsymlinks:nativestrict`, before the README and CHANGELOG edits | 140 tests, 139 OK, 1 failed (the gate-timeout flake above, `grade.sh`, which this round does not touch), 4409 s on a heavily loaded machine. Verified |
| that test alone, three times | OK 3 of 3. Verified |
| after the doc edits: `Docs`, `KitCaseDocs`, `Hygiene`, `SharedPack` | 36 tests OK. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations. Verified |
| `python tools/check_secrets.py`; `python tools/check_credential_hygiene.py` | clean; clean (0 new findings). Verified |
| rendered prompts: `run.template.js` at 09b476d and now, through the test module's `run_config`/`execute_template` with `GOLDEN_HOST`, the fixture and shared manifests, `cause_in_prompt` absent, true and false | 60 calls, 0 differ; fix prompts 2580 bytes `5e66cf5f4d0c141c` and 3066 bytes `54a0353d503c950d` (the `FIX_PROMPT_GOLDEN` values). The prompt files, `classification.md` and `protocol.template.json` are identical to 09b476d. Verified |
| `git ls-files --eol` on the six files; `bash -n` on the script | LF everywhere; passes. Verified |
| the added lines: no absolute host path, session or run id, or model name (grep) | none. Verified |
| touched files | `historyless-checkout.sh`, `tools/test_calibration_kit.py`, `tools/calibration/README.md` (step 3), `tools/calibration/subject-pack/README.md` (`checkout.links`), `CHANGELOG.md` (a clause in the sr-kit-cases entry, no new line), and this report. `shared/README.md` untouched. Verified |
| the full regression gate, through the pre-commit hook | verified by the commit landing |

**Untested:**

- Hosts other than this Windows 11 / Git Bash one. On Linux or macOS only the shell layer runs; both fixes are in the
  shell layer and should hold there too (expected, untested).
- The cause of the gate-timeout flake above.
- A NAME rule wider than the whitelist (for example, escaping with `\`): I refused instead, because a refusal is
  simpler to prove and every name the kit uses passes.

## What I got wrong and fixed

- **My first red run of the LC7-2 test failed for the wrong reason.** On d4c2c8f, `[x]` was refused with "no
  directory ...", the path printed with every backslash gone. MSYS globs a Windows command-line argument holding `[`, `?` or `*`, and reads its
  backslashes as escapes, so the dependency path lost them. The test now passes the forward-slash shell spelling of
  that path, and the red run fails as it should ("ok" for `[x]`).
- **An edit script written through a shell heredoc lost its escapes.** The heredoc turned `\\n` into `\n`, so the
  script's own assertion failed before it wrote anything. I wrote the script with a file write instead.
- **The LC6-1 test's hop case changed its reason, and I checked that this is no weakening.** With the hop spelled
  exactly, the case is refused for the repository it really reaches. The test now asserts that stronger reason, and a
  mutant restoring `$(readlink)` (R3) must turn it red.
