# sr-pack-4a, lead integration round 5: the rebase on the kit's integrations 2-8, IC4-1, IC4-2 and IC4-3

Branch `build/sr-pack-4a`, rebased onto `build/sr-kit-cases` at 3ed05d4 (the kit's lead integrations 2-8, check 8
ACCEPT). Then one commit for this round. Its sha is in the structured return, and this file is part of it. Every run had
TEMP and TMP on the gittoken `.tmp-gate` folder. The MoonAliza clone was only read, and its recorded state is the same
before and after (step 5).

## Step 1: the rebase

`git rebase build/sr-kit-cases` replayed the unit's eleven commits onto 3ed05d4. The only conflicts were in
`CHANGELOG.md`, in five commits (3981310, fe0a8e6, a70c639, f6f0e2d, 1f64138). Each one sat on the kit's line "Calibration
kit: run 4 case keys", which integrations 2-8 rewrote, next to the pack's line. Each was resolved with the kit
branch's line as 3ed05d4 has it, plus the commit's own pack line. A script asserted three things before it wrote each
resolution: the commit's side of the kit line equalled 09b476d's, so the unit commit had not changed it; our side
equalled 3ed05d4's; and nothing else was in the hunk. `tools/test_calibration_kit.py` and
`tools/calibration/subject-pack/README.md` merged without a conflict.

`git range-diff 09b476d..bd6506e 3ed05d4..HEAD` marks six commits `=` (patch unchanged). It marks the five above `!`,
and in each the only difference is the context line of the kit's CHANGELOG entry. So the rebase changes the meaning of
no unit commit. The rebase picks did not run the pre-commit hook. This round's commit runs the gate on the whole result.

| old | new | commit |
|---|---|---|
| 3981310 | 27ffd53 | feat: host subject pack moonaliza-x2-1 |
| 10bfbd2 | 95bb84b | docs: review 1 |
| fe0a8e6 | d8d9934 | fix: review 1 findings F1, F3, F7, F8 |
| ffe6454 | 25f172c | docs: re-review 1 |
| a70c639 | a40272a | fix: re-review 1 findings R1, R2, R4 |
| 3cba2f0 | 386e7ba | fix: lead integration D-F2, D-R3, D-RR2-1 |
| 4795b53 | 297a2de | docs: integration check |
| f6f0e2d | 71150f2 | fix: lead integration 3 |
| 20990ce | 2a12df8 | docs: integration check 3 |
| 1f64138 | ffa8b45 | fix: lead integration 4 |
| bd6506e | 0c04415 | docs: integration check 4 |

**What the rebase broke.** The rebase changed no unit commit's meaning, but the kit's tighter `--link` guard now refuses
round 4's harness. `x21_shell_modules` built a folder whose entries were symlinks to the clone's `node_modules`
entries. The guard checks each top-level symlink where it resolves, and that is inside the clone's git repository.
Red, verified: the rebased, unchanged test module (`git archive HEAD tools`), run with the clone,
`test_the_accepted_journey_test_is_red_at_base_and_green_at_accepted`, fails in `at()` with exit 2: "refused: --link
node_modules: .../modules/node_modules/@asamuzakjp, a symlink in ... resolving to <clone>/node_modules/@asamuzakjp, is
inside the git repository <clone>" (63 s). Every clone test that makes a checkout failed the same way, so step 2 had to
replace the harness's install anyway.

## Step 2: IC4-1, no install in a MoonAliza clone or checkout

### What the README and the manifest now say

