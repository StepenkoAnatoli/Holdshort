# sr-kit-cases, lead integration 6: every path the shell resolves checked natively, the shell options reset, each link made inside the checkout (LC5-1, LC5-2, LC5-3, LC5-4)

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of 8637e03 (lead integration check 5, FIX).
A narrow round: check 5's four findings and nothing else. The change is one commit through the pre-commit hook. This
report is part of that commit, so it cannot name its own sha (the returned gist does).

**Verdict: DONE.** All four findings of check 5 are closed in `historyless-checkout.sh`, each with a red-first test
and guard-removal proofs:

- **LC5-1 (S3):** every path the shell layer resolves a symlink at DIR's top to is now also handed to the native
  layer and checked there as native programs resolve it (source, pack, repository walk). Before this, DIR, the source,
  the pack and TARGET's parent were the only shell paths handed over. An MSYS `sys` or `.lnk` symlink (seen only by
  Git Bash) to a volume-GUID link or a `subst` drive (resolved only by native programs) is refused.
- **LC5-2 (S4):** the script runs `set +f` and `shopt -u nullglob failglob` right after `set -euo pipefail`. An
  inherited `SHELLOPTS=noglob` or `BASHOPTS=nullglob`/`failglob` no longer changes what the top-level loop sees.
- **LC5-3 (S4):** before each `ln -s`, in both layers, by identity: NAME must not exist yet in the checkout, and its
  real parent must lie inside TARGET and outside TARGET's `.git`. A refusal at that point removes the checkout, never
  through a link.
- **LC5-4 (S4):** check 5's mutants U1 and U2 are now killed, by a stand-in entry whose `stat` fails and by a refused
  NAME after an accepted `--link`.

All 70 earlier guard mutants are still killed, and so are 16 of 17 new ones. The one survivor, O4, is equivalent; the
reason is given below. The rendered prompts are byte-identical to 09b476d. The IC4-1 and LC5-1 reproductions against
the read-only MoonAliza clone are refused in all 24 variants, and the clone is unchanged.

## LC5-1: the native layer checks where the shell says a link leads

**The seam.** The shell layer resolves each symlink at DIR's top (`resolve`) and checks that path with `guard_link`.
Its checks use Git Bash's view of the path. Git Bash cannot see through a volume-GUID symlink (to it, a plain
directory, and `pwd -P` keeps the link's own path) or a `subst` drive (its `/r/...` parents are not the real ones).
The native layer scans DIR's top for reparse points, but an MSYS `sys` link (a system file holding the target) and a
`.lnk` shortcut are plain files to Windows. Verified on this host: Python reports attributes 4 (system) and 1
(read-only), no reparse point. So the shell's resolved path was never resolved natively.

**Fix.** The top-level loop records each `$real` it accepts (`REAL_NAMES`, `REAL_SHOWN`, `REAL_PATHS`). On Windows
each one is handed to `native_guard` as a new item kind `E`, which runs `final()` (strict `realpath`, drive-letter
paths only, fail closed) and then `check()`: the source and pack guards and the repository walk, exactly as for DIR.
The header's "both layers below do this" now holds for every path the shell resolves, and it says so. README step 3
says so too.

**Test** `test_historyless_checkout_checks_where_a_link_only_the_shell_sees_leads_as_native_programs_resolve_it`:

- `L/g` is a GUID symlink to `other/node_modules`, where `other` is a work tree with history. A free drive letter is
  `subst`-mapped to `other/node_modules`, and the mapping is removed in cleanup.
- Refused natively ("other; a dependency tree inside a repository"), with and without `--pack`:
  - a `sys` link to `L/g`;
  - a `.lnk` shortcut to `L/g`;
  - a `sys` link to `/<drive>/pkg`;
  - a `.lnk` shortcut to `/<drive>/pkg`.
- Each case first asserts that Git Bash sees the entry as a link and that Windows does not, so the case cannot pass
  for the wrong reason.
