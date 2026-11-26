# sr-pack-4a, integration check 3: refute-first check of the rebase onto build/sr-kit-cases and of lead integration round 3

Verdict: **FIX**, for one S2 (IC3-1). Checked `build/sr-pack-4a` at f6f0e2d against the round-3 report
(`sr-pack-4a-integration-3.md`), the integration check (`sr-pack-4a-integration-check.md`), the kit report's N-1
(`sr-kit-cases-lead-integration.md`), the brief `run4-pack-4a-builder.md` and `conventions.md`. Fresh context; I wrote
none of the change. This report is the only file this round adds. Every run had TEMP and TMP on the gittoken
`.tmp-gate` folder; the MoonAliza clone was only read.

Round 3's own claims hold: the rebase is clean, the cause is real and stays out of the fix prompt's text, IC-2, IC-3 and
IC-5 are closed, every wrong fix still FAILs, every correct shape I tried passes, and no run wrote into the clone. But the
candidate's checkout itself holds the cause and the accepted fix's design (IC3-1). So `cause_in_prompt: false` does not
actually hide the cause from the candidate.

## Findings

| id | severity | finding |
|---|---|---|
| IC3-1 | S2 | **The base tree a candidate checks out carries the answer key.** `base0` is MoonAliza 16f637f's tree as it is (`make-repo.sh`; `test_make_repo_builds_the_manifest_ids` asserts `base0^{tree}` equals 16f637f's tree), and that tree holds MoonAliza's own orchestration record of this fix. `docs/orchestration/2026-10-13-github-sign-in/briefs/fix-x2-1.md` states the cause with file and line ("`references()` (`:101`) returns `[]`, and `src/main/index.ts:195` passes a reconcile set without the pair. The vault's reconcile ... then deletes the staged pair as unreferenced"). It also gives the accepted fix line by line (`GitHubAccountStore.unreadAtOpen()`, `Vault.reconcile(committedReferences, options?: { keepStaged?: boolean })`, the index.ts call), and three of the wrong fixes as "Rejected" (W-a, W-d, W-b). `reports/calibration-2-extra-findings.md` (X2-1) states the mechanism as well. `RUN.md`, `smartrouter/trace/calibration-2/lead-notes.md`, `.../observations.json`, `.../trace/decisions/fix-x2-1-1.json` and `.../trace/ledger.jsonl` name it too. Verified in a real grade checkout: in a history-less checkout of `base0` made by the class, `fix-x2-1.md` exists and names `unreadAtOpen` and `keepStaged`, and `git grep -l X2-1` lists four files. The fix prompt names the finding `X2-1`, the brief's file name is `fix-x2-1.md`, and the prompt allows reading anything inside the checkout. So a candidate that greps for the finding id reads the cause and the accepted change. That defeats `cases.fix.cause_in_prompt: false` and the brief ("The cause is NOT in the candidate's task text"; H3: "the candidate never sees it"). It also breaks the kit's isolation rule ("The accepted fix, the ground truth ... live outside every candidate's permitted paths"; "never the accepted change") and makes the manifest's `isolation` text false. A fix@T3 cell graded PASS would not show that the profile found the cause. No test catches this: the cause test reads only the rendered prompt, and the hygiene scan reads only the pack's own files. **Fix (the lead decides, because the brief says "exporting the base tree 16f637f"):** have `make-repo.sh` export both trees without `docs/orchestration/` (or without the seven files named here), so the base0..accepted0 diff stays as it is. Record the new ids in the manifest (`cases.fix.base`, `present_at`, `accepted_fix` twice). Replace the tree-equality assertion with "16f637f's tree minus the excluded paths". Add a test that no file of `base0` contains `X2-1` (case-insensitive), `unreadAtOpen`, `keepStaged` or any of `X21_CAUSE_PHRASES`, and show it red at the current make-repo. State the exclusion in the README and in `isolation`. |

Checked and not findings (each at most S4, unchanged from earlier rounds or disclosed):

- The prompt narrows the search without stating the cause. The module's promise and the required behaviour say "an
  unreferenced staged entry is deleted by the next start that reads the file" and "leaves the new pair in the vault as
  the crash left it". The instructions name the index.ts region that holds the reconcile. The brief puts the first two
  into the required behaviour, and the last is the F1 limit the lead accepted (integration check, "Instructions"). Not
  restated as a cause.
- The phrase check is textual. A paraphrase in the instructions passes it (N1 below, green). Round 3 discloses this
  limit.

## Is the branch build/sr-kit-cases plus this unit's commits, with no kit file changed?

- `git merge-base HEAD build/sr-kit-cases` = 09b476d = the tip of build/sr-kit-cases. `git log 09b476d..HEAD`: the eight
  commits of this unit (3981310 ... 4795b53, f6f0e2d). Verified.