- README build step 2 says to install with `npm ci` (Node 24) in a directory of its own that holds only MoonAliza's
  `package.json` and `package-lock.json` from `base0`. It gives the `git -C <pack dir>/repo show <base0 id>:...`
  commands for both files. The directory goes outside the pack, outside every checkout and outside every git
  repository's work tree. The step says why: through `node_modules/..` a checkout reaches the directory around the
  install (Git Bash's tools on Windows, and every tool on a POSIX host, resolve `..` through the link). It says "Never
  link the install of a MoonAliza clone or checkout", and names what would leak: the `docs/orchestration/` records and
  the history that holds the accepted commit. It says the guard cannot see a plain copy or an export of MoonAliza's
  files, so keeping those away is the host's part. The F5 text (`--no-cache`, `--configLoader runner`) stays, and so
  one install serves every cell. "A read-only install, such as a MoonAliza clone's, can then be linked as it is" is
  gone. So is the old "`npm ci` in a MoonAliza checkout of `16f637f`".
- The harness is stated as harness-only, in its own sentence that starts "Harness only, never a candidate's setup"
  (below).
- Step 3's link reads `--link node_modules=<install dir>/node_modules`, and the checkout goes "outside the pack and
  outside every git repository".
- The manifest's `isolation` now reads "with node_modules linked from an npm ci install in a directory of its own
  holding only base0's package.json and package-lock.json, outside the pack and outside every git repository's work
  tree (never the install of a MoonAliza clone or checkout: through node_modules/.. a candidate would reach its
  docs/orchestration/ records and its history)".
- The pack's CHANGELOG line says the same in one clause.
- `source_hashes` README.md: `00f72443…` -> `d84db55b…` (checked with `sha256sum`). The other four hashes are unchanged.

### A deviation from the brief, and a kit finding for the lead (KR5-1, S4)

The brief allowed a second install site: "a history-less checkout of base0 made with historyless-checkout.sh outside
the pack and outside any git repository's work tree". The kit README offers the same example (step 3: "such as a
history-less checkout of the case base made outside the pack", and again in "What the guard covers"). **The kit's
`--link` refuses it.** `historyless-checkout.sh` gives the checkout a `.git`, and the guard refuses any directory
inside a git repository. Verified on a scratch build: a history-less checkout of `base0` (`hl-base`, "one commit, the
tree of 4eaf584a…", 36 s), then `mkdir hl-base/node_modules`, then `--link node_modules=<abs>/hl-base/node_modules`
gives exit 2: "refused: --link node_modules: .../hl-base/node_modules is inside the git repository .../hl-base; a
dependency tree inside a repository lets the checkout reach that repository's history and files through '..' (Item
2)". No checkout was made.

So the pack README documents only the site that works. It says why a history-less checkout of `base0` is no install
site: "it has a `.git`; its tree is the candidate's own, but the guard knows a repository only by its markers". The new
clone test pins that refusal, so a kit change that accepted such a checkout would turn the test red and prompt a README
update. I did not edit the kit README (a kit file). **For the lead:** the kit README recommends an install site that its
own guard refuses. The guard fails closed, so this is S4 (a host following the README gets a refusal, not a leak). The
fix belongs in the kit: either drop the example, or say "copy its `package.json` and lockfile into a directory of
their own".

### The documented way, validated end to end (scratch, `.tmp-gate/r5`)

- I wrote `base0`'s `package.json` and `package-lock.json` (from the clone's 16f637f, the same blobs) into an empty
  directory and ran `npm ci --no-audit --no-fund` there (Node 24.20.0, npm 11.19.0). Result: "added 477 packages in
  1m", exit 0 (00:43:53Z-00:45:15Z). Verified.
- Its `node_modules` and the clone's hold the same 16,875 entries with the same sizes, and neither holds a symlink or
  a junction. The lockfile is the same blob (`bb678746…`) at 16f637f, 01a8604 and the clone's HEAD. Verified.
- Next, a history-less checkout of `accepted0` and one of `base0`, each with `--link node_modules=<install>/node_modules`
  (`MSYS=winsymlinks:nativestrict`). In both, `ls -a node_modules/..` shows `. .. node_modules package-lock.json
  package.json`: no `.git`, no `docs/orchestration/`. The manifest's test command on the journey test passes 18 of 18
  at `accepted0` and fails 12 of 18 at `base0` (the journey test placed in the checkout). No `node_modules/.vite*`
  was written into the install. Verified.