- Controls accepted:
  - a `sys` link and a `.lnk` shortcut to a GUID link to a free directory;
  - a `sys` link to the free directory;
  - a `sys` link through a `subst` drive mapped to the free directory.
- **Red at 8637e03:** FAIL, accepted with exit 0. **Green** on the fix.

## LC5-2: the shell options the loops rely on

Bash takes `SHELLOPTS` and `BASHOPTS` from the environment. I verified on bash 5.3.15 that both are imported, and that
`IFS` and `GLOBIGNORE` are not. The script now sets the globbing it relies on itself. A comment and the header say why.

**Test** `test_historyless_checkout_resets_the_shell_options_its_loops_depend_on`:

- Setup: a `sys` link at DIR's top to `other/node_modules`, which only the shell layer can refuse.
- Environment variants:
  - `SHELLOPTS=noglob`;
  - `SHELLOPTS=braceexpand:noglob`;
  - `BASHOPTS=failglob`;
  - `BASHOPTS=nullglob`;
  - `noglob` together with `failglob:nullglob`.
- Each variant must be refused by the shell layer, with and without `--pack`. A clean DIR is accepted under each one.
- **Red at 8637e03:** FAIL. Under `noglob` the case was accepted with exit 0 (check 5's bypass). **Green** on the fix.

## LC5-3: each link inside the checkout, outside its `.git`

Check 5 proposed a check after the links are made. I check before each `ln -s` instead, so no link is ever made in a
wrong place. Then:

- `[ -e "$at" ] || [ -L "$at" ]` refuses a NAME that exists already. GNU `ln -s DIR dest` puts the link *inside*
  `dest` when `dest` is a directory or a symlink to one. A NAME the base tree tracks (`src`, or a tracked `g -> .git`)
  or an earlier `--link` would otherwise steer the link.
- The shell resolves NAME's parent with `physd` and walks its ancestors with `ancestors`. It refuses the parent when
  it is `-ef` TARGET's `.git` or lies under it, and when no ancestor is `-ef` TARGET.
- On Windows, `native_guard` gets two new items:
  - `C`: TARGET, resolved once;
  - `K`: the parent the shell resolved.
  It checks the same two rules on the native resolution, so a tracked symlink to a volume-GUID path, which Git Bash
  takes for a plain directory, is caught there.
- Any refusal after `git init` calls `refuse_made`. That removes the checkout made so far, then refuses (exit 2). The
  header's "nothing is made" thus still holds.

**The removal must not follow links.** I found this while testing (verified, in my own scratch directory): Git Bash's
`rm -rf` on a directory that holds a tracked symlink to a volume-GUID path walks *into* it, because Git Bash takes that
symlink for a plain directory. It deleted the target directory's files. A base tree can track such a symlink. So on
Windows the removal is done by the native layer's Python (`native_guard --discard`). It removes every symlink,
junction or other reparse point (and every entry it cannot read) as an entry, never entering it. Elsewhere `rm -rf` is
used, which follows no symlink.

**Test** `test_historyless_checkout_makes_each_link_inside_the_checkout_outside_its_git_directory`:

- **Setup.** The case base tracks three symlinks (mode 120000) and is checked out with `core.symlinks=true`:
  - `g -> .git`;
  - `v` -> the GUID spelling of a host directory `far`;
  - `w` -> the GUID spelling of the checkout's own `.git/refs`.
  `.gitattributes` marks `v` and `w` as `symlink=dir`.
- **Refused by the shell**, with and without `--pack`:
  - `g/hooks`: "is inside the checkout's git directory";
  - `g`, `src`, and `a` after `--link a=lib`: "the checkout already holds";
  - `a/b` after `--link a=lib`: "is not inside the checkout".
- **Refused natively**, with and without `--pack`:
  - `v/x`: "is not inside the checkout";
  - `w/hooks`: "is inside the checkout's git directory".
- **After every refusal**, nothing is left of the checkout, and the listings of `far`, the host hooks directory and
  `lib` are unchanged. That pins the no-follow removal.
- **Control:** `--link node_modules=lib --link src/vendor=hooks` is accepted, `g` is still a symlink, and `git status`
  is clean apart from ` M v` and ` M w`. That is git's own round trip of a GUID target: Git for Windows reads it back
  without its `//?/` prefix. The test filters exactly those two lines and says why.
- **Red at 8637e03:** FAIL. `--link g/hooks=...` was accepted with exit 0, as in check 5's reproduction. **Green** on
  the fix.

## LC5-4: U1 and U2

- **U1** (the native `is_link` counts an unreadable entry as no link): the unreadable-marker test now also runs
  `is_link`, taken from the script's heredoc, on a stand-in entry whose `stat` raises `PermissionError`. It must answer
  True, and False when `stat` succeeds.
- **U2** (the NAME check skipped after the first `--link`): the link-name test now passes `.git/hooks` and `.GIT` as a
  second `--link` after an accepted `a=<free>` (with `--pack`), and `c:x` after two accepted links. Each must be
  refused with its own reason.
- Both extensions are green at 8637e03 (no behaviour changed) and red on their mutants (table below).

## Tests: red first, then green

Red run: the final test file against 8637e03's script (`git show 8637e03:...` compared byte for byte), with
`MSYS=winsymlinks:nativestrict`. Six tests:

- The three new tests FAIL, each with an accepted exit 0 where a refusal is due (verified).
- The U1/U2 extensions and the extended junction test pass there, as expected: they are mutant-killers, not
  behaviour changes (verified).

On the fix, all six pass (verified). The full kit suite is under Checks.

## Guard-removal proofs

**Earlier mutants.** I re-applied all 70 of rounds 4 and 5 (45 + 25) to the fixed script. Each is the diff from
6b952de's script to its round-5 mutant. 6b952de's script is the same as 8637e03's.

- 62 applied with `patch -F0` (line offsets only).
- 7 hunks no longer applied because my additions sit in their context: M14, R6, ND, NJ, NN, NP and NS. For those, the
  hunk's removed lines were replaced by its added lines as one exact replacement (each removed block occurs exactly
  once).