- `git diff --stat 09b476d HEAD` touches `CHANGELOG.md` (+1 line), the pack directory, `tools/test_calibration_kit.py`,
  `tools/calibration/subject-pack/README.md` (+7: the host-pack paragraph the brief allows) and the reports. No
  `run.template.js`, `grade.sh`, kit README, `observations.py`, `historyless-checkout.sh` or fixture. In
  `tools/test_calibration_kit.py` the unit's edits to existing code are three: `checkout()` gains a `timeout` keyword,
  the Hygiene scan moves into `hygiene_scan()` (same rules, with a host pack exempt from the MoonAliza-name rule only),
  and the Docs tests admit the host pack (README listing, a CHANGELOG line). Everything else is the new
  `HostPackX21` class. Verified.
- Conflict resolutions against both parents. `git range-diff 0a6d341..d154326 09b476d..4795b53`: four commits `=`, and
  three `!` whose only difference is the CHANGELOG context line (the kit's `run 4 case keys` line kept above the pack's
  line). `git diff 0a6d341 09b476d` (the kit's change) and `git diff d154326 4795b53` (the rebase's net effect on the old
  tip) have the same stat. Excluding CHANGELOG.md they are identical. In CHANGELOG.md the net effect is exactly the
  kit's one added line, with the pack's line unchanged below it. So both units' content is kept. Verified.

## The fix prompt, rendered through the kit template

Rendered with `execute_template(x21_launch_config(...))` (the kit's `run.template.js` under the stub harness, the real
manifest). One call, `fix:alpha-low`. It holds the summary, the required behaviour and the instructions verbatim and no
`Cause:`. It does not hold the cause, any of `X21_CAUSE_PHRASES` (word-normalised), the pack path, `subject-pack`,
`README` (of the pack), `WRONG-FIXES`, `zz_accepted`, `make-repo` or a commit id. Read by hand: no clause names the
reconcile's deletion, the empty reference set or the unread start as the reason. The manifest's cause matches the base
code: `open()` sets `unread` and leaves `live` null (github-account-store.ts 76-95), `references()` returns
`refsOf(this.live)` = [] (101), `index.ts` 195 reconciles with that set, and `vault.ts` `reconcile` (106-121) unlinks
and drops every staged entry not in the set. Verified. (The checkout is another matter: IC3-1.)

Cause guards re-run (`cause_guards.py`: a scratch copy of the pack per mutation under `.tmp-gate`, `X21` pointed at
it, `test_the_fix_prompt_carries_the_finding_but_not_its_cause` alone):

| mutation | result |
|---|---|
| control (unchanged copy) | green |
| C1 key removed / C1b key `true` | red (`None is not False` / `True is not False`) |
| C2 a cause phrase added to the summary | red |
| C3 cause added to the instructions / C3b to the required behaviour | red / red |
| C4 `WRONG-FIXES.md` named in the instructions | red |
| C5 the README's cause reworded | red |
| C6 the manifest's cause reworded (a phrase gone) | red |
| new N1: a paraphrase ("the store knows no refs, so the reconcile drops staged pairs") added to the instructions | **green** (the disclosed textual limit) |
| new N2: "the pack README.md" added to `subject.reference` | red |
| new N3: a cause phrase added to `subject.promise` | red |

## Shapes of a correct fix (the accepted fix plus edits, each eslint-checked, the committed journey test)

Scratch driver `probe_driver.py`. It subclasses `HostPackX21`, takes a history-less checkout of `accepted0`, resets the
three source files from `accepted0` (or `base0`) per probe, applies the edits, runs `npx eslint` on the touched files,
then runs the manifest's test command on `tests/zz_accepted_x2_1.test.ts`.

| shape | eslint | journey test |
|---|---|---|
| P1 the reconcile call wrapped over eight lines, prettier style, trailing commas | 0 | 0 of 18 failed |
| P2 block comments inside the reconcile call (between arguments and inside the options) | 0 | 0 of 18 failed |
| P3 no `;` on any line of the region, the engine call and `void supervisor.attach()` included | 0 | 0 of 18 failed |
| P4 the reconcile split over two statements (`const keepStaged = ...;` then the call) | 0 | 0 of 18 failed |
| P4b the engine call split over three statements (`reply`, `parsed`, `const references = parsed`) | 0 | 0 of 18 failed |
| P5 strings holding `/*`, `*/` and `//` between the anchors (a quoted string and a template literal) | 0 | 0 of 18 failed |
| P6 the store and the vault only, `index.ts` as the base has it: `open()` tells its vault to spare unreferenced staged entries at the next reconcile | 0 | 0 of 18 failed |
| P7 `try { reconcile } finally { }` between the anchors, and `await supervisor.attach()` | 0 | 0 of 18 failed |
| P8 `if (unread) reconcile(refs, { keepStaged: true }) else reconcile(refs)` | 0 | 0 of 18 failed |
| P9 a namespace import of the store module, a helper exported as a `const` arrow, options typed and checked with `satisfies` | 0 | 0 of 18 failed |
| P10 the whole `index.ts` with CRLF line ends and a non-ASCII comment between the anchors | 0 | 0 of 18 failed |
| P11 a local arrow helper declared between the anchors, then called | 0 | 0 of 18 failed |
| (P4c `let references` before the call, assigned by it) | 1 (`no-useless-assignment`) | 0 of 18; not a valid shape, since it is not eslint-clean |