### The harness (`tools/test_calibration_kit.py`)

- `x21_shell_modules` is gone. The new `x21_install(clone, repo, target, env)` makes the README's directory: it holds
  `package.json` and `package-lock.json` read with `git show base0:` from the pack repository, plus a `node_modules`.
  Harness only: it copies the clone's installed `node_modules` (top-level `.vite` and `.vite-temp` left out) instead of
  running `npm ci`, which would need the network. The copy is equivalent because the lockfile and the file list are the
  same (above). It then asserts that the copy holds no symlink and no junction, so nothing in the install leads back to
  the clone. It takes about 35 s (298 MB). The docstring and the README say it is harness-only.
- `setUpClass` builds the install once, under the class's temporary directory, outside every repository. The F5 test
  builds a fresh one and records every entry of it (`x21_tree`), not only the top-level links as before.
- The new `x21_reaches_no_records(checkout)` resolves `checkout/node_modules` as native programs do. It lists any `.git`
  or `docs/orchestration` in the directory around it and in each of that directory's parents. `at()` now asserts the
  list is empty for every checkout the class makes. Guard, verified: on scratch checkouts whose install directory holds
  `docs/orchestration/` or `.git`, it returns that path. With neither, it returns `[]`.
- New test `test_no_checkout_links_an_install_in_a_moonaliza_clone_or_checkout`:
  - It checks that the clone holds `docs/orchestration/` and `.git`.
  - `--link` must refuse three routes, each with exit 2, "is inside the git repository", and no target made: the
    clone's own `node_modules`, a folder holding one symlink to a clone entry (round 4's harness), and a history-less
    checkout of `base0` with a `node_modules` in it.
  - A checkout of the README's install must then have `node_modules/..` hold exactly `node_modules`,
    `package-lock.json` and `package.json`, and reach no records.
  - The test is in the UNSUPPORTED list of the no-clone test.
- README test: step 2 must hold seven phrases. They include "`npm ci` (Node 24)", "holds only MoonAliza's
  `package.json` and `package-lock.json` from `base0`", "outside every git repository's work tree", "Never link the
  install of a MoonAliza clone or checkout", "a history-less checkout of `base0` is no install site" and "Harness only,
  never a candidate's setup". The build section must not hold "linked as it is", "a MoonAliza checkout of `16f637f`" or
  "symlinks to the clone's". Before the harness note, step 2 may name a clone only in the sentence that forbids its
  install. The manifest test pins the three new `isolation` phrases.

Red and guard proofs (no clone needed, scratch copies of `tools/`):

| proof | result |
|---|---|
| the new README and manifest tests against round 4's README and manifest (`git show HEAD:`) | both RED: "'`npm ci` (Node 24)' not found ...", "'npm ci install in a directory of its own ...' not found" |
| README with " A read-only install can then be linked as it is." added to step 2 | RED: "'linked as it is' unexpectedly found" |
| README with " The node_modules of a MoonAliza clone also works." added before the harness note | RED: "'clone' unexpectedly found" |
| final README and manifest | green (no-clone run of the class: 18 tests, 10 skipped as UNSUPPORTED) |

## Step 3: IC4-2, the non-vacuity check needs the content scan

`test_base0_names_neither_the_finding_nor_its_fix_nor_its_cause` now pins the whole list of the clone scan's hits
(`X21_CLONE_HINT_PATHS`, six paths under `docs/orchestration/`). It also asserts that the hits no path name explains
are exactly `2026-10-13-github-sign-in/RUN.md`, `2026-10-13-github-sign-in/reports/calibration-2-extra-findings.md`
and `smartrouter/trace/ledger.jsonl`. Only the content scan can find those three.

- Guard GX9, verified: in a scratch copy, `x21_hint_hits` reads path names only
  (`if any(h in path.lower() for h in X21_HINTS)`). Run with the clone, the test goes RED: "Lists differ:
  [...briefs/fix-x2-1.md, ...] != [...RUN.md, ...]" (148 s). Under round 4's check (one by-name hit required) this
  mutation stayed green, as check 4 computed.