- Each mutant ran the tests its round-5 result names.
- The control (the fixed tree on the union of those tests, plus the five new or changed ones) is green: 21 tests.

Result: 69 of 70 give exactly the same red set as in round 5 (verified).

**JR** (junction not a link: the native `is_link` drops its reparse-point clause) came back green. Its round-5 case is
a junction at DIR's top that leads to a GUID link. Git Bash sees that junction as a link, so the new `E` item now
checks where it leads natively and refuses it even without the reparse clause. The clause is still the only guard for
a junction Git Bash does *not* see. A junction whose own target is a volume-GUID path is a volume mount point to Git
Bash, a plain directory (verified).

I added that case to
`test_historyless_checkout_refuses_every_directory_git_takes_for_a_repository_as_native_programs_resolve_it`. It needs
a small helper, `volume_junction`, which writes the mount-point reparse data itself, because `_winapi.CreateJunction`
doubles the `\\?\` prefix of such a target (verified). JR is red again on it: the junction is accepted with exit 0
(verified), and the fix passes it.

**New mutants** (each on the five new or changed tests):

| Mutant | What it removes | Result |
|---|---|---|
| V1 | no `E` items: the shell's resolved paths are not handed over | red: LC5-1 test |
| V2 | the native `E` branch resolves but does not check | red: LC5-1 test |
| O1 | no `set +f` | red: options test |
| O2 | no `shopt` line | red: options test |
| O3 | `shopt -u nullglob` only (`failglob` kept) | red: options test |
| O4 | `shopt -u failglob` only (`nullglob` kept) | **green: equivalent** (below) |
| K1 | no "NAME exists" check | red: link-parent test |
| K2 | no shell `.git` check | red: link-parent test |
| K3 | no shell "inside TARGET" check | red: link-parent test |
| K4 | no native parent check (`C`/`K` items) | red: link-parent test |
| K5 | native `K` without the `.git` rule | red: link-parent test |
| K6 | native `K` without the "inside" rule | red: link-parent test |
| D1 | removal by `rm -rf` on Windows too | red: link-parent test (`rm -rf` stops on the checkout, exit 1, and leaves it behind) |
| D2 | `refuse_made` refuses without removing | red: link-parent test (the checkout is left behind) |
| D3 | the native removal enters directory links | red: link-parent test (a host directory behind a link loses its file) |
| U1 | check 5's: an unreadable entry is no link | red: unreadable-marker test |
| U2 | check 5's: the NAME check only for the first `--link` | red: link-name test |

**O4 is equivalent.** `nullglob` only drops a pattern that matches nothing. The loop's patterns
(`"$dep"/* "$dep"/.[!.]* "$dep"/..?*`) then leave no literal word, and the loop skips such a word anyway (`[ -L ]` is
false for it). The options test runs `BASHOPTS=nullglob` and passes under O4 too (verified). That no other line of
the script depends on `nullglob` is my reading, not a proof (expected). The script still resets `nullglob`, so the loop's comment ("an unmatched
pattern stays literal") stays true.

## IC4-1 and LC5-1, against the read-only MoonAliza clone

All links, the source repository, the pack and the checkouts were in a scratch directory under the gate's temporary
directory. Nothing was written in the clone. The variants were:

- **IC4-1, as in round 5:**
  - the clone's `node_modules` directly;
  - a GUID link to it;
  - a GLOBALROOT link;
  - a chain (a plain link to the GUID link);
  - a junction to the GUID link;
  - a DIR whose top-level entry is a GUID link, a junction, or a native symlink leading there.
- **LC5-1:** a DIR whose top-level entry is a `sys` link or a `.lnk` shortcut:
  - to the GUID link;
  - to `/<drive>/<package>` on a `subst` drive mapped to the clone's `node_modules`.

Each ran with and without `--pack`: 24 runs.

- **At 8637e03:**
  - the 16 IC4-1 runs are refused;
  - all 8 LC5-1 runs exit 0 and make a checkout (the leak reproduced).
- **On the fix:**
  - all 24 runs exit 2, and none makes a checkout;
  - the direct runs are refused by the shell layer;
  - every other run is refused natively ("as native programs resolve it (...moonaliza-gsi-build\node_modules), is
    inside the git repository ...");
  - the LC5-1 runs name the `sys`/`.lnk` entry and the path the shell resolved it to.
- `git status --porcelain --ignored` in the clone was `!! node_modules/ | !! research/raw/.diagnostics.jsonl`, before
  and after both runs. It was unchanged (verified).

(My first `subst` variant mapped the clone's root, which the shell refuses through `/<drive>/.git` even at 8637e03.
Mapping `node_modules` itself is the shape check 5 named, and the one only the native layer catches.)

## Behaviour changes a host can see

- A `--link` NAME that the case base already holds (a file, a directory or a symlink), or one that an earlier
  `--link` made, is refused with exit 2. Before, `ln -s` put the link inside it, or wherever a symlink there led.
- A NAME whose parent does not exist in the checkout (`a/b` with no `a`) is refused with exit 2, and the checkout is
  removed. Before, `ln -s` failed with exit 1 and left the checkout behind.
- Docs changed only for these behaviours:
  - the header;
  - README step 3;
  - the subject-pack README's `checkout.links` entry (a name the base holds, or a parent outside the checkout, is
    refused);
  - a clause in sr-kit-cases' existing CHANGELOG entry (no new line).
  `shared/README.md` is untouched.

## Observations, not fixed (out of this round's scope)

- `SHELLOPTS=noexec` makes bash read the script without running it: exit 0, and nothing is made (verified). A script
  cannot undo that from inside. A host that checks the exit code alone would take that run for a success, but no
  checkout exists, so the next step fails visibly.
- `BASH_ENV` and exported bash functions are also taken from the environment. Both run the host's own code inside
  the script. That is the host's trust boundary, like `PATH`, and not a path the checkout gets.

## Checks

- **Rendered prompts:** `run.template.js` differs from 09b476d only in a comment (since bea034a). I rendered every
  call through the test module's `run_config`/`execute_template` with `GOLDEN_HOST`, at 09b476d and at the working
  tree. That covered the fixture and shared manifests, each with `cause_in_prompt` absent, true and false, with every
  call compared as sorted JSON. Result: **60 calls, 0 differ.** The `fix:alpha-low` prompt sha256 prefixes are
  `5e66cf5f4d0c141c` (fixture) and `54a0353d503c950d` (shared), the `FIX_PROMPT_GOLDEN` values (verified).
- **Full kit suite:** `python -W error::SyntaxWarning tools/test_calibration_kit.py` with
  `MSYS=winsymlinks:nativestrict`: 135 tests OK, 0 skipped (was 132; three new) (verified).
- **Evidence check:** `check_calibration_evidence.py`: 3 folders, 0 failures, 14 limitations, as before (verified).
- **Secrets:** `check_secrets.py` clean (0 hits). `check_credential_hygiene.py` clean, with 0 new findings (verified).
- **Hygiene:**
  - every changed file is LF (`git ls-files --eol`);
  - `bash -n` passes on the script;
  - the diff adds no absolute host path, session or run id, or model name (verified).
- **Pre-commit gate:** it runs on the commit itself, so its outcome is in the returned gist, not here.

**Untested or expected:**

- Hosts other than this Windows 11 / Git Bash one. On Linux and macOS, the shell rules (options, NAME exists, parent
  inside TARGET and outside `.git`) are the same. The native layer does not run there, and the removal is `rm -rf`,
  which follows no symlink on those systems (expected, untested).
- A `.lnk` shortcut or `sys` link deeper than DIR's top stays the host's duty, as the header says (expected).

## What I got wrong and fixed

- **My first `w -> .git` case was refused by the shell, not natively.** Git Bash's `-ef` (a `stat`) does see through
  a GUID symlink, even though `-L` and `pwd -P` do not. **Fix:** `w` points at `.git/refs`. The shell's walk from
  there does not meet `.git` itself, so only the native `K` check refuses it. The test asserts which layer refuses.
- **I expected writing the symlink blob with `/` to keep `git status` clean.** It did not: Git for Windows strips the
  `\\?\` prefix when it reads a GUID target back. **Fix:** the control filters exactly ` M v` and ` M w`, with a
  comment.
- **My scratch `rm -rf` deleted a directory through a GUID link** (my own scratch files, nothing else). That is how I
  found the removal hazard. The native removal and mutants D1 and D3 came out of it.
- **I first handed the native layer two parents per link**, the one the shell resolved and NAME's spelled parent. The
  second was redundant: a spelled parent that native programs resolve differently from the shell is either a link the
  shell already followed, or a GUID link that the first item resolves anyway. No mutant could tell it apart, so I
  removed it.
- **Some edits with backslashes failed through Python heredocs** (the shell collapsed them). **Fix:** those edits were
  made with the file tools.
- **My mutation driver's first pass could not apply 7 old hunks**, because their context now holds my new lines.
  **Fix:** an exact replacement of each hunk's removed lines, applied only when the removed block is unique. All 7 are
  red as before.
- **JR came back green**, and I did not expect that. The cause was the new `E` check overlapping the junction case.
  **Fix:** a junction Git Bash cannot see. The test now pins the reparse-point clause on its own.