The class's own 13 `X21_SLICE_PROBES` (the wrapped engine call, block and line comments, a string holding `/*`, no
`;`, the split call and the rest) were all green and lint-clean in the full run below. I found no eslint-clean correct
shape that grades FAIL without a disclosure. The undisclosed-looking case I tried, a fix that leaves `index.ts`
untouched (P6), passes.

## Guard proofs, re-run (scratch variants of the journey test written into the checkout; the real pack)

| guard removed | probe | result |
|---|---|---|
| G1 the declaration rule (`const from = call`) | the engine call split over two statements | RED 17 of 18 (`The symbol "references" has already been declared`) |
| G2 statement slicing replaced by whole-line slicing | a statement after the engine call on its line | RED 17 of 18 (`ReferenceError: keep is not defined`) |
| G2 | the last startup statement on the line of `supervisor.attach()` | RED 10 of 18 |
| G3 no import bound (`extra` an empty map) | an imported helper whose import carries comments | RED 17 of 18 (`ReferenceError: keepOnUnread is not defined`) |
| new G7 the slice ends one statement early (`to - 1`) | line comments | RED 10 of 18 |
| G5+G6 both F5 flags removed from `commands.test` and `run_one` (scratch pack, `X21` pointed at it from import) | the F5 test | RED: the link folder gained `.vite`, `.vite-temp`, `.vite/vitest/da39a3ee.../results.json`; `tearDownClass` passed, so the clone was unchanged |

The counts for G1, G2 and G3 match round 3's table. My G2 is a line-slicing variant of my own, not round 3's script.
My first try at it had a quoting slip, so the test file did not parse; I fixed it and re-ran, and only the second run
is cited.

## F5: the MoonAliza clone

Before my first clone run (14:42 local, after round 3's commit) and after my last (16:14 local):
`git --no-optional-locks -C <clone> status --porcelain --ignored` gave `!! node_modules/` and
`!! research/raw/.diagnostics.jsonl` both times. `ls -d node_modules/.vite*` found nothing both times. A listing of every
entry of the clone with mtime and size (19,137 entries) was byte-identical. In between: the full HostPackX21 class, the
probe and guard drivers, the G5/G6 run and the G2 rerun. Verified.

## Checks

| check | result |
|---|---|
| `MOONALIZA_CLONE=<clone> python -W error::SyntaxWarning -m unittest -v tools.test_calibration_kit.HostPackX21`, 13:00-13:59Z | 16 tests OK in 3512 s, exit 0, `tearDownClass` included. In it: make-repo ids; base red / accepted green; every WRONG-FIXES row FAILs at its stated count with candidate green, guard red, scope and lint ok; accepted and both alternatives PASS; 13 slice probes lint-clean and green; the F5 test; the launch refusals; the prompt test. Verified |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py` without the clone | 132 tests OK, 9 skipped (UNSUPPORTED), exit 0. Verified |
| `python -m unittest tools/test_check_calibration_evidence.py` | 51 OK. Verified |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations, exit 0. Verified |
| this report's commit through the pre-commit hook (regression gate) | verified by the commit landing |

## For the lead

1. IC3-1 (S2): take the orchestration record out of the trees `make-repo.sh` exports, re-pin the ids, and add a test
   that the base tree names neither the finding nor the fix. The brief's "exporting the base tree 16f637f" needs the
   lead's or owner's word on the exclusion. Without it, `cause_in_prompt: false` hides only what the checkout already
   tells the candidate.
2. Nothing else blocks: the rebase, the prompt, the slice, the wrong-fix matrix and F5 hold as round 3 says.

## What I got wrong and fixed

- My G2 variant first wrote a newline into a TypeScript string literal (Python escaping), so the journey test did not
  parse (a suite error, not a red row). I fixed the escaping and re-ran G2 alone; only the rerun is cited.
- P4c was not eslint-clean (`no-useless-assignment`), so it is listed but not counted as a correct shape.