- Green with the real scan: the full class run below.

## Step 4: IC4-3, LIMIT-1 named

LIMIT-1 means round 3's disclosed limit: `sr-pack-4a-integration-3.md`, Decision 2, "Limit (disclosed here): the phrase
check is textual. A paraphrase of the cause in the summary or instructions ... would pass it". The id is cited in only
two places in the worktree (`git grep`). Each now carries a note marked "added in round 5" that names the limit:
`sr-pack-4a-integration-4.md` (its "LIMIT-1" section) and `sr-pack-4a-integration-check-4.md` (the IC4-3 row and item 3
of "For the lead"). Their original text is kept. No committed pack or test file uses the id. The README and `isolation`
state the limit in words: "That check is textual", "a paraphrase is not caught".

## Step 5: the full validation

| check | result |
|---|---|
| `MOONALIZA_CLONE=<clone> python -W error::SyntaxWarning -m unittest -v tools.test_calibration_kit.HostPackX21`, 01:02-01:50Z, on the final pack and test files | **18 tests OK** in 2914.1 s, exit 0, `tearDownClass` included (the clone and the class's install unchanged). Each checkout passed the `x21_reaches_no_records` assertion; make-repo built `4eaf584a` / `ebe2f45a`; every WRONG-FIXES row grades FAIL; the accepted and both alternative fixes grade PASS; F5 and the launch refusals hold. Verified |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` (no clone, as the gate runs it) | 158 tests OK, 11 skipped (the clone tests, UNSUPPORTED: round 4's 10 plus the new one), 1312.5 s, exit 0. Verified |
| `python -m unittest tools/test_check_calibration_evidence.py` | 51 OK (181.0 s). Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| `python tools/qualification_table.py --check`; `python tools/check_secrets.py` | exit 0; clean (0 hits). Verified |
| this round's commit through the pre-commit hook (regression gate) | verified by the commit landing (sha in the structured return) |

**The clone.** I recorded it with the class's own `x21_clone_state` at 00:43:28Z, before this round's first clone read
(after the rebase). I recorded it again at 01:51:27Z, after the last clone run. Both records: `git --no-optional-locks
status --porcelain --ignored` = `!! node_modules/` and `!! research/raw/.diagnostics.jsonl`; `node_modules/.vite*`
none; 19,137 entries, the same mtime and size for each (sha256 of the sorted record `0f13a7ee…` both times). Between
them ran the scratch make-repo, the `npm ci` file comparison, the copy timing, the refusal probes, the red-first runs
(redA, GX9) and the full class run. Verified.

Every pack file, the test module and this report are LF, with no CR byte. The pack holds no absolute host path, session
id or run id (the class's hygiene test). This round changes no kit file. Before the commit, `git diff --name-only HEAD`
named only `CHANGELOG.md`, the pack's README and manifest, the test module and the two round-4 reports, and this report
was untracked. Against 3ed05d4, the only file the branch changes outside the pack, the test module, CHANGELOG and the
reports is `tools/calibration/subject-pack/README.md`. That change is the unit's one paragraph from 3981310, which the
brief allows, and this round did not touch it.

## What I got wrong and fixed

- My first README draft for step 2 said "a clone's history" in the sentence after the one that forbids the install. My
  own new README check, that no clone is named before the harness note except to forbid its install, would have failed
  on it. I reworded it to "the history that holds the accepted commit" before any run. All proofs above ran on the
  final wording.
- My first plan followed the brief's two install sites. The probe showed that the guard refuses the first (a
  history-less checkout of `base0`). So the README keeps only the second and says why, and the refusal is reported to
  the lead as KR5-1, not written around.
- I first meant to keep the harness's per-entry links "for speed". The rebased kit refuses them (redA), so the harness
  now copies the clone's install into a directory of the README's shape, with no link back.
