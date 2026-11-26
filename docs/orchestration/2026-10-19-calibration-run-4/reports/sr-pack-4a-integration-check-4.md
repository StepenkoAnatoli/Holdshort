# sr-pack-4a, integration check 4: refute-first check of lead integration round 4 (D-IC3-1)

Verdict: **FIX**, for one S3 (IC4-1). I checked `build/sr-pack-4a` at 1f64138 against the round-4 report
(`sr-pack-4a-integration-4.md`), integration check 3 (`sr-pack-4a-integration-check-3.md`), the brief
`run4-pack-4a-builder.md` and `conventions.md`. I worked in a fresh context and wrote none of the change. This report
is the only file this round adds. Every run had TEMP and TMP on the gittoken `.tmp-gate` folder. I only read the
MoonAliza clone, and its recorded state is the same before and after my runs (below).

Round 4's claims hold. The base tree a candidate checks out no longer carries the answer key. The pack repository
holds none of the excluded objects. The ids are deterministic. base0..accepted0 is exactly 16f637f..01a8604 outside
`docs/orchestration/`. Every guard goes red when it is removed. Nothing graded depends on the directory, and every
claim check 3 verified still holds.

But the README's dependency step leaves a second path to the same records (IC4-1). The README says the host may link
a MoonAliza clone's own install. A path spelled inside the checkout, `node_modules/../`, then reaches that clone's
`docs/orchestration/` and its history, which holds 01a8604.

## Findings

| id | severity | finding |
|---|---|---|
| IC4-1 | S3 | **The dependency link reaches the records the trees now leave out.** The README's build step 2 says to run `npm ci` "in a MoonAliza checkout of `16f637f`". It also says "A read-only install, such as a MoonAliza clone's, can then be linked as it is". Step 3 links `node_modules=<installed outside the pack>`. The kit's `--link` guard refuses only a directory that shares a path with the pack repository or the pack. A MoonAliza checkout or clone is neither, so the guard accepts it. The directory the link points into therefore sits inside a MoonAliza working tree that has `docs/orchestration/`, and for a clone also inside MoonAliza's history. **Reproduced:** I made a history-less checkout of `base0` the README's way (`historyless-checkout.sh --pack <pack> --link node_modules=<clone>/node_modules`, `MSYS=winsymlinks:nativestrict`). In that checkout, `readlink node_modules` names the clone. In Git Bash, `cat node_modules/../docs/orchestration/2026-10-13-github-sign-in/briefs/fix-x2-1.md` prints the brief ("Unit fix-x2-1: a crash before commit followed by an unreadable start ... (X2-1, S3)"). `ls node_modules/../docs/orchestration` lists the run folders, and `git -C "$(readlink node_modules)/.." log 01a8604` shows the accepted fix's commits. On this host, Node, Python and git resolve `node_modules/..` by its spelling (ENOENT, or the checkout itself). The MSYS tools resolve it through the link. On a POSIX host, every tool resolves it through the link. The candidate rules say "Do not read or modify anything outside your checkout", so a candidate that follows them does not read these records, and a plain `grep -r` or `git grep` does not follow the link. That is why this is S3 and not IC3-1's S2. Even so, it breaks the isolation statement this round rewrote ("the pack repository, its accepted commit ... stay outside every candidate's permitted paths"). It also breaks the kit's Item 2 ("no path from a checkout reaches the accepted fix"), and does so under the procedure the pack's own README documents. Conventions name the clone as the install the run uses ("has `node_modules` installed ... it serves as `MOONALIZA_CLONE`"). **Fix (the lead decides):** step 2 should require an install whose directory and parents hold no MoonAliza history and no orchestration records. One way: run `npm ci` in a history-less checkout of `base0` made outside the pack (its tree already lacks `docs/orchestration/`), or in a directory holding only `package.json` and `package-lock.json` from `base0`. Drop "such as a MoonAliza clone's ... linked as it is". Say the same in `isolation`. Optionally, add a test that the README names no clone or MoonAliza checkout as the install. The kit's own tests may keep linking the clone, because they are not candidates. |
| IC4-2 | S4 | **The new test's non-vacuity check does not prove that it scans file contents.** `test_base0_names_neither_the_finding_nor_its_fix_nor_its_cause` requires the scan of 16f637f to hit `briefs/fix-x2-1.md`, but that file matches by its path name alone. I computed the alternative: a scan that reads path names only finds `fix-x2-1.md`, `fix-x2-1-1.json` and `sr-host-fix2-1.json` in 16f637f, all under `docs/orchestration/`, and nothing in base0. So every assertion of the test still holds when the content half of `x21_hint_hits` is broken. The content scan works today. My GX8 (below) plants RUN.md's text under the hint-free name `docs/notes.md`, and the test goes red with `['docs/notes.md']`. **Fix:** also require a hit that only content can find, such as `.../2026-10-13-github-sign-in/RUN.md` or `.../reports/calibration-2-extra-findings.md`, or pin the six-path list. |
| IC4-3 | S4 | **LIMIT-1 is still undefined.** I found no item with that id in the worktree, in the run 4 orchestration folder of `sr-run4`, or in the side-session notes. Round 4 says the same and keeps its claims to what is tested. The lead should write it down or drop the reference. (Note added in round 5, `sr-pack-4a-integration-5.md`: LIMIT-1 is round 3's disclosed limit, `sr-pack-4a-integration-3.md` Decision 2: the phrase check is textual, so a paraphrase of the cause in the summary or instructions would get past it.) |

Checked and not findings:

- `tests/github-account-store.test.ts:795` (base) has the title "a file unread at open and %s at the sign-in's
  re-read". This is the subject's own test of the base behaviour. It is not the accepted fix's name (`unreadAtOpen`
  does not match, because the scan collapses whitespace but does not remove it), and it is not the cause.
