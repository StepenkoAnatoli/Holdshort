# sr-pack-4a, integration check 5: refute-first check of lead integration round 5 (IC4-1, IC4-2, IC4-3)

Verdict: **ACCEPT**. No S1, S2 or S3 found; three S4s are open (IC5-1, IC5-2, IC5-3). I checked `build/sr-pack-4a` at
d1ea270 against the round-5 report (`sr-pack-4a-integration-5.md`), integration checks 3 and 4
(`sr-pack-4a-integration-check-3.md`, `-4.md`), the brief and the conventions. I worked in a fresh context, wrote none
of the change and assumed it was broken. This report is the only file this round adds. Every run had TEMP and TMP on the
gittoken `.tmp-gate` folder. I only read the MoonAliza clone, and its recorded state is the same before and after my
runs (below).

I tried to reach the cause, the accepted fix, MoonAliza's history and the pack from a checkout made by following the
README word for word. I could not. The kit guard refuses the old clone-link recipe in every spelling I tried,
a junction and a symlinked parent included. Six new eslint-clean correct fixes grade PASS through `grade.sh`. Every
WRONG-FIXES row grades FAIL at its stated count. The rest still holds: the base tree holds no hint, the prompt holds no
cause, the ids are deterministic, and the rebase kept both sides.

## Findings

| id | severity | finding |
|---|---|---|
| IC5-1 | S4 | **The README test catches a clone install but not a checkout or export install.** `test_the_readme_lists_the_files_and_the_names_the_test_assumes` forbids "clone" before the harness note and the exact old phrase "a MoonAliza checkout of `16f637f`". In a scratch copy, adding "An install made in a MoonAliza checkout of `01a8604` can be linked too." before the harness note stays **green**. So does "A MoonAliza export with its records can hold the install." Adding "The node_modules of a MoonAliza clone also works." goes red, and so does dropping "Never link ...". The kit guard refuses a checkout anyway, because a checkout is a git repository. An export is not one, and the README already says keeping exports away is the host's part. So a README regression of this kind would fail closed or is disclosed, which makes this S4. Check 4's optional suggestion was "names no clone or MoonAliza checkout as the install". Round 5 covers only the clone half and does not claim more. **Fix (optional):** forbid "MoonAliza checkout" and "export" in step 2 before the harness note too, except in the sentences that forbid them. |
| IC5-2 | S4 (kit) | **KR5-1 confirmed: the kit README recommends an install site its own guard refuses.** `tools/calibration/README.md` line 56-57 says "run the install in a directory that is no repository, such as a history-less checkout of the case base made outside the pack", and line 112 says it again. I made a history-less checkout of `base0` the README's way and added `deps/node_modules` in it. `--link node_modules=<checkout>/deps/node_modules` gives exit 2 with "is inside the git repository <checkout>", and no target is made. The guard fails closed. This is a kit file, so the unit rightly left it alone. Under the owner's rule the kit README should be fixed (drop the example, or say "copy its `package.json` and lockfile into a directory of their own"). That is the lead's call on `build/sr-kit-cases`. |
| IC5-3 | S4 | **The round-5 report's skip count is described a little loosely.** It says the no-clone suite skipped 11 tests, "the clone tests, UNSUPPORTED: round 4's 10 plus the new one". My run also shows 11 skipped. But 10 are `HostPackX21` UNSUPPORTED skips, and the 11th is `Scripts.test_historyless_checkout_links_only_on_request_and_hides_the_links`, which skips because Git Bash without `MSYS=winsymlinks` copies instead of linking. That test is a kit test, not a clone test. The numbers are right and nothing is hidden. Only the description is off. |

Checked and not findings:

