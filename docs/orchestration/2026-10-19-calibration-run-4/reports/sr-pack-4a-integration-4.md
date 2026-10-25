# sr-pack-4a, lead integration round 4: MoonAliza's orchestration records left out of both trees

Branch `build/sr-pack-4a` at 20990ce (on `build/sr-kit-cases` 09b476d, draft PR #120), then one commit for this round.
Its sha is in the structured return, and this file is part of it. Every run had TEMP and TMP on the gittoken
`.tmp-gate` folder. The MoonAliza clone was only read (cat-file, ls-tree, grep <rev>, pack-objects --stdout).

## D-IC3-1, as given

Lead decision D-IC3-1 (2026-10-25): the brief's H3 intent ("the candidate never sees it") outranks its literal wording
("export the base tree 16f637f"). The lead verified the leak. In 16f637f's 1,481-file tree, every file that names
X2-1, unreadAtOpen or keepStaged is under `docs/orchestration/`:

- `2026-10-13-github-sign-in/RUN.md`
- `briefs/fix-x2-1.md`
- `reports/calibration-2-extra-findings.md`
- `smartrouter/trace/decisions/fix-x2-1-1.json`
- `smartrouter/trace/ledger.jsonl`

The decision's steps were: (1) export both trees without `docs/orchestration/`, deterministically, copying only the
objects they reach, and assert that base0..accepted0 (minus the journey test) equals 16f637f..01a8604 outside it;
(2) hunt for any hint outside it, and stop if one is found; (3) check that nothing graded depends on it; (4) re-pin the
ids and hashes, replace the tree-equality assertion, add a no-hint test (red, green, guard removal), and state the
exclusion with no claim stronger than the tests; (5) re-run the full validation, with the clone unchanged.

## Step 1: what changed in make-repo.sh

- `copy()` (which copied the two original trees whole) is replaced by `filter TREE`, which runs once per tree:
  - it refuses a tree that has no `docs/orchestration/` tree (exit 1);
  - it lists `ls-tree -r -t -z TREE` and drops the `docs` tree entry itself, `docs/orchestration`, everything under it,
    and any gitlink;
  - it pipes the remaining object ids through `pack-objects --stdout` in the clone into `unpack-objects` in the pack
    repository. The clone is only read, and no alternates are used: writing an object that already exists in an
    alternate can freshen the clone's object files, which F5 forbids;
  - it writes the `docs` tree without its `orchestration` entry, then the root tree with that `docs` tree, using
    `git mktree -z` from the clone's own entries.
  The ids stay host-independent. Every tree except the two roots and the two `docs` trees is MoonAliza's own tree
  object, and those four are content-addressed `mktree` output. The function runs in a command substitution, where
  bash does not inherit errexit, so each pipeline ends in `|| fail` (pipefail is inherited).
- accepted0 is built by adding the journey test to the filtered accepted tree. The commit messages now say "without
  docs/orchestration/".
- New diff check, after both commits: the hash of `diff-tree -r -z --no-renames 16f637f^{tree} 01a8604^{tree} -- .
  ':(exclude)docs/orchestration'` (computed in the clone) must equal the hash of `diff-tree base0 accepted0 -- .
  ':(exclude)tests/zz_accepted_x2_1.test.ts'` (computed in the pack repository), and the diff must not be empty.
  Otherwise the script exits 1 and removes TARGET. On success it prints "make-repo: base0..accepted0 is
  16f637f..01a8604 outside docs/orchestration/".
- The header comment states the exclusion, why the whole directory goes, and the new exit-1 cases.

Built ids: base0 `4eaf584a0b72b36e71ca8f318ad9d9b4d04e8a2e` (was 09fe935e), accepted0
`ebe2f45a683989b91bac4d1bf46ebba138597fa9` (was 8ddd4f4b). base0 holds 1,278 files (1,481 minus the 203 under
`docs/orchestration/`). Two separate builds gave the same ids, in about 54 s each.

The pack repository also keeps two unreachable trees: the filtered accepted root and its `tests` tree from before the
journey test was added. Both hold only subject code that the filtered trees reach, which the object test below allows.
(The old design also left ACCEPTED_TREE unreachable.)

## Step 2: the hint hunt outside docs/orchestration/ (no finding)

All of this ran in the clone at 16f637f, read only.

- `git grep -i -E 'x2-1|x2_1|fix-x2|unreadAtOpen|keepStaged' 16f637f`, excluding `docs/orchestration/`: nothing.
- Each of the six `X21_CAUSE_PHRASES`, case-insensitive: nothing outside `docs/orchestration/`.
- Path names: only `.gitkeep` files match "keep". None of the hint words appears in a path.
- Paraphrase searches (unread, unreferenced, staged near reconcile or delete, "cannot read", "double fault", "known
  limit"): the only hits are the base's own subject code, spec and tests describing the base's behaviour, as a base
  must. These are `src/main/github-account-store.ts` (the open and reconcile comments), the spec's 4.5 table, and the
  tests' `unreadStart`. None names the fix, its flag or its cause.
- `HANDOFF`, the development-status notes, `AGENTS.md`, `README.md` and `docs/ARCHITECTURE.md`: nothing.
- A whitespace-normalised, case-insensitive scan of every blob and path of 16f637f (the test's helper) found 6 hits,
  all under `docs/orchestration/`. They are the lead's five, plus `smartrouter/trace/decisions/sr-host-fix2-1.json`
  (also inside the excluded directory).
- `smartrouter/trace/calibration-2/lead-notes.md` describes the C-B mechanism without the id. That is a paraphrase
  inside `docs/orchestration/`, and it shows why the whole directory goes, not a list of files.

## Step 3: nothing graded depends on docs/orchestration/

- Static checks:
  - In `tests/`, only comments mention the directory (`application.test.ts:621`, `provider-stream.test.ts:460`).
  - The eslint ignores, the vitest config and the tsconfig `include` (src, tests, e2e, configs) do not reach it.
  - `handoff.test.ts` reads `docs/handoff` only and is not graded.
  - `grade.sh` grades the test file, the candidate's new tests and the accepted journey test.
  - 16f637f..01a8604 touches 7 files, none under `docs/orchestration/`.
- At the new base0 and accepted0 (full run, below): the journey test is red at base0 and 18 of 18 green at accepted0.
  Every WRONG-FIXES row grades FAIL at its stated count. The accepted fix and both alternative correct fixes grade PASS.
  All 13 slice probes pass.
- Check 3's correct-fix shapes, rebuilt on the new pack (scratch `shapes.py`, a subclass of `HostPackX21` that applies
  each shape to a base0 checkout): all OK, `Ran 1 test in 410.558s`.

| shape | eslint | journey test |
|---|---|---|
| P1 wrapped, prettier style | exit 0 | 0 of 18 failed |
| P2 block comments inside the call | exit 0 | 0 of 18 failed |
| P4 reconcile over two statements | exit 0 | 0 of 18 failed |
| P5 strings holding comment tokens | exit 0 | 0 of 18 failed |
| P6 store and vault only, `index.ts` as the base calls it | exit 0 | 0 of 18 failed |
| P7 try-finally and await attach | exit 0 | 0 of 18 failed |
| P8 if-else | exit 0 | 0 of 18 failed |
| P10 CRLF file, non-ASCII comment between the anchors | exit 0 | 0 of 18 failed |
| P11 local arrow helper | exit 0 | 0 of 18 failed |

## Step 4: re-pin, tests, docs

- `manifest.json`:
  - `accepted_fix` (top level and in the finding) is now `ebe2f45a…`;
  - `present_at` and `cases.fix.base` are now `4eaf584a…`;
  - `_lineage` says each tree is without its `docs/orchestration/` directory;
  - `source_hashes` README.md is now `00f72443…` and make-repo.sh `08f57ccd…` (checked with `sha256sum`);
  - `isolation` now names the exclusion and why: those records name the finding, state its cause and give the accepted
    fix. It says make-repo copies no object of the directory that the two trees do not reach. It says a test checks
    that no file or path name of the base holds the finding's id, the accepted fix's two names or a phrase of the
    cause, and it states that this check is textual, so a paraphrase is not caught.
- `README.md`: build step 1 says both trees are without `docs/orchestration/` and mentions the diff check. A paragraph
  under "Why there is no pin and no review case" states the exclusion, why it covers the whole directory, that only
  the reached objects are copied, and what the tests check. It says plainly that a paraphrase elsewhere in the tree is
  not caught, and that the base's code, spec and tests describe the reconcile, as the base must.
- `CHANGELOG.md`: the pack's line names the exclusion.
- `tools/test_calibration_kit.py`:
  - new constants `X21_BASE_SRC`, `X21_ACCEPTED_SRC`, `X21_EXCLUDED`, and `X21_HINTS` (`x2-1`, `x2_1`, `unreadatopen`,
    `keepstaged` and every `X21_CAUSE_PHRASES` entry);
  - new helpers `x21_ls_tree` and `x21_hint_hits`. The second reads every blob with `cat-file --batch`, decodes it as
    UTF-8 with replacement, lowercases it, collapses whitespace, and matches the hints against each blob and each path;
  - **new** `test_base0_names_neither_the_finding_nor_its_fix_nor_its_cause`. It checks that the hints are lowercase,
    that base0 has no `docs/orchestration/` path, and that the hint scan of base0 finds nothing. As a non-vacuity
    check, the same scan of the clone's 16f637f must hit `briefs/fix-x2-1.md`, and every hit must be under
    `docs/orchestration/`. The test is added to the UNSUPPORTED list of the no-clone test;
  - `test_make_repo_builds_the_manifest_ids`: the old assertion (each tag's tree equals the clone's tree) is replaced.
    It now checks that:
    - make-repo printed the diff-check message;
    - each tag's `ls-tree -r` equals the clone's tree minus `docs/orchestration/` (accepted0 also has the journey test
      at mode 100644), and the clone has more than 100 excluded files;
    - no object of the excluded directory that the tags do not reach (its `ls-tree -r -t` objects plus the original
      root and `docs` trees, minus every object the tags reach through `ls-tree -r -t`) is in the repository
      (`cat-file --batch-all-objects`), and the `fix-x2-1.md` blob is among those objects;
    - no blob in the repository is outside what the tags reach;
  - the manifest-shape and README tests pin the new isolation text and the new README sentences.

### Red, green and the guard proofs

- **Red first**: the new test at the old make-repo.sh (old ids) failed at "base0 has no docs/orchestration/ path" with
  203 extra paths, the first being `docs/orchestration/2026-10-03-task5-research-review/MANDATE-P5.md` (61.8 s). A
  scratch scan of that old base0 (09fe935e) found 6 hint hits, all under `docs/orchestration/`.
- **Green**: the new test, `test_make_repo_builds_the_manifest_ids` and
  `test_make_repo_removes_its_target_when_the_ids_differ`: 3 OK in 195.3 s.
- **Guards**: each mutation ran on a scratch copy of the pack, with that copy's manifest pinned to the ids the mutated
  script builds, so the id check passes and only the new assertions can catch the mutation.

| guard | mutation | ids built | result |
|---|---|---|---|
| GX1 | exclusion removed: `filter` replaced by round 3's whole-tree copy, the original trees used as base0's and accepted0's | c1155c1e / 61963a2a | ids test RED (tree minus docs/orchestration/ differs: base0 holds `docs/orchestration/...`); hint test RED (203 docs/orchestration/ paths) |
| GX2 | trees filtered, but every object of both original trees copied into the repository as well | 4eaf584a / ebe2f45a (the right ids) | ids test RED: the excluded objects are in the repository (first `0009ddc9…`, `docs/orchestration/2026-10-05-more-models/USER-DECISIONS-P2.md`); hint test green, as expected, since the trees are right |
| GX5 | README.md also dropped from both roots (over-exclusion) | a944ee64 / e0e552ea | ids test RED (README.md missing from the tree minus docs/orchestration/); make-repo's own diff check passed, as expected, because both trees lose the file |
| GX3 | accepted0 alone also loses `docs/ARCHITECTURE.md` (base0 keeps it) | none | make-repo exit 1, "base0..accepted0 is not 16f637f..01a8604 outside docs/orchestration/", target removed |

Each mutation was checked with `bash -n` before its run.

## Step 5: the full validation

All of these ran on the final pack and test files, with TEMP and TMP on `.tmp-gate`.

- `MOONALIZA_CLONE=<the clone> python -W error::SyntaxWarning -m unittest -v tools.test_calibration_kit.HostPackX21`,
  15:29-16:28Z: **17 tests OK** in 3517 s, `tearDownClass` included (the clone and the class's link folder unchanged).
  In it:
  - make-repo builds the manifest ids `4eaf584a` / `ebe2f45a`, the diff check holds, and the new object and
    tree-minus assertions pass;
  - the new no-hint test passes;
  - the journey test is red at base0 and 18 of 18 green at accepted0;
  - every WRONG-FIXES row grades FAIL: the candidate's tests are green, the guard is red, scope and lint are ok, and
    the accepted journey test fails at exactly the row's stated count;
  - the accepted fix and both alternative correct fixes grade PASS;
  - the reshaped accepted fix (the 13 slice probes) stays lint clean and green;
  - the F5 test passes;
  - the launch refusals hold, and the prompt has no `Cause:`.
  The graded results at the new ids are therefore the same as round 3's at the old ids.
- `python -W error::SyntaxWarning tools/test_calibration_kit.py` (no clone, as the gate runs it), on the final files,
  this report included: 133 tests, OK, 10 skipped. The skips are the clone tests, reported UNSUPPORTED: round 3's 9
  plus the new one.
- `python -m unittest tools/test_check_calibration_evidence.py`: 51 OK.
- `python tools/check_calibration_evidence.py`: 3 folders, 0 failures, 14 limitations, exit 0.
- `qualification_table.py --check`: exit 0. `check_secrets.py`: clean (0 hits).
- **The clone.** I recorded its state at 15:02:22Z, after this round's first scratch builds and before the guards, the
  shapes run and the full run. I recorded it again at 16:28:44Z, after the full run. The two records are identical:
  - `git --no-optional-locks status --porcelain --ignored` gives `!! node_modules/` and
    `!! research/raw/.diagnostics.jsonl` both times;
  - `node_modules/.vite*` does not exist either time;
  - `x21_tree` (the mtime and size of every entry, 19,137 entries) is equal both times.

## LIMIT-1

The decision says "LIMIT-1 still stands". I found no item with that id in the worktree (`git grep LIMIT-1`) or in the
run's side-session notes, so I could not cite its exact wording. Whatever it says, this round claims nothing stronger
than the tests. The README and the manifest say the hint check is textual and that a paraphrase is not caught. The
cause check stays as round 3 left it (`cause_in_prompt: false`, textual). The base's code, spec and tests still
describe the reconcile, because the base must.

## What I got wrong and fixed

- My first edit of make-repo.sh went through a Python heredoc whose exact-match assertion failed, so nothing was
  written. I made the edit with the Edit tool instead.
- The first `filter()` relied on `set -e` inside a command substitution, where bash does not inherit errexit, so a
  failed `pack-objects` or `mktree` would have gone unnoticed. Each pipeline now ends in `|| fail`.
- My first object test asserted that the repository holds exactly the objects `rev-list --objects --all` reaches.
  That would fail on the two legitimate unreachable trees (the accepted root and `tests` tree from before the journey
  test). I replaced it with "no excluded object that the tags do not reach" plus "no unreached blob".
- The reached set first held only blob ids. A tree object shared between `docs/orchestration/` and another path could
  then have been flagged as forbidden even though it is legitimately reached. It now uses `ls-tree -r -t`, so trees
  count too.
- The first guard-mutation script turned `\\\n` into a literal newline. That broke the root and docs loop matches, so
  GX1 and GX2 had bash syntax errors and GX3 and GX5 failed for the wrong reason. I rewrote it with `chr()` constants,
  checked every mutated script with `bash -n`, and re-ran all four guards. Only those re-runs are cited above.