- `docs/superpowers/plans/2026-10-02-research-jobs.md:605` cites a path under `docs/orchestration/2026-10-05-more-models/`.
  The citation now dangles, and it names nothing about X2-1.

## History-less checkout of base0, searched

I made the checkout with the kit's `historyless-checkout.sh --pack --link node_modules=...` from a scratch build of the
pack (`.tmp-gate/ic4/packA`). It reported "one commit, the tree of 4eaf584a…". Its repository holds 1,246 objects, all
reached by `rev-list --objects --all`, and `fsck --unreachable` reports nothing. It has 1,278 files and no
`docs/orchestration/`.

| search (git grep, whole tree unless noted) | result |
|---|---|
| `x2[-_ space U+2010-2015]1` (not preceded by `%`, `\`, a digit or a letter), `fix-x2`, `unread.?at.?open`, `keep.?staged`, `calibration-2`, `extra-findings` | one file: the base test title above |
| the same plus `double fault`, `smartrouter`, `holdshort`, `sr-host`, `spare.?staged`, `staged.?pair`, `unreadStart`, outside `research/raw` | only regex classes `\x21`, the research-jobs plan's SmartRouter notes, and the base tests' `unreadStart` / "staged pair" (subject code) |
| `github-sign-in/`, `2026-10-13`, `C-B` | dates and the spec link in ARCHITECTURE.md only, no run folder |
| `unread`, `cannot be read`, `unreadable` in `docs/` and `src/` (not `docs/research`) | the base store's own fields and comments, and unrelated specs |
| `unreferenced`, `reconcile` in `docs/` and `src/` | the base's vault and store comments, the rework plans, and reconcilers of other features |
| the 15 `.zip` fixtures (`tests/fixtures/research-kit/`), every member, for the hints and `orchestration` | nothing |
| file names | no hint word in any path |

The base code still shows how the reconcile treats staged entries: `vault.ts` 106-121, `references()` returning
`refsOf(this.live)`, and the store's `unread` field and its comments. The README and `isolation` disclose this, and a
base must show its own behaviour.

The rendered fix prompt (kit `run.template.js` under the stub harness, the committed manifest) has no `Cause:`. It
contains none of `subject-pack`, `moonaliza-x2-1`, `WRONG-FIXES`, `zz_accepted`, `make-repo`, `manifest`,
`unreadAtOpen`, `keepStaged`, `keep_staged`, `fix-x2-1`, `docs/orchestration`, any of the four commit ids,
`references()`, `returns []` or "no references". "unreferenced" appears only in the required behaviour, as check 3
already accepted. The manifest fields the prompt prints (summary, required behaviour, instructions) did not change in
this round. The diff touches only the ids, `_lineage`, `isolation` and `source_hashes`.

## Is the pack repository clean, and are the ids host-independent?

- In my scratch build, the pack repository holds 1,132 blobs, 128 trees and 2 commits. `fsck --unreachable` names
  only the two trees round 4 describes (3ec0e7bf…, be6333cd…, the accepted root and its `tests` tree from before the
  journey test). The blobs that match a hint are all files of `accepted0`: the fix's three source files, its tests, the
  map and the journey test. The pack repository is never a candidate's path.
- Three builds: two plain, and one with `GIT_CONFIG_GLOBAL` set to `core.autocrlf=true`, `commit.gpgsign=true`,
  `i18n.commitEncoding=ISO-8859-1`, another user identity and `pack.threads=1`, under `TZ=Asia/Tokyo`. All three give
  base0 `4eaf584a0b72b36e71ca8f318ad9d9b4d04e8a2e` and accepted0 `ebe2f45a683989b91bac4d1bf46ebba138597fa9`, and
  "the ids equal manifest.json's". Verified.
- `ls-tree -r base0` is byte-identical to `ls-tree -r 16f637f` minus `docs/orchestration/` (1,278 lines).
  `ls-tree -r accepted0` minus the journey test is byte-identical to 01a8604 minus the directory. `diff-tree -r
  --no-renames base0 accepted0` gives exactly 16f637f..01a8604's seven entries outside the directory (the same blob
  ids), plus `A tests/zz_accepted_x2_1.test.ts`. 16f637f..01a8604 touches nothing under `docs/orchestration/` (seven
  files in total). Verified.

## Is the branch build/sr-kit-cases plus this unit's commits, with no kit file changed?

- `git merge-base HEAD build/sr-kit-cases` = 09b476d = the tip of build/sr-kit-cases. `09b476d..HEAD` is this unit's
  ten commits, ending with 20990ce (check 3) and 1f64138 (round 4). Verified.
- `git diff --name-only 09b476d HEAD` names no `run.template.js`, `grade.sh`, kit README, `observations.py`,
  `historyless-checkout.sh`, `request.py`, `protocol.template.json`, prompt file or `shared/`. Round 4 touches
  `CHANGELOG.md` (the pack's own line), the pack's README, `make-repo.sh` and `manifest.json`,
  `tools/test_calibration_kit.py` and its report. Verified.
- Every pack file and the test module are LF, with no CR byte. The five `source_hashes` equal `sha256sum` of the
  committed files. The pack has no absolute host path, session id or run id (my grep, and the class's hygiene test).
  Verified.

## Guard proofs, re-run (scratch copies of the pack; the scratch manifest pinned to each mutation's ids)

Driver `.tmp-gate/ic4/guards/guards.py`. It checks every mutated script with `bash -n`, builds it once to learn its
ids, pins the scratch manifest to them, then runs `test_make_repo_builds_the_manifest_ids` and the new no-hint test
with `X21` pointed at the scratch copy.

| guard | mutation | ids built | result |
|---|---|---|---|
| control | none | 4eaf584a / ebe2f45a | both green |
| GX1 | no exclusion (both original trees copied whole) | c1155c1e / 61963a2a (round 4's) | ids test RED ("base0 is ... tree minus docs/orchestration/"), hint test RED ("base0 has no docs/orchestration/ path") |
| GX2 | trees filtered, and every object of both original trees copied as well | 4eaf584a / ebe2f45a | ids test RED ("an excluded object is in the pack repository"), hint test green, as expected |
| GX5 | README.md dropped from both roots as well | a944ee64 / e0e552ea (round 4's) | ids test RED (tree minus differs); make-repo's own diff check passes, as round 4 says |
| GX3 | accepted0 alone loses `docs/ARCHITECTURE.md` | none | make-repo exit 1, "base0..accepted0 is not 16f637f..01a8604 outside docs/orchestration/", target removed |
| new GX6 | only `briefs/fix-x2-1.md` left out, the rest of the directory kept | a5c92c82 / cf5aa5ac | both RED |
| new GX7 | base0 filtered, accepted0 whole | none | make-repo exit 1 (diff check), target removed |
| new GX8 | RUN.md's text planted in both trees as `docs/notes.md` (a name with no hint) | 9b668092 / e26c9e6b | ids test RED; hint test RED with `['docs/notes.md']`, so the content scan works (see IC4-2) |

Red first: the new test run against round 3's pack (`git archive 20990ce` of the pack directory) fails at "base0 has
no docs/orchestration/ path" (64 s). Verified.

## Does anything graded depend on docs/orchestration/? Shapes of a correct fix

Static checks: `vitest.config.ts` includes only `tests/**/*.test.ts(x)`. In `tests/` and `src/` the directory appears
only in two comments (`application.test.ts:621`, `provider-stream.test.ts:460`). `grade.sh` grades the candidate's
tests, the guard and the journey test. 16f637f..01a8604 touches nothing in the directory.

Driver `.tmp-gate/ic4/shapes/shape_driver.py`. It is check 3's driver with the leak probe removed and five new
shapes added. It works on a history-less checkout of the new `accepted0`, resets the three source files from
`accepted0` (or `base0`) per shape, applies the edits, runs `npx eslint` on the touched files, then runs the manifest's
test command on the committed journey test. Result: `Ran 1 test in 420.192s`, OK.

| shape | eslint | journey test |
|---|---|---|
| P1 reconcile call wrapped over five lines, prettier style | 0 | 0 of 18 failed |
| P2 block comments inside the reconcile call | 0 | 0 of 18 failed |
| P4 the reconcile over two statements | 0 | 0 of 18 failed |
| P6 store and vault only, `index.ts` as the base has it | 0 | 0 of 18 failed |
| P8 if/else with two reconcile calls | 0 | 0 of 18 failed |
| P10 CRLF `index.ts`, non-ASCII comment between the anchors | 0 | 0 of 18 failed |
| P11 local arrow helper between the anchors | 0 | 0 of 18 failed |
| **new** N1 the store's flag as a getter property under another name (`get fileUnreadAtStart()`), read by the wiring | 0 | 0 of 18 failed |
| **new** N2 a positional boolean parameter of `reconcile` under another name (`spareUnreferencedStaged = false`) | 0 | 0 of 18 failed |
| **new** N6 options built by a conditional spread | 0 | 0 of 18 failed |
| **new** N7 a promise chain: `Promise.resolve(flag).then(keep => vault.reconcile(...))` | 0 | 0 of 18 failed |
| **new** N9 an async arrow run in place between the anchors | 0 | 0 of 18 failed |

I found no eslint-clean correct shape that grades FAIL. Every WRONG-FIXES row grades FAIL at its stated count (full
run below).

## F5: the MoonAliza clone

I recorded the clone at 17:03:05Z (before my first clone run) and at 18:06:24Z (after my last), with the class's own
`x21_clone_state`. Both times, `git --no-optional-locks status --porcelain --ignored` gave `!! node_modules/` and
`!! research/raw/.diagnostics.jsonl`. `node_modules/.vite*` was empty both times. All 19,137 entries had equal mtime
and size. Between the two records ran the three builds, the checkout, the full HostPackX21 class, the guard runs
(including the probe builds), the red-first run and the shapes run. For IC4-1 I also read the clone's files and log
through the link (reads only). Verified.

## Checks

| check | result |
|---|---|
| `MOONALIZA_CLONE=<clone> python -W error::SyntaxWarning -m unittest -v tools.test_calibration_kit.HostPackX21`, 17:03-17:58Z | **17 tests OK** in 3285.6 s, exit 0, `tearDownClass` included. Verified |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` (no clone) | 133 tests OK, 10 skipped (the clone tests, reported UNSUPPORTED), 439.1 s, exit 0. Verified |
| `python -m unittest tools/test_check_calibration_evidence.py` | 51 OK (290.6 s). Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

## For the lead

1. IC4-1 (S3): rewrite build step 2 so that the install a checkout links does not sit in a MoonAliza clone or
   checkout (it holds `docs/orchestration/` and, for a clone, 01a8604). For example, `npm ci` in a history-less
   checkout of `base0` outside the pack. Drop "such as a MoonAliza clone's ... linked as it is", and say it in
   `isolation`.
2. IC4-2 (S4): make the no-hint test's non-vacuity check need a hit that only the content scan can find.
3. IC4-3 (S4): define LIMIT-1 or drop the reference (round 5: defined as round 3's disclosed limit of the phrase check).

## What I got wrong and fixed

- My first guard driver copied the pack from `X21` after the previous mutation had repointed it, so GX2 started from
  GX1's script and its anchor was missing (the driver refused; nothing was graded). The driver now copies from the
  original pack every time. I re-ran GX2 and the rest, and only the re-runs are cited.
- GX5's anchor was written with a Python `\t` escape, so it never matched (the driver refused). I rebuilt it with
  `chr(92)` and re-ran it.
- GX3 and GX6 first used `update-index --force-remove`, which needs a work tree in the bare pack repository. Both
  refused for that reason, not for the guard. I switched to `update-index --index-info` with a mode-0 entry and re-ran
  both. Only those re-runs are cited.
- My first `grep -c $'\r'` count of CR bytes counted every line, because the quoting was lost in a loop. A Python byte
  count shows zero CR bytes in every file.