- **Paths that climb out lexically.** From a checkout, `node_modules/../..` reaches the directory around the install,
  which may hold the pack if the host puts the two side by side, as the class and my scratch build do. Lexically that
  path is `..`, outside the checkout, as plain `../` is. The candidate rule ("Do not read or modify anything outside
  your checkout") covers both. IC4-1 was different: `node_modules/../docs/orchestration` reads as a path inside the
  checkout. With the README's install, every path that reads as inside the checkout resolves to the install directory.
  That directory holds only `node_modules`, `package.json` and `package-lock.json`, and the two files are the same as
  the checkout's.
- **npm 11.19.0 skips esbuild's postinstall** ("install scripts not yet covered by allowScripts"). The README's plain
  `npm ci` still gives a working install. My `npm ci` tree and the clone's `node_modules` (without `.vite*`) hold the
  same 14,988 files with the same sizes, and no link. Every grade below ran on my `npm ci` install, not on a copy.
- **Round 5 edited two earlier reports.** It added a note to `sr-pack-4a-integration-4.md` and to the IC4-3 row of
  check 4. The notes are marked "added in round 5", and the original text is kept. The definition matches the lead's
  RUN.md entry of 2026-10-25 ("round 3's disclosed limit: the cause check is textual, so a paraphrase gets past it")
  and `sr-pack-4a-integration-3.md` Decision 2.

## Is the branch build/sr-kit-cases plus the unit's commits, with no kit file changed?

- `git merge-base HEAD build/sr-kit-cases` = 3ed05d4 = the tip of `build/sr-kit-cases`. `3ed05d4..HEAD` is 12 commits:
  the eleven rebased ones and d1ea270. Verified.
- `git range-diff 09b476d..bd6506e 3ed05d4..0c04415`: six `=` and five `!` (27ffd53, d8d9934, a40272a, 71150f2,
  ffa8b45). Verified.
- Both sides kept, checked by content, not only by range-diff:
  - The `+`/`-` lines of `git diff 09b476d bd6506e` equal those of `git diff 3ed05d4 0c04415` (sha1 compared), for
    `tools/test_calibration_kit.py`, for `tools/calibration/subject-pack/README.md`, and for the pack plus the
    reports.
  - In `CHANGELOG.md` the changed lines are identical. 3ed05d4's rewritten kit line is kept above the pack's line.
  - `git diff 09b476d 3ed05d4 --stat` equals `git diff bd6506e 0c04415 --stat` (20 files, +5306 -43). So the
    rebase's net effect on the old tip is exactly the kit's change.
  - Verified.
- `git diff --name-only 3ed05d4 HEAD`: `CHANGELOG.md`, the kit format README's one host-pack paragraph (unchanged since
  3981310), the pack directory, `tools/test_calibration_kit.py` and the reports. No `run.template.js`, `grade.sh`,
  `historyless-checkout.sh`, `observations.py`, `request.py`, `protocol.template.json`, prompt, `shared/` or kit README.
  Round 5 itself (`0c04415..HEAD`) touches `CHANGELOG.md` (the pack line), the pack README and manifest, the test
  module and three reports. Verified.
- The five `source_hashes` equal sha256 of the committed files. Every pack file, the test module and the round-5
  report are LF with no CR byte. A grep for host paths, `local_`/`wf_` ids finds none in them. Verified.

## A checkout made by following the README word for word

All under `.tmp-gate/ck5`, which no git repository holds (`git rev-parse` fails there and in every parent).

1. Step 1: I copied the pack directory and ran `bash make-repo.sh <clone> <pack>/repo`. It printed base0 `4eaf584a…`
   and accepted0 `ebe2f45a…`, and "the ids equal manifest.json's" (69 s). Verified.
2. Step 2: an empty `install/` holding `git -C <pack>/repo show <base0>:package.json` and `package-lock.json`. Then
   `npm ci` with Node 24.20.0 and npm 11.19.0 took 3m39s and exited 0. `ls -a install` showed `node_modules
   package-lock.json package.json`, and no symlink was inside it. Verified.
3. Step 3: `historyless-checkout.sh --pack <pack> --link node_modules=<install>/node_modules <pack>/repo <base0>
   <checkout> cand-base` with `MSYS=winsymlinks:nativestrict` gave "one commit, the tree of 4eaf584a…" (43 s).
   `dir /AL` shows a real `<SYMLINKD>`. Verified.

What the checkout reaches:

| probe | result |
|---|---|
| `ls -a node_modules/..` (Git Bash, resolves through the link) | `. .. node_modules package-lock.json package.json` |
| Node `fs.realpathSync('node_modules')`, Python `os.path.realpath` and a listing of its parent | the install directory: the same three entries |
| `git log --all`, `git count-objects -v`, `git reflog` | one commit (`4e10cb0`, "calibration base: a tree with no history"), 1,246 loose objects, no pack, no other ref |
| `.git/config`, `.git/objects/info/alternates`, `.git/logs` | no remote, no alternates, no host path |
| `x21_reaches_no_records(<checkout>)` | `[]` |
| `docs/orchestration` in the checkout | absent (1,278 files) |

**The kit guard against the old recipe.** I asked `--link node_modules=...` for six routes into the clone:

- the clone's `node_modules`;
- the same with a trailing `/`;
- the same with `/.`;
- its Windows spelling (`C:\...`);
- a directory junction (`mklink /J`) whose target is the clone's `node_modules`;
- the clone reached through a symlinked parent (`<scratch>/clone -> <clone>`, then `.../clone/node_modules`).

Each one gave exit 2 with "refused: --link node_modules: <clone>/node_modules is inside the git repository <clone>",
and no target was made. (I removed the junction with `rmdir`, which removes only the link, and the symlink with `rm`.
The clone record below covers this.) Verified.

## The fix prompt and the base tree

- Rendered through the kit's `run.template.js` with the committed manifest: one call, `fix:alpha-low`, no `Cause:`.
  None of these appear: `subject-pack`, `moonaliza-x2-1`, `WRONG-FIXES`, `zz_accepted`, `make-repo`, `manifest`,
  `pack`, `readme`, `ground truth`, `accepted`, `unreadAtOpen`, `keepStaged`, `keep_staged`, `fix-x2-1`,
  `docs/orchestration`, any of the four commit ids, `references()`, `returns []`, `no references`, or any of the six
  `X21_CAUSE_PHRASES` (whitespace collapsed, case folded). I read the prompt by hand. No clause names the empty
  reference set or the reconcile's deletion as the reason. The required behaviour's "an unreferenced staged entry is
  deleted by the next start that reads the file" and "leaves the new pair in the vault as the crash left it" are the
  journey, as check 3 accepted. Verified.
- I re-ran the cause guards in a scratch copy (manifest mutated, the prompt test alone):

  | mutation | result |
  |---|---|
  | control | green |
  | `cause_in_prompt` removed | red |
  | a cause phrase in the instructions | red |
  | a cause phrase in the required behaviour | red |
  | "See WRONG-FIXES.md." in the instructions | red |
  | a paraphrase ("the store knows no refs at that start, so the sweep drops staged pairs") | **green**: LIMIT-1, disclosed in the README and in `isolation` |

- The `base0` checkout, scanned two ways:
  - Every tracked file was read with `X21_HINTS` (`x2-1`, `x2_1`, `unreadatopen`, `keepstaged` and the six cause
    phrases, whitespace collapsed, case folded), checking each path name and each file's content. Hits: `[]`.
  - A wider `git grep -i -E "x2[-_ ]?1|fix-x2|unread.?at.?open|keep.?staged|calibration-2|extra-findings"` finds only
    `%x21`/`\x21` character classes, `gpt-image-2-...` strings and the base test title at
    `tests/github-account-store.test.ts:795`, which check 4 already cleared.
  - Verified.

## Correct fixes and wrong fixes

Driver `.tmp-gate/ck5/shapes/drive.py`. Each shape:

- is a full candidate on a fresh README-literal checkout of `base0` (my `npm ci` install linked);
- is made with the class's `x21_candidate`, so it has its own red-first test and is committed;
- is graded by the kit's `grade.sh <pack>/manifest.json fix`, one at a time.

So a PASS here means candidate green, guard red, journey test green, scope ok and eslint clean. None of these shapes
was tried by the earlier checks.

| shape | PASS | acceptedPin | lint |
|---|---|---|---|
| A: a string mode parameter `reconcile(refs, mode: 'all' \| 'spare-staged' = 'all')`, chosen by a ternary in `index.ts` | true | 18 of 18 | ok |
| B: a second vault method `reconcileSparingStaged` sharing a private `sweep(refs, spare)` that skips with `continue`, and `await (flag ? vault.reconcileSparingStaged(R) : vault.reconcile(R))` | true | 18 of 18 | ok |
| C: the store's flag made a public field (`unread = false`), read as `githubStore.unread` | true | 18 of 18 | ok |
| E: `const reconcileOptions: { keepStaged: boolean } = Object.freeze({...})` in a statement of its own between the anchors | true | 18 of 18 | ok |
| F: `export const SPARE_STAGED` from `vault.ts`, imported by `index.ts` next to `Vault`, passed by a ternary with `undefined` | true | 18 of 18 | ok |
| H: a store method `reconcileOptions()` that returns the vault's options object | true | 18 of 18 | ok |

The install held no `.vite*` after the six grades. I found no eslint-clean correct shape that grades FAIL.

In the full class run below, `test_every_wrong_fix_grades_fail_on_the_accepted_journey_test_alone` passed. It asserts
two things for each of the sixteen WRONG-FIXES rows:

- the grade is FAIL with candidate green, guard red, scope ok and lint ok;
- `acceptedPin.failed` equals the count in the row's grade column (12, 1, 1, 5, 13, 13, 12, 9, 1, 1, 12, 1, 12, 4, 1, 12).

The same run grades the accepted fix and both alternatives PASS, and keeps the 13 slice probes lint-clean and green.
Verified.

## Guard proofs (scratch copies)

| guard | mutation | result |
|---|---|---|
| round 5's README and manifest tests against round 4's files (`git show 0c04415:`) | the old README and manifest | both RED ("'`npm ci` (Node 24)' not found", "'npm ci install in a directory of its own ...' not found") |
| README test | "The node_modules of a MoonAliza clone also works." before the harness note | RED ("'clone' unexpectedly found") |
| README test | "Never link ..." reworded to "Link ..." | RED |
| README test | a checkout install / an export install named before the harness note | green (IC5-1) |
| GX9, the content scan | `x21_hint_hits` reads path names only; `test_base0_names_...` run with the clone | control green (198 s); GX9 RED: "Lists differ: [...briefs/fix-x2-1.md, ...] != [...RUN.md, ...]" (161 s). IC4-2 is closed |
| `x21_reaches_no_records` | on my README checkout, the install dir given `docs/orchestration/`, then a `.git` file, then a `.git` in its parent | returns that path each time; `[]` clean before and after |
| id determinism | `make-repo.sh` under `GIT_CONFIG_GLOBAL` with `core.autocrlf=true`, `commit.gpgsign=true`, `i18n.commitEncoding=ISO-8859-1`, another identity, `pack.threads=1`, `TZ=Asia/Tokyo` | base0 `4eaf584a…`, accepted0 `ebe2f45a…`, "the ids equal manifest.json's" |

## The MoonAliza clone

I recorded it with the class's `x21_clone_state` at 02:48:25Z, before my first clone read, and at 04:16:35Z, after my
last. Both records give:

- `git --no-optional-locks status --porcelain --ignored`: `!! node_modules/` and `!! research/raw/.diagnostics.jsonl`;
- `node_modules/.vite*`: none;
- 19,137 entries, the same mtime and size for each.

The two serialised records are byte-identical (`cmp`; sha256 `cb9d7d3b…` both times), and HEAD is `1ac226db…` both
times. Between them ran the full class, the scratch make-repo (twice, one under the hostile config), the clone-route
refusal probes (the junction included), the `node_modules` file comparison and GX9 (control and mutation). Nothing new
appeared. Verified.

## Checks

| check | result |
|---|---|
| `MOONALIZA_CLONE=<clone> python -W error::SyntaxWarning -m unittest -v tools.test_calibration_kit.HostPackX21`, 02:48-03:44Z | **18 tests OK** in 3313.7 s, exit 0, `tearDownClass` included. Verified |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` (no clone) | 158 tests OK, 11 skipped (10 UNSUPPORTED, 1 Scripts link skip; IC5-3), 2050.1 s, exit 0. Verified |
| `python -m unittest tools/test_check_calibration_evidence.py` | 51 OK (249.2 s). Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| `python tools/qualification_table.py --check`; `python tools/check_secrets.py` | exit 0; clean (0 hits). Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

## Claims of checks 3 and 4, re-checked

| claim | now |
|---|---|
| The rebase keeps both sides (check 3), and the branch is the kit's tip plus the unit's commits (3, 4) | holds on the new base 3ed05d4 (above) |
| The cause is real, matches the base code and stays out of the prompt; cause guards C1-C6 red, N1 green (3) | holds (prompt and guards above; the class's prompt test is green) |
| Every wrong fix FAILs at its count; the accepted fix and the alternatives PASS; slice probes green (3, 4) | holds (class run) |
| F5: the commands write nothing into the linked `node_modules`, and the clone is unchanged (3, 4) | holds (the class F5 test on a fresh install; my six grades left no `.vite*`; the clone record) |
| `base0` is 16f637f minus `docs/orchestration/`, with no excluded object in the pack repository (4) | holds (`test_make_repo_builds_the_manifest_ids` green) |
| The ids are deterministic under a hostile config (4) | holds (above) |
| `base0` holds no hint, and the scan is not vacuous (4) | holds, and IC4-2's gap is closed (GX9) |
| IC4-1: no route from a checkout to MoonAliza records or history | closed: README-literal checkout probed, six clone routes refused |
| IC4-3: LIMIT-1 defined | closed: matches round 3 Decision 2 and the lead's RUN.md |

## For the lead

1. IC5-2 (S4, kit): fix the kit README's install-site example on `build/sr-kit-cases` (lines 56-57 and 112).
2. IC5-1 (S4, optional): widen the README test to a checkout or export install.
3. IC5-3 (S4): no action needed; the skip count is right, and only its description is loose.

## What I got wrong and fixed

- My first prompt-guard driver extracted only `tools/` and `CHANGELOG.md`. The class's `run_config` reads
  `tests/fixtures/calibration`, so even the control errored with FileNotFoundError. I added `tests/fixtures` to the
  extract and re-ran every mutation. Only the re-runs are cited.
- My first `git grep` of the checkout used `x2[-_ ]?1`, which also matches `%x21`, `\x21` and `gpt-image-2-1…`. I kept
  it as the wider net and relied on the class's exact `X21_HINTS` scan for the verdict. That scan gives `[]`.
- I first meant to grade the shapes while the class run was going. The host has 4 cores and about 1.5 GB free, and the
  subject's tests are timeout-bound, so I ran the shapes after the class finished, to keep any red unambiguous.
