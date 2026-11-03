# Calibration run 4: run ledger (append-only; newest entry last)

The lead's plan is `briefs/run4-plan.md` (decisions R4-1..R4-9). Conventions for every unit: `briefs/conventions.md`.
The adapter is `hosts/claude-code/` (`route.mjs decide | dispatch | outcome`, readings with `route.mjs usage`); unit
reports go to `reports/`.

## Where this run comes from

Runs 1-3 and the onboarding units (SmartRouter #100-#109) were led from MoonAliza `build/github-sign-in`, whose
`docs/orchestration/2026-10-13-github-sign-in/RUN.md` holds that history (last entry 2026-10-19 03:50 UTC, commit
46113d9) and whose `docs/orchestration/smartrouter/` was the adapter's live copy, mirrored here by refresh PRs. At #109
(main 311c36f) the mirror matched it file for file, and this copy's `trace/qualification-stats.json` is the newer
`rate` output. From 2026-10-19 the run is led and recorded here, in SmartRouter (operator's instruction); MoonAliza is
read only, for the subject trees the packs export.

## Standing rules (operator, 2026-10-19)

- Every unit goes through the adapter, with a usage reading under 30 minutes old.
- Gate 4: nothing is dispatched while it blocks unless the operator overrides; the lead never passes it by hand. Stop
  and save at seven_day 0.90; no new launch past 0.85.
- Order: at the reset, a fresh reading, then decide and dispatch sr-pack-4a and sr-kit-cases; then sr-policy-7 and
  sr-packs-t1; then freeze and launch stage 4a per the plan.
- Write less text; report at the end of each phase; merge as the lead decides, carefully; do not lower quality.
- From NEXT-CHAT.md (MoonAliza): never `--no-verify` or `GATE_OFF`, never unwire the hook; never pass `--fallback` on
  the lead's own initiative; no keys printed, copied or committed; no model identifiers in commits or PRs beyond the
  trailers; adapter acceptance checks name the category's verification items verbatim (or Gate 3 blocks); every
  request declares `difficultyTier`; draft PRs; the ledger holds no keys, prompts or bodies.

## 2026-10-19 04:10 UTC (lead) - the run moves to SmartRouter; Gate 4 still blocks

- Usage 03:46Z (desktop `get_usage`, not yet recorded in `hosts/claude-code/trace/usage.jsonl`): five_hour 0.11,
  seven_day 0.82, weekly Fable 0.87 (resets 2026-10-24 18:00Z). Gate 4 blocks; nothing dispatched.
- Reading source on this host: the desktop app's `get_usage` (percent used and reset time per plan window), not
  `list_events kinds=["rate_limit_event"]`. Mapping: 5-hour -> five_hour, weekly all-models -> seven_day, percent/100;
  the source goes in the reading's `note`. The weekly Fable window is not modelled by the policy; the 4a Fable cells
  draw on it.
- Moved in from MoonAliza: the plan, the four unit briefs and their request files (paths rewritten to this folder;
  objectives, tiers and acceptance checks unchanged), plus `briefs/conventions.md` (the rules the briefs cited from
  MoonAliza's older briefs). `sr-policy-7` now builds on `hosts/claude-code/` here (G4 also moves the policy's
  `smartrouter.revision` binding off fbe7bca, as recorded on 2026-10-19; G6 rewrites the README head).
- Armed: a one-time local scheduled task `smartrouter-run4-at-reset` at 2026-10-24 18:07Z (fresh reading, then
  sr-pack-4a and sr-kit-cases; it stops if this ledger already shows them dispatched).
- Open, the operator's call: MoonAliza's own pending dispatch (fix-c1-c3, MoonAliza Chat B) would go through
  MoonAliza's adapter copy, a second ledger whose in-flight units Gate 4 here cannot see, and the reverse.
- Next action: at the reset, a fresh reading, then decide and dispatch sr-pack-4a and sr-kit-cases.

## 2026-10-19 04:30 UTC (lead) - SmartRouter's gate fails on this host; the run folder is not committed (resume point)

- The pre-commit hook refused the commit of this folder (docs only): `test_calibration_kit` failed with 5 failures and 12
  errors. Clean main 311c36f fails the same 17 tests (79 run, 415 s), so the fault is in main, not in this change. CI
  runs the gate on ubuntu-24.04 only, and the kit tests from #106-#108 had never run on Windows.
- Causes (all from the host): `Path.read_text()` with no encoding reads README.md as cp1252; `symlink_to` needs a
  privilege this client lacks (WinError 1314, Developer Mode is off); `subprocess` calls `python3`, which hits the
  Store alias (WinError 1920); assertions expect POSIX paths but get backslash temp paths; git rejects a gitconfig fixture
  ("bad config line 8"); one list sorts differently.
- Consequence: no SmartRouter commit can pass the hook on this host, and that includes every run 4 unit commit at the
  reset. Bypassing the hook stays forbidden.
- State: this folder is staged in worktree `gittoken/sr-run4` (branch `orchestration/calibration-run-4` at 311c36f).
  Nothing is committed or pushed and no PR exists. The scheduled task `smartrouter-run4-at-reset` (2026-10-24 18:07Z)
  is still armed and does not know about this blocker.
- Open, the operator's call: (a) a Windows-portability unit for `tools/test_calibration_kit.py`, dispatched first at
  the reset (Gate 4 blocks it until then); (b) run this commit and the units from a Linux host, such as a cloud
  session; (c) an operator override to fix it now. Turning on Developer Mode (an operator setting) fixes only the
  symlink part.
- Next action: wait for the operator's choice, then commit this folder, push and open a draft PR.

## 2026-10-19 04:46 UTC (lead) - operator override: the Windows fix for the kit tests as lead work (resume point)

- Operator, 2026-10-19: "Override Gate 4 for this one: fix the Windows failures in tools/test_calibration_kit.py now
  as lead work, then commit the run folder, push and open the draft PR." This one task only; Gate 4 still blocks every
  run 4 unit until the reset.
- The fix is in worktree `gittoken/sr-kitwin`, branch `tools/calibration-kit-windows` off main 311c36f. It touches
  `tools/test_calibration_kit.py` and `CHANGELOG.md` and nothing else:
  - every file is read as UTF-8;
  - the pack's harness and its probes run with `sys.executable`;
  - the hostile gitconfig's `attributesFile` is written with '/';
  - `pack_files` sorts by name parts, with case;
  - the tests expect `<checkout_root>/<name>`;
  - the two symlink checks skip with the reason where the host cannot make a symlink (the into-the-pack case is now
    its own test);
  - the `//abs` pack spelling is tried only where paths start with '/'.
- On this host the kit gives 80 run, OK, 2 skipped (442 s). The commit through the hook was running at 04:46Z (log:
  the session scratchpad's `commit-kitwin.log`).
- Known limit, recorded in CHANGELOG: on this host Git Bash's `ln -s` copies, so `historyless-checkout.sh --link`
  leaves a copy, not a link. Stage 4a checkouts on this host get copies of linked directories.
- Decisions: the fix gets its own PR, merged first once CI is green. Then `orchestration/calibration-run-4` is rebased
  on the new main, this folder is committed through the hook, pushed, and opened as a draft PR. The PR body draft is
  the scratchpad's `pr-run4.md`; its Validation line is still to fill.
- Open: the scheduled task `smartrouter-run4-at-reset` must be told that unit commits on this host need the fix on
  main.
- Next action: when the commit lands, push, open the fix PR, and merge it on green CI; then the run folder as above.

## 2026-10-19 06:02 UTC (lead) - two more Windows failures behind the first; the fix widens (resume point)

- The 04:46Z commit was refused: with the kit's tests green, the gate reached `test_check_calibration_evidence` and
  failed there. The gate stops at its first failing check, which is why the 04:30Z diagnosis saw only the kit's.
  Running the remaining checks by hand showed `test_qualification_table` failing too; every other check passed.
- Causes (host): `Path.write_text` writes CRLF on Windows, so `observations.py` and `qualification_table.py` output
  differed from the committed LF bytes; the evidence test's `journal.jsonl` and `JOURNAL.JSONL` cases shared one folder
  on NTFS; the table test replaced a `C:\...` path where the table prints `C:/...`.
- Lead decision: these are the same task under the 04:46Z override (make the gate pass on this host so the run folder
  can be committed). The fix branch now also changes those two writers (`newline="\n"`, the identity on POSIX) and
  the two tests. On this host: evidence 51 OK, table 20 OK. CHANGELOG entry widened.
- The recommit through the hook started 05:58Z without the noreply identity the run's rules require; it is left to
  finish (stopping its gate was refused here) and is then amended with
  `-c user.name=StepenkoAnatoli -c user.email=318295322+StepenkoAnatoli@users.noreply.github.com` through the hook.
  Nothing is pushed until the identity is right.
- Next action: amend, push `tools/calibration-kit-windows`, open the fix PR (body: this session's scratchpad
  `pr-kitwin.md`), merge on green CI; then rebase this branch, commit this folder through the hook, push, draft PR.

## 2026-10-19 06:35 UTC (lead) - the gate passes on this host; fix PR #110 open (resume point)

- `tools/calibration-kit-windows` committed as de25ea7 through the hook: REGRESSION GATE all checks PASS on this
  Windows host, the first full green gate here. Author and committer are the noreply identity. The 05:58Z attempt
  never made a commit (the hook refused it: the widened CHANGELOG entry named the evidence test's file, which the
  evidence check's one-CHANGELOG-line rule counts), so the 06:02Z amend plan was not needed.
- Pushed; draft PR #110, CI pending at 06:33Z (regression-gate, claude-code-adapter-tests, watcher-once-proof).
- The scheduled task `smartrouter-run4-at-reset` now checks that the fix is on main before any unit work.
- Next action: on green CI, mark #110 ready and merge it (merge commit, as #100-#109); then move this branch onto the
  new main (it has no commits; the folder is staged: `git checkout -B orchestration/calibration-run-4 origin/main`
  carries the index), commit this folder through the hook with the noreply identity, push, open the draft PR (body
  draft `pr-run4.md`, Validation line to fill with the hook result).

## 2026-10-19 07:34 UTC (lead) - #110 merged; this folder is committed on the new main

- #110 merged as e4bc1e1 on green CI (regression-gate, claude-code-adapter-tests, watcher-once-proof). The hook now
  passes on this host, so run 4 unit commits can land here after the reset.
- This branch was re-cut from e4bc1e1 with the folder staged, and this folder is committed through the hook in the
  same step, then pushed as a draft PR. The 04:46Z override task is done with that PR; Gate 4 still blocks every run
  4 unit until the reset (2026-10-24 18:00Z), and the scheduled task stays armed.

## 2026-10-21 02:30 UTC (lead) - renamed to Holdshort; this branch moved onto the rename; the 07:34 entry corrected

- The project is now Holdshort (ADR-0003): PR #112 merged as 4ea8c6d on 2026-10-20, and the GitHub repo is
  `StepenkoAnatoli/Holdshort` (the old URL redirects). The policy's upstream block is `holdshort`: where the 2026-10-19
  entries say `smartrouter.revision`, read `holdshort.revision`. `route.mjs` refuses a policy that still carries
  `smartrouter`, except host-policy-1..5 and host-policy-6 as a frozen copy under `trace/policies/`.
- Correction to the 07:34 entry: the folder was committed on e4bc1e1 but never pushed. GitHub has no
  `orchestration/calibration-run-4` branch and no PR for it (checked 02:28Z), so the 04:46Z override's last step
  (push, draft PR) is still open.
- Rebased onto 4ea8c6d now (the run commit is 0527d08) instead of staying on e4bc1e1. Why: no run 4 decision or
  dispatch exists, unit worktrees start from origin/main anyway, so nothing recorded is bound to pre-rename bytes; and
  the briefs must describe the tree the units will see. The live policy loads on this tree (host-policy-6, `holdshort`).
- Briefs and requests now use Holdshort for the project. `briefs/conventions.md` has the rename map and what keeps the
  old name. policy7-builder G1 freezes the live, renamed bytes that sr-policy-7's decision binds, never a pre-rename
  version; G4 moves `holdshort.revision` and names `tests/holdshort_decisions.py` for citations at the new commit.
  The gate time is corrected to 36-50 minutes. Objectives, tiers and acceptance checks are unchanged.
- Scheduled task `smartrouter-run4-at-reset` checked, not changed (the owner's call). Step 1's `git pull` would merge
  origin/main (this branch's upstream; pull.rebase is false) without the hook's gate; the Windows check names
  `origin/tools/calibration-kit-windows`, deleted on GitHub and kept only by a stale local ref that a prune would
  remove, which would read as "not on main" and block every dispatch (`de25ea7` is on origin/main). Proposed fixes:
  `gittoken/run4-scheduled-task-update.md`.
- Gate 4 unchanged: it blocks until 2026-10-24 18:00Z; the task fires at 18:07Z.
- Next action: the owner's yes or no on the task edits, and on pushing this branch and opening its draft PR.

## 2026-10-24 18:15 UTC (lead) - the reset; sr-pack-4a and sr-kit-cases decided and dispatched (resume point)

- Run by hand on the owner's request (the scheduler no longer listed `smartrouter-run4-at-reset`). Before acting:
  no decision or dispatch for either unit after 2026-10-19 04:10Z; this branch rebased onto origin/main 0a6d341
  (no bare pull); the Windows fix de25ea7 is an ancestor of origin/main.
- Reading 18:08:41Z (desktop `get_usage`, recorded with `route.mjs usage`): five_hour 0.01 (resets 23:00Z), seven_day
  0.00 (resets 2026-10-31 18:00Z), weekly Fable 0%. `node --test route.test.mjs`: 142/142 after recording.
- Decisions (now 18:10:10Z, deadline 2026-10-25 02:10:10Z, scratch copies of the requests): both delegate
  cc-opus-high (build-ui@T3), sr-pack-4a all-in $13.09 estimate, sr-kit-cases $15.09; ledger seq 1. Dispatches seq 2
  at 18:10:52Z.
- Worktrees from origin/main 0a6d341: `gittoken/wt-sr-pack-4a` (build/sr-pack-4a), `gittoken/wt-sr-kit-cases`
  (build/sr-kit-cases). Workflows (opus, effort high: build, refute-first review, at most two fix rounds):
  wf_700a8638-73d (sr-pack-4a), wf_fb88b23e-3e1 (sr-kit-cases). Reports: each unit's `reports/` in its worktree.
- Both units touch `tools/test_calibration_kit.py`, `CHANGELOG.md` and `subject-pack/README.md`: the lead merges
  them one after the other.
- This branch is still not pushed (the owner's call).
- Next action: read both results, integrate (draft PRs, merge on green CI), record outcomes; then decide sr-policy-7
  and sr-packs-t1 from the branch carrying sr-kit-cases.

## 2026-10-24 19:05 UTC (lead) - the workflows relaunched; a host TEMP fault in the gate (correction to 18:15)

- The first commit of the 18:15 entry was refused: `test_live_dispatcher` T17 calls `os.path.relpath` from a temp
  folder to the repo, and this session's TEMP is on E: while the repo is on C: (ValueError, path on another mount).
  Host fault, not the change. Every commit here now runs with TEMP and TMP set to `gittoken/.tmp-gate` (on C:,
  outside every repo); the recommit passed the full gate (6d89422).
- Correction to 18:15: wf_700a8638-73d and wf_fb88b23e-3e1 were stopped before either unit changed a file (both
  worktrees clean at 0a6d341) and relaunched with the TEMP instruction as wf_d882a0aa-d1d (sr-pack-4a) and
  wf_9a4da8aa-094 (sr-kit-cases). Same dispatches (seq 2); no new decision.
- Follow-up (not run 4 work): T17 could make its temp folder under the repo's drive, so the gate does not depend on
  where TEMP points.
- Next action: unchanged from 18:15.

## 2026-10-24 19:20 UTC (lead) - owner confirms MoonAliza bugs as the test subjects

- Owner, in chat: "yes we should test it on moonaliza bugs and keep the info for holdshort". R4-1 and R4-5 stand:
  the packs test fixed MoonAliza bugs, read from a MoonAliza clone (read only) at test time. Packs, results and every
  record live in Holdshort, and no MoonAliza code is committed here.

## 2026-10-24 20:35 UTC (lead) - sr-kit-cases build stopped on its paths; one folder allowed; continuation launched

- wf_9a4da8aa-094's builder (142,609 tokens) staged K1-K4, 28 red-first tests, 27 guard proofs and the docs, and
  stopped before committing (STOP-1): K1 writes the fixture manifest's categories into `observations.json`, so the
  kit-built `tests/fixtures/calibration-evidence/` changes and the gate's Fixtures test fails. That folder was not a
  permitted path.
- Lead decision (deviation from the decided permitted-effects, recorded here and in the outcome):
  `tests/fixtures/calibration-evidence/**` is allowed for this unit, only regenerated by
  `test_check_calibration_evidence.py --write-fixtures` (the builder verified it in a scratch copy: 9 files, +27
  category lines, evidence check green). Set aside: changing K1 to omit default categories (it departs from the brief
  and hides the category the adapter will read).
- Continuation: wf_84740cc4-275 (same script, a lead note on the build step; review and fix rounds as before).
- Follow-ups the builder named, outside this unit: FU-1 evidence rule e must accept a pin cell's task-object category
  (needed before a `build-tests` T1 run is evidenced); FU-2 rule f refuses `judging_profile: null` (4a names a
  judging profile, R4-8, so 4a is unaffected); FU-3 `qualification_table.py` ignores gate cells; FU-4 host-policy-7
  reads category from the task objects and `review-grade` (sr-policy-7's brief); FU-5 a K2 pin is red at its base by
  rule, so the `build-tests` pack needs a base where the rules fail (sr-packs-t1's brief). FU-1..FU-3 need a unit
  before the T1 runs; the lead folds them into the sr-policy-7 / sr-packs-t1 decisions.

## 2026-10-24 21:40 UTC (lead) - PR #119 open; owner rules; policy-7 brief patch

- This branch was pushed and draft PR #119 opened by the holdshort-finish session on the owner's approval ("yes,
  lead pushes run-4 branch + draft PR"); 92e4389 pushed on top. No other PR for this branch.
- Owner, confirmed in this lead chat: push branches and open PRs without asking, then ask the owner to review;
  merges go to the owner (replaces "merge as you decide" in the 2026-10-19 mandate). Owner also confirmed the 20:35
  sr-kit-cases deviation (`tests/fixtures/calibration-evidence/**`, regenerate only).
- policy7-builder.md G4: host-policy-7's research-collect description becomes "Fetchproof (formerly Research-Kit)
  collection and brief" (owner-approved patch from the holdshort-finish session; before sr-policy-7 is dispatched).

## 2026-10-25 (lead) - sr-kit-cases accepted; draft PR #120 waits on the owner (resume point)

- wf_84740cc4-275: build f9e7b3b, review FIX (R-1 S3), fix 1 7ae4577, re-review ACCEPT at ce86512 (RR-1..RR-3 S4
  open, listed in #120). Lead re-checks at ce86512: kit suite 112 OK / 1 skipped (418 s), evidence check 0 failures,
  table --check 0, secrets clean, files within the permitted paths plus the approved fixtures folder.
- Pushed `build/sr-kit-cases`, draft PR #120; the merge is the owner's. Outcome seq 3 accepted, 696,772 tokens
  (wf_fb88b23e-3e1's are unknown and not counted).
- Open: sr-pack-4a (wf_d882a0aa-d1d) still running. Then sr-policy-7 and sr-packs-t1 decide from the branch carrying
  sr-kit-cases, with FU-1..FU-3 (evidence rule e, rule f, table gate cells) needing a unit before the T1 runs.

## 2026-10-25 (lead) - sr-pack-4a: two fix rounds spent, FIX with one S2; lead decisions; integration launched

- wf_d882a0aa-d1d (6 agents, 1,046,687 tokens): build c43b04c, review FIX (F1 S2 wiring helper, F2 S2 cause in the
  prompt, F3 S3 a missing 24 h clock row), fix 1, re-review 1, fix 2 (head b1af660), re-review 2 FIX: F2 open; R1, R2,
  R4 and the rest verified; new RR2-1 S4 (a correct fix formatted over lines fails 17/18). Re-review 2's report is
  uncommitted (its agent returned before the hook could run).
- Lead decisions:
  - F2: `run.template.js` prints `Cause:` into the fix prompt. The kit is not changed: that would alter the shared
    prompt runs 1-3 used, and it collides with #120. In this fix-only pack nothing but the prompt reads `cause`, so the
    manifest's cause is reworded to name no mechanism, and a test pins that. Kit follow-up: a grader-only cause field.
  - R3: the candidate instruction is reworded to drop the location hint, keeping the F1 limit disclosed.
  - RR2-1: fixed, because a correct fix graded FAIL would corrupt the 4a cells.
  - Ratified: F4 `--testTimeout=60000` (measured timeouts under load; it changes nothing that is graded) and F6 (the
    hygiene exemption stops at `subject-pack/host/`, where packs name their subject by design).
  - F5: vitest left git-ignored caches `node_modules/.vite` and `.vite-temp` in the read-only MoonAliza clone; the
    owner decides whether to delete them.
- Lead integration (not a third unit round): wf_ebafb09d-6a1, an integration fixer, then a refute-first check.
- Integration round 1 (wf_ebafb09d-6a1, 301,864 tokens): 19aeda2 (cause reworded, instruction reworded, slicing
  fixed; HostPackX21 with the clone 15 OK), check d154326 FIX: IC-1 S3 (the new cause pointed the candidate at the
  pack's README, which the kit forbids in the prompt), IC-2 S4 (a correct fix with no `;`, or split in two
  statements, fails 17/18), IC-3/IC-4 S4 (untested guard, a word-blocklist test), IC-5 S4 (the deviation is undocumented).
- Integration round 2 (wf_6557048d-00a): a fixed one-sentence cause pinned by exact text, plus a check on the
  rendered prompt; slicing robust to both shapes, with a hunt for other correct shapes; the IC-3 probe; the IC-5
  README line. Then a refute-first check with at least five shapes.
- Owner, 2026-10-25, about F2: "fix it instead" (fix the kit, do not reword the cause). Round 2 stopped; its partial
  diff was set aside, and the worktree is clean at d154326. Plan: the kit fix as lead integration on build/sr-kit-cases
  (#120), then rebase sr-pack-4a onto it, restore the real cause, and hide it through the kit. Resume point: the
  lead's side-session note `run4-resume.md`.

## 2026-10-25 06:10 UTC (lead) - new lead session; the kit fix launched; F5 decided

- The lead moved to a fresh session (the earlier one ran out of context). Reading 05:55Z (desktop `get_usage`):
  five_hour 0.06, seven_day 0.08, weekly Fable 0.
- Step 1 of the plan: lead integration on `build/sr-kit-cases` (#120), workflow wf_95043af6-f02 (opus, high). It adds
  an optional manifest key, `cases.fix.cause_in_prompt` (boolean, default true). With true or absent, the fix prompt
  stays byte-identical, so runs 1-3 and the shared pack are unchanged. With false, the prompt omits the "Cause:"
  clause, and graders still see the cause. A refute-first check follows.
- F5, owner, 2026-10-25: "ok, delete the .vite caches in the moonaliza clone." The caches (`node_modules/.vite`,
  `.vite-temp`) were deleted by the previous lead session. The clone's git status is clean, and the vite/vitest
  packages are untouched. Root fix in sr-pack-4a's next round: the pack's vitest commands and HostPackX21 must write no
  cache into the clone (cache dir outside it). Deleting the caches after the run is acceptable only if that cannot be
  done. Owner rule: fix the real defect, never take the easier workaround.

## 2026-10-25 09:00 UTC (lead) - kit fix on #120 accepted; sr-pack-4a round 3 in flight; pause for the owner's shutdown

- Step 1 done: wf_95043af6-f02 (282,911 tokens). c72419a adds `cases.fix.cause_in_prompt`. The launch step refuses a
  non-boolean value, and refuses the key on a pin, review or gate case or on a finding. The refute-first check at
  09b476d was ACCEPT (two S4s open: LC-1, the docs overstate who reads the cause; LC-2, a false outside cases.fix is
  ignored). Lead re-check at 09b476d: kit suite 116 OK, 1 skipped; evidence check 0 failures; table check 0; secrets
  clean. Pushed; the #120 body has a lead-integration section.
- Step 2 in flight: wf_29220d8f-432 (opus, high), sr-pack-4a lead integration round 3. Its plan: rebase onto 09b476d
  (done, not pushed), restore the real cause with the key false, close IC-2, IC-3 and IC-5, F5 at the root (no vitest
  cache in the MoonAliza clone), HostPackX21 with the clone, then a refute-first check.
- The owner shuts the host down at about 10:25Z. A workflow still running then is stopped first. The unit's on-disk
  state and the exact restart steps are in the lead's side-session note `run4-resume.md`, the resume point.


## 2026-10-25 21:20 UTC (lead) - sr-pack-4a rounds 3-5: two more FIX verdicts, an answer key and a kit guard; round 5 in flight

- Restart 11:16Z (new lead session, after the owner's PC shutdown). Reading 11:14Z: five_hour 0.03, seven_day 0.13. The
  worktree matched the stop state; round 3 continued as wf_20fa4ac7-c1b (376,575 tokens; the stopped first agent
  wf_29220d8f-432 used 192,537 more, read from its transcript).
- Round 3: fixer f6f0e2d (real cause restored, hidden by `cases.fix.cause_in_prompt: false`; IC-2, IC-3, IC-5 closed;
  F5 at its root: no vitest cache written into the MoonAliza clone; HostPackX21 with the clone 16 OK). Refute-first check 3
  (20990ce) FIX, one S2, IC3-1: `base0` was MoonAliza 16f637f's tree as it is, and that tree holds MoonAliza's own
  orchestration record of the fix (`docs/orchestration/.../briefs/fix-x2-1.md`: the cause with file:line, the accepted
  design, the rejected wrong fixes). A candidate grepping for the finding id would read the answer, so hiding the cause
  from the prompt hid nothing. The lead verified it: every file of the tree naming X2-1, `unreadAtOpen` or `keepStaged`
  is under `docs/orchestration/`.
- Lead decision D-IC3-1: `make-repo.sh` exports both trees without `docs/orchestration/` (the brief's H3 intent, "the
  candidate never sees it", over its literal "export the base tree 16f637f"). Round 4 (wf_d79ad3bf-0ab, 313,883
  tokens): fixer 1f64138 (new ids base0 4eaf584a, accepted0 ebe2f45a; only reachable objects copied; a red-first test that
  base0 names neither the finding, its fix nor its cause; HostPackX21 17 OK; clone unchanged). Check 4 (bd6506e) FIX:
  IC4-1 S3, IC4-2 S4, IC4-3 S4.
- IC4-1: the pack README allowed linking a MoonAliza clone's `node_modules` into a checkout, and the kit's
  `historyless-checkout.sh --link` guard (on main) refuses only a directory touching the pack or the pack repository, so
  from a checkout `node_modules/..` reached the clone's fix brief and its history with the accepted fix (Item 2 broken).
  That is a shared-tooling defect, so under the owner's rule the kit is fixed, not only the README: `--link` refuses a
  directory inside any git repository, as lead integration 2 on `build/sr-kit-cases` (#120). IC4-2: the no-hint test's
  non-vacuity check passed on path names alone. IC4-3: the id LIMIT-1 was undefined (round 3's disclosed limit: the
  cause check is textual, so a paraphrase gets past it).
- Round 5, wf_a6b3de8d-2b3: kit fix, kit check, sr-pack-4a rebased onto it with IC4-1..3 fixed, check 5. Stopped about
  19:10Z for the owner's PC restart, with the kit change staged; relaunched about 19:50Z as wf_8183009b-f61 (reading
  seven_day 0.24). At 21:20Z the kit commit 69d1d03 has landed on `build/sr-kit-cases` (not pushed) and the kit check
  is running.
- Pending: on ACCEPT of both checks, push `build/sr-kit-cases` (#120, body updated with lead integration 2) and
  `build/sr-pack-4a` (a draft PR against main, stacked on #120), record sr-pack-4a's outcome (dispatch seq 2), and a
  RUN.md entry. Tokens known for sr-pack-4a so far: 1,046,687 + 301,864 + 192,537 + 376,575 + 313,883 = 2,231,546,
  plus round 5's pack part (round 2's partial is unknown). Then plan step 5 (sr-policy-7, sr-packs-t1) waits for the
  owner. Resume point: the lead's side-session note `run4-resume.md`.

## 2026-11-01 - sr-pack-4a ACCEPTED (check 5), kit lead integrations 2-8 ACCEPTED (check 8)
- Owner decision 4 (2026-10-27): wait for the weekly reset (Sat 2026-10-31 18:00Z), then fix LC7-1 and LC7-2. A new lead
  chat started at the reset (weekly usage 0.00) and ran wf_ba5994fb-daf.
- Kit lead integration 8 = f06353f: LC7-1 (S3) resolve spells every path part exactly, so no command substitution sits
  between a path and its identity proof (the hard-link bypass is closed); LC7-2 (S4) `--link` NAMEs are whitelisted and
  `git check-ignore` must prove each link ignored, else the checkout is removed. Kit check 8 = 3ed05d4: ACCEPT, no S1-S3;
  S4s LC8-1 (`MSYS=winsymlinks:lnk` makes a `NAME.lnk` file that `git add -A` stages), LC8-2 (a wrong report line),
  LC8-3 (mutant Y6 survives). Pushed to #120 (d4c2c8f..3ed05d4), body now has "Lead integration 2-8".
- sr-pack-4a: rebased onto 3ed05d4; round 5 = d1ea270 (IC4-1..IC4-3), check 5 = 2f73c9f ACCEPT, no S1-S3; S4s IC5-1,
  IC5-2 (kit README step 3 recommends a checkout `--link` refuses), IC5-3. Draft PR #122, stacked on #120.
- Outcome recorded: sr-pack-4a seq 3 accepted (dispatch seq 2); `node --test route.test.mjs` 142 pass. Tokens for
  sr-pack-4a, lower bound: 2,231,546 + 203,330 + 215,810 = 2,650,686 (round 5/5b pack parts and round 2 partial unknown).
  Kit rounds 2-8 count to sr-kit-cases (#120; its outcome seq 3 is append-only, so the cost is noted here and in #120).
- Not done: plan step 5 (sr-policy-7, sr-packs-t1) waits for the owner. Merges (#120 then #122, then #119) are the owner's.

## 2026-11-01 - review loop after the ACCEPTs: rounds 1 and 2, three findings fixed on each branch
- Why this entry: the entry above records sr-pack-4a ACCEPTED at check 5 (2f73c9f) and the kit at check 8 (3ed05d4). A
  review loop of fresh refute-first reviewers ran after those verdicts and after the outcome seq 3 "accepted" entry, and
  it found a wrong fix that grades PASS on the accepted pack. The heads below replace 2f73c9f and 3ed05d4 as the ones to
  review; the verdicts above stand as what checks 5 and 8 saw.
- Round 1 (review-loop-round-1): RL1-1 (S3, pack) a wrong fix that keeps unreferenced staged entries when the account
  file was read and refused (invalid JSON, oversized, an extra key), not only when it could not be read, graded PASS; no
  pin row had a refused file. Fixed in 045ee89 (f16f10f since the rebase below): the refused-file row (19 rows) and
  wrong fix W-o2. RL1-2 (S4, docs) the lead restart report described D-IC3-1 as the kit option
  `cause_in_prompt: false`; fixed in b93c808 (D-IC3-1 is the export of both trees without `docs/orchestration/`).
- Round 2 (review-loop-round-2): RL2-K1 (S3, kit) a gate candidate that edits an invariant file and puts a clean filter
  in its own `.git/config` plus `.git/info/attributes` graded PASS (the same class: `.git/info/exclude`, a self-ignoring
  `.gitignore`, skip-worktree, assume-unchanged, an `ident` attribute). RL2-K2 (S4, kit) `grade.sh gate` crashed with no
  JSON on a large invariant directory (one `hash-object` command line past Windows' limit). Both fixed in dead160 on
  `build/sr-kit-cases`: grade.sh reads the checkout through a view repo of its own (base tree's attributes and ignore
  rules only, the wrapper unsets git's repository variables), invariant paths hashed on stdin; 5 new tests, each route
  red on the old grade.sh. RL2-P1 (S3, pack) a wrong fix that keeps a staged pair through one unreadable start only (a
  second in a row deletes it) graded PASS: W-k's class with a limit counted in starts. RL2-P2 (S4, pack) README "Three
  things stay as they are." listed four. Both fixed in f25b52c (rebased onto dead160): the unreadable-run row (four
  unreadable starts in a row, EACCES twice, EBUSY, EIO, ten years apart), the orphan row now runs the same four starts,
  20 rows, wrong fixes W-p (keep limit of one start) and W-q (a hold earned by two kept starts); "Four things"; the
  limit left is disclosed (runs of more than four unreadable starts). accepted0 is now 577f52b4. RL2-D1 (S4, docs) this
  record stopped before the loop: this entry and the lead restart report fix it.
- Verified: dead160 and f25b52c each passed the full regression gate; on f25b52c HostPackX21 with the MoonAliza clone
  graded every wrong fix FAIL with its stated count of 20 (W-p and W-q 1 of 20) and the base-red test, fixed for the new
  row, passes alone; the MoonAliza clone is unchanged. Not run after the loop: a fresh refute-first check of the heads.
- Heads to review (nothing pushed by the loop): kit dead160 (#120 is at 3ed05d4 on GitHub), pack f25b52c (#122 is at
  2f73c9f on GitHub), docs: this entry's commit on `orchestration/calibration-run-4` (#119). The pack's rebase onto
  dead160 gave its commits new ids with the same changes (`git diff` of the pack's own commits checked equal): check 5's
  2f73c9f is fb55bb3 and RL1-1's 045ee89 (never pushed) is f16f10f.
- Outcome log: seq 3 "sr-pack-4a accepted" is append-only and stays; it names the check 5 head. The loop's fixes are
  not a new dispatch, so no outcome entry is added for them; the record of the change of head is this entry.
- Not done: the pushes of the three branches and the #120/#122 body updates (the lead's next step), the merges (the
  owner's), plan step 5.

## 2026-11-01 - review loop round 2, RL2-1: the refused-file row extended to a file that names the pair
- Why this entry: the entry above names pack f25b52c as the head to review. Round 2 had one more pack finding, fixed in a
  separate session after f25b52c landed: RL2-1 (S3, pack). The refused-file row (RL1-1) refused only the signed-out
  file (account null), so a wrong fix that reads a refused file again without the format and keeps the unreferenced
  staged entries while it still names an account passed all 19 rows and graded PASS through `grade.sh fix`, and so did
  one keyed on a format version other than 1; the README did not disclose it. Spec 4.4: a refused file reads as no
  account, whatever it holds.
- Fixed in 556b166 on `build/sr-pack-4a` (on f25b52c; the kit did not move, dead160): a named refused-file row (a first
  sign-in's crash before commit 1, then the file that names the pair is refused as invalid JSON, over 64 KiB, with an
  extra key and with version 2: each start deletes the pair and rewrites the file), a version-2 form on the
  refused-file row, 21 rows, wrong fixes W-o3 (keep while a refused file names an account, 1 of 21) and W-o4 (keep on
  another format version, 2 of 21); W-c 7 and W-o2 2 of 21. The README limit "Refusals other than the four." discloses
  the disallowed values not written (a revision of 0, a malformed ref, a ninth retired ref). accepted0 is 1f7aa3bf.
- Verified: on scratch trees the accepted fix passes 21 of 21 and the reviewer's two wrong fixes fail (the new row; the
  version-2 forms); red first, the new kit test on f25b52c's pack files fails 2; HostPackX21 with the MoonAliza clone
  all 18 OK in 7566 s, every wrong fix FAIL with its stated count; its tearDownClass F5 check reported the clone's `.git`
  mtime changed at 15:32:49Z, attributed to a read from outside the class (no file in `.git` changed; the six tests that run the
  clone pass with F5 on a rerun, mtime unchanged); the clone is unchanged (status empty, HEAD 1ac226d); 556b166 passed
  the full regression gate (kit suite 163 OK, 11 skipped; evidence 0 failures).
- Heads to review (nothing pushed): kit dead160, pack 556b166, docs this entry's commit. Not done: the pushes, the #122
  body update, the merges (the owner's).

## 2026-11-01 - review loop round 3: RL3-K1 on the kit, RL3-1 and RL3-2 on the pack
- Why this entry: the entry above names kit dead160 and pack 556b166 as the heads to review. Round 3
  (review-loop-round-3) found three more, all fixed at the root, kit first.
- RL3-K1 (S3, kit): after dead160 the grade still ran the candidate's own git (rev-list, rev-parse, the committed and
  staged diffs, ls-files) in the checkout, and that git applies the candidate's `.git/config`: a `core.fsmonitor` hook
  ran inside the grade and could poison the grade's view repo, so the reviewer's gate case (an invariant edited, plus
  the hook) and fix case (a skip-worktree out-of-scope edit, plus the hook) both graded PASS. Fixed in d73511f on
  `build/sr-kit-cases`: grade.sh reads the candidate's history through a second bare repo of its own (the candidate's
  objects through alternates, a copy of its index, HEAD and refs read as files), so no git runs on the candidate's
  `.git` as a repository; every grade git runs with `--no-replace-objects`, `core.fsmonitor=false`,
  `core.untrackedCache=false`. 3 new tests, red on dead160's grade.sh; the reviewer's probes now PASS false.
- RL3-1 (S3, pack): no row refused a file while the vault held a committed account, so a keep beside a refused file
  while a committed entry exists (the reviewer's WF-O5) passed 21 of 21 and graded PASS, and the README sentence that
  such a fix fails was false. RL3-2 (S4, pack): the ENOENT row had only an empty vault, so the same keep for a missing
  file (WF-H3) passed 21 of 21. Fixed in 00df498 on `build/sr-pack-4a`: the named refused-file row runs a first
  sign-in before commit 1 and, beside the old committed pair, a sign-in and a refresh before commit 3 and a refresh
  before commit 4; the ENOENT row adds a sign-in that crashed after staging and a refresh before commit 3, each with
  its file removed beside the committed account. Still 21 rows; wrong fixes W-o5 and W-h3 (1 of 21 each); README
  rows paragraph and a new limit "Vault states beside a refused or missing file."; accepted0 is a106f3bc.
- Rebase: the pack branch moved onto d73511f; each pack commit kept its change (only the CHANGELOG line pair
  conflicted; change lines of d73511f..12ebdb8 equal dead160..556b166). Id map: 748925b -> a78f0d5, e8d8dec ->
  71d9d6b, 3b5a38f -> 969f7ba, 9598b70 -> cb9a256, 5d67cf9 -> 3885f71, 8be02c7 -> 961e842, c9903e3 -> 3f9b8af,
  26c89c6 -> 03df586, 4cc2d0c -> 1f3b694, e19b655 -> 2c86728, 633e10b -> e5f0e5a, 18a39a9 -> 53fbdb6, fb55bb3 ->
  f487554, f16f10f -> eb4d19e, f25b52c -> 178054f, 556b166 -> 12ebdb8.
- Verified: d73511f and 00df498 each passed the full regression gate; on the pack fix's tree HostPackX21 with the MoonAliza clone 18 of 18 OK in 4947 s, every wrong fix FAIL with its
  stated count of 21 (W-o5, W-h3 1 each); on a scratch tree the accepted fix
  passes 21 of 21, WF-O5 and WF-H3 fail one row each, and every other wrong fix fails its stated count; make-repo
  ids equal the manifest; the MoonAliza clone is unchanged (status empty, HEAD 1ac226d). Not run: a fresh
  refute-first check of the three heads.
- Heads to review (nothing pushed): kit d73511f, pack 00df498, docs this entry's commit. Not done: the pushes, the
  #120 and #122 body updates, the merges (the owner's).

## 2026-11-02 - review loop round 4: RL4-K1 on the kit; the pack rebased, unchanged
- Why this entry: the entry above names kit d73511f and pack 00df498 as the heads to review. Round 4
  (review-loop-round-4) found one more on the kit, fixed at the root; nothing new on the pack or the docs.
- RL4-K1 (S3, kit): grade.sh read the candidate's commits against the root of the candidate's own history and left
  every file the candidate's index holds out of `untracked`, so a replaced root that held a new file (`git add -A &&
  git commit --amend` of the checkout's single commit, or an orphan root) hid it from `changed`, `outOfScope` and
  `srcTouched`: the reviewer's fix cells r1 and r2 (an out-of-scope `evil.sh`) and pin cell p1 (a new `src/b.sh`)
  graded PASS. Older than the loop (origin/main, 3ed05d4 and dead160 do the same). Fixed in 7ac8143 on
  `build/sr-kit-cases`: committed and added are read against the base tree (from the pack repository, whose objects
  the history git now also reads), every file on disk the base lacks that the candidate's index holds counts as
  changed, the grade carries `baseRoot` (one root, holding the base tree) and `commits` counts only commits on top of
  it (0 otherwise, so the gate's commit is one on the base). Found while testing it: git reads a commit-graph from an
  alternate's `objects/info`, and a forged one in the candidate's objects (HEAD's parent cut) made HEAD its own root,
  hiding a committed out-of-scope file on d73511f; every grade git now runs with `core.commitGraph=false`. 3 new tests
  (amended, amended-then-pruned and orphan roots for fix and pin; the forged commit-graph; a gate history that does
  not start at the base), red on d73511f's grade.sh; mutants without the commit-graph setting or the pack alternate
  fail them; the reviewer's probes now grade PASS false.
- Pack: no finding, so no pack commit. The pack branch moved onto 7ac8143 (only the CHANGELOG line pair conflicted;
  the rebased head differs from 00df498 by exactly the kit's d73511f..7ac8143 change). Id map: a78f0d5 -> de02b1e,
  71d9d6b -> 57e25e5, 969f7ba -> 5a4c9c1, cb9a256 -> 6970184, 3885f71 -> a32bb15, 961e842 -> d2bd4b2, 3f9b8af ->
  c71b139, 03df586 -> 939bfff, 1f3b694 -> fca20d3, 2c86728 -> b045727, e5f0e5a -> 3903eee, 53fbdb6 -> 17473ce,
  f487554 -> 09387d4, eb4d19e -> 6edc4ea, 178054f -> 5635015, 12ebdb8 -> db25af2, 00df498 -> 0ec45ca.
- Verified: 7ac8143 passed the full regression gate on its commit, and the gate run on the rebased pack head 0ec45ca
  passed (the rebase made no commit through the hook); on 0ec45ca HostPackX21 with the MoonAliza clone 18 of 18 OK in
  4012 s; the clone is unchanged (status empty, HEAD 1ac226d). Not run: a fresh refute-first check of the three heads.
- Heads to review (nothing pushed): kit 7ac8143, pack 0ec45ca, docs this entry's commit. Not done: the pushes, the
  #120 and #122 body updates, the merges (the owner's).

## 2026-11-02 - review loop round 5: RL5-K1 on the kit, RL5-P1 on the pack
- Why this entry: the entry above names kit 7ac8143 and pack 0ec45ca as the heads to review. Round 5
  (review-loop-round-5) found two S4s, one on each branch, both fixed at the root, kit first; nothing new on the docs.
- RL5-K1 (S4, kit): a gate invariant's files were the base's, the candidate's index and the files on disk the base's
  ignore rules do not ignore; HEAD was never read. So an ignored file force-added under an invariant, committed, then
  unstaged (`git rm --cached`, the removal never committed) was in HEAD and on disk but in none of the lists, and the
  grade gave `invariantsIntact {tests: true}`, PASS true, though the kit README says such a file counts even when
  ignored. Fixed in 2937b2c on `build/sr-kit-cases`: `cand_blobs` also takes every name HEAD adds or changes under the
  path against the base tree (`diff-tree base-tree HEAD`, read by the grade's history git). A committed file under the
  path that is gone from disk counts too, as an indexed one already did; a base file whose disk copy matches the base
  again still passes (base files are read as the checkout stands). 1 new test (control, committed, unstaged, removed
  and staged forms), red on 7ac8143's grade.sh; on 7ac8143 the unstaged and removed forms grade PASS true, on 2937b2c
  every form but the control grades PASS false; the reviewer's toy gate checkouts now grade g0 PASS true, g1 and g2
  PASS false.
- RL5-P1 (S4, pack): the journey rows, the unreadable-run row and the tombstone row failed the reads only with EACCES,
  EBUSY and EIO, so the reviewer's W-l2 (W-l's idea with the list EACCES, EPERM, EBUSY, EAGAIN, EIO) passed 21 of 21
  and graded PASS, though it still loses the account on any other I/O error. Fixed in 7595509 on `build/sr-pack-4a`:
  a new pin row, the other-errno row (the journey's four crash points, the next start ten years later fails every
  read with EPERM, EMFILE, EINVAL or UNKNOWN; that start keeps the pair as the crash left it, the readable start after
  finds it alone, live and committed). The pin has 22 rows; W-l2 is 1 of 22 (EMFILE); nine wrong fixes the row also
  catches count one more; the README limit is now "Errno codes the rows do not use" (a fix keyed on a list of codes
  passes when the list holds all seven); accepted0 is a53755b9 (base0 4eaf584a unchanged). ENOTDIR and EISDIR were
  left out (they read close to a missing or refused file). Rewording the README alone was rejected.
- Rebase: the pack branch moved onto 2937b2c before the pack fix (only the CHANGELOG line pair conflicted; the
  changed lines of 0ec45ca..9ee7222 equal 7ac8143..2937b2c). Id map: de02b1e -> 922942e, 57e25e5 -> e9a1252, 5a4c9c1
  -> e562b2d, 6970184 -> e9757b2, a32bb15 -> 6ba9e03, d2bd4b2 -> 957fa69, c71b139 -> 14b0db4, 939bfff -> 6edcf28,
  fca20d3 -> c5cee70, b045727 -> e43dfd4, 3903eee -> a9606c2, 17473ce -> 86eeba8, 09387d4 -> 40d7ae5, 6edc4ea ->
  b06dd11, 5635015 -> 95998ef, db25af2 -> 7949563, 0ec45ca -> 9ee7222; the pack fix 7595509 is on top.
- Verified: 2937b2c and 7595509 each passed the full regression gate on their commits; the kit suite 152 OK (1
  skipped) and the evidence check 0 failures on 2937b2c's tree; on the pack fix's tree HostPackX21 with the MoonAliza
  clone 17 of 18 OK in 4346 s, every wrong fix FAIL with its stated count of 22 (W-l2 1), the one failure the
  red-at-base test, which did not yet expect the new row red at the base; with that fixed it is 1 of 1 OK with the
  clone; on a scratch tree the accepted source passes 22 of 22 and W-l2 fails the other-errno row only; the MoonAliza
  clone is unchanged (status empty, HEAD 1ac226d). Not run: a fresh refute-first check of the three heads.
- Heads to review (nothing pushed): kit 2937b2c, pack 7595509, docs this entry's commit. Not done: the pushes, the
  #120 and #122 body updates, the merges (the owner's).

## 2026-11-02 - review loop round 6: RL6-P1 on the pack
- Why this entry: the entry above names kit 2937b2c and pack 7595509 as the heads to review. Round 6
  (review-loop-round-6) found one S3 on the pack, fixed at the root. Nothing new on the kit or the docs.
- RL6-P1 (S3, pack): the unreadable start's fault (`failingReads`) failed only lstat, stat, open and readFile of
  node:fs/promises and their sync forms. The callback forms still read the file, and so did `createReadStream`, which
  opens through the callback `fs.open`. So the reviewer's W-r passed 22 of 22 and graded PASS: it reads the file again
  by a stream, and the vault keeps only the staged refs that read names. On a real unreadable file the stream fails
  too, so W-r loses the account as the base does. The README said the opposite ("a fix that re-reads the file another
  way still meets the error").
- Fixed in a6d12b8 on `build/sr-pack-4a`:
  - The test file installs wrappers once, before the subject's modules load. They cover open, readFile, stat, lstat,
    access, copyFile and cp, in the promise, callback and sync forms, plus openAsBlob. While a fault is set, any call
    whose path names the account file fails: a string, a Buffer or a file: URL, relative or not, and on Windows in any
    case. A stream meets the error through the callback open, as its 'error' event.
  - Each session and each start loads the subject's two modules afresh (`vi.resetModules`, then a dynamic import), as
    a new process of the app does. Before this, every start ran in the first session's module instance, so a module
    variable could remember the refs across a "restart".
  - Three new wrong fixes, each 14 of 22: W-r (the reviewer's stream re-read), W-r2 (the same re-read through a
    `promisify(readFile)` taken as the module loads) and W-r3 (the refs of the last file the process wrote, kept in a
    module variable). WRONG-FIXES.md names twenty-seven.
  - README: the simulation paragraph says what fails and names W-a, W-r, W-r2 and W-r3. A new limit, "Reads outside
    `node:fs`", covers a child process, a worker thread, a native addon or internal bindings.
  - accepted0 is d8af1fd4 (base0 4eaf584a unchanged). Still 22 rows.
- How the class was hunted: nine more second-read routes passed the 7595509 test 22 of 22. They are openAsBlob, a
  Buffer path, promisify(fs.readFile) at call time, copyFile then read, cp of the directory, promisify(readFile) taken
  at load, fs.readFileSync taken at load, a file: URL and an upper-cased path. The reviewer's callback-only probe caught
  one of them. Each fails 14 of 22 on the new test. W-r3 came out of the same hunt.
- Decisions:
  - Rewording the README alone was rejected.
  - createReadStream itself is not swapped: a sync throw is not how a real stream fails.
  - A real OS lock was rejected: on Windows it gives EBUSY only, and the rows need seven codes.
  - The reviewer's optional orphan-row assertion was not added. W-r fails without it, and whether "leaves the pair as
    the crash left it" covers every unreferenced staged entry is the owner's reading.
- No rebase: the kit did not move (build/sr-kit-cases is still 2937b2c).
- Verified:
  - a6d12b8 passed the full regression gate on its commit.
  - HostPackX21 with the MoonAliza clone on the fix's tree: 18 of 18 OK in 4895 s, every wrong fix FAIL with its stated count of 22 (W-r, W-r2 and W-r3 14), the alternatives PASS, red at base OK.
  - On a scratch tree the accepted source passes 22 of 22, and W-r, W-r2 and W-r3 each fail 14 of 22. The 7595509 test
    passes all three 22 of 22 (red first).
  - tsc gives 0 errors and eslint is clean on the test.
  - The MoonAliza clone is unchanged (status empty, HEAD 1ac226d).
  - Not run: a fresh refute-first check of the heads.
- Heads to review (nothing pushed): kit 2937b2c, pack a6d12b8, docs this entry's commit. Not done: the pushes, the
  #120 and #122 body updates, the merges (the owner's).

## 2026-11-02 - review loop round 7: RL7-P1 and RL7-P2 on the pack
- Why this entry: the entry above names kit 2937b2c and pack a6d12b8 as the heads to review. Round 7
  (review-loop-round-7) found two S3s on the pack, both left by the RL6-P1 fix, both fixed at the root. Nothing new on
  the kit or the docs.
- RL7-P1 (S3, pack): every start ran in the one vitest process. `vi.resetModules` gives fresh modules, but it keeps
  `globalThis`, `process`, its environment, the built-in module objects and the `Symbol.for` registry. So the
  reviewer's W-g (W-r3 with its memory on `globalThis`) passed 22 of 22 and graded PASS. A real next start is a new
  process and keeps none of it, so W-g loses the account as the base does. The README and the comment on `load()` said
  nothing a start keeps outlives it.
- RL7-P2 (S3, pack): the fault matched the path string, and `link`, `rename` and `symlink` were not wrapped. So the
  reviewer's W-s (a second read through a hard link it makes to the file) passed 22 of 22 and graded PASS. Under a real
  Windows lock the read through the link fails with EBUSY (the reviewer reproduced it), so W-s loses the account too.
- Fixed in cfe982c on `build/sr-pack-4a`:
  - Each later start runs as the app's next start does, in a new node process with an empty environment. The
    candidate's two modules are bundled once per run by esbuild from its own source and loaded there; the start is
    driven there and writes back the account it read, whether the file went to another app and which refs its vault
    holds. Only a first session runs in the test's process.
  - The fault knows the file by its identity (device and file index, which every name of the file shares; its real
    path where the index is 0). So a hard link, a rename, a symlink or junction, a `\\?\` prefix or another spelling
    meets the error. A module loader hook fails an `import` or a `require` of the file too. The wrappers are in place
    in the start's process before the subject loads.
  - Two new wrong fixes: W-r4 (W-g, 14 of 22) and W-r5 (W-s, 15 of 22: the rm of the link meets the fault too, so the
    file keeps a second link and the next readable start refuses it). WRONG-FIXES.md names twenty-nine.
  - README: the simulation paragraph says each later start runs in its own process, what the fault covers and that it
    goes by identity, and names W-r4 and W-r5. The limit "Reads outside `node:fs`" now names the start's process. A
    new limit, "Paths beside the subject's own module" (`import.meta.url` and `__dirname` point at the bundle).
  - accepted0 is 1c516672 (base0 4eaf584a unchanged). Still 22 rows.
- How the class was hunted: 14 more routes. Read routes: a symlink, a junction, a rename, a `\\?\` long path, the
  `::$DATA` stream name, a trailing dot, `import` of the JSON, `require` of the JSON, and a hard link then copyFile.
  Memory routes: `globalThis`, the environment, a property on `process`, a property on the `fs` module and a
  `Symbol.for` key. Eleven of them pass the a6d12b8 test 22 of 22 (the JSON import, the JSON require and the trailing
  dot fail it 14 of 22). On the new test all 14, and the nine routes of round 6, fail 14 of 22 (the hard-link copy 15).
- Decisions:
  - Wrapping `link`, `rename` and `symlink`, or clearing `globalThis` keys between starts, was rejected: each closes
    one route of a class a real new process and a real lock close as a whole.
  - The start's process gets an empty environment, not a copy of the test's: the kit's hygiene check refuses an
    environment read in a pack, and the app's next process gets nothing the last one set either.
  - A real OS lock is still rejected (EBUSY only, on Windows; the rows need seven codes).
- No rebase: the kit did not move (build/sr-kit-cases is still 2937b2c).
- Verified:
  - cfe982c passed the full regression gate on its commit.
  - HostPackX21 with the MoonAliza clone on the fix's tree: 18 of 18 OK in 6511 s, every wrong fix FAIL with its stated count of 22 (W-r4 14, W-r5 15), the alternatives PASS, red at base OK.
  - On a scratch tree the accepted source passes 22 of 22; the base, W-r3, W-g and the three other memory routes fail
    14 of 22, W-s and the hard-link copy 15. The a6d12b8 test passes W-g and W-s 22 of 22 (the reviewer's log; red
    first).
  - The new no-clone checks fail on a6d12b8's pack files and pass now. tsc gives 0 errors and eslint is clean on the
    test.
  - The MoonAliza clone is unchanged (status empty, HEAD 1ac226d).
  - Not run: a fresh refute-first check of the heads.
- Heads to review (nothing pushed): kit 2937b2c, pack cfe982c, docs this entry's commit. Not done: the pushes, the
  #120 and #122 body updates, the merges (the owner's).

## 2026-11-03 - review loop round 8: RL8-K1 and RL8-K2 on the kit, RL8-P1..P3 on the pack, RL8-D1 and RL8-D2
- Why this entry: the entry above names kit 2937b2c and pack cfe982c as the heads to review and says nothing was
  pushed. All three heads were pushed after it (PR heads updated 2026-11-02 14:00Z; #122's head force-pushed with
  lease at 18:11Z), and no entry recorded that (RL8-D2). Round 8 (review-loop-round-8-kit-docs,
  review-loop-round-8-pack) found two S3s on the kit, three S3s on the pack and two S4s on the docs.
- RL8-K1 (S3, kit): the grade's history git read the candidate's `.git/objects` as an alternate ahead of the pack
  repository's, and git reads an object by the id a store files it under. A candidate that filed an object under the
  base tree's id (the base tree plus a file it wanted hidden) hid a committed out-of-scope file (fix) or source file
  (pin); the wrong cell graded PASS. Same class, found by the fixer: a cache tree spliced into the candidate's index
  hid a staged source edit; a HEAD naming a pack commit was readable through the pack's objects.
- RL8-K2 (S3, kit): nothing read `checkout.links`, so a fix that wrote through the linked `node_modules` (the test
  runner) or replaced the link graded PASS, and the write-through changed the host's shared install.
- Fixed in ad9e4b0 on `build/sr-kit-cases` (pushed, #120):
  - The history git has no alternates. grade.sh streams the base tree's objects from the pack repository first, then
    each candidate object whose id is not there yet, and `git index-pack` files every object under the id its content
    hashes to. A HEAD naming a pack commit, or an index git cannot read, is exit 3.
  - The history index holds the candidate's entries, each written again (`ls-files -s -z` of a copy into
    `update-index --index-info`), so no cache tree the candidate wrote is read. The copy sits at the history git's own
    default index path, so no environment variable names it.
  - `grade.sh --seal NAME=DIR...` (the host, after the install, before any candidate) and `--links SEAL`: each linked
    tree is read by content before the first command and after the last; `linksIntact` joins the grade and PASS needs
    every name intact. A manifest with links and no seal is refused.
  - Kit README, pack-format README and CHANGELOG say so, with four new limits (the seal is read twice, not around each
    command, and the commands run the candidate's code; the seal's cost; grade while no candidate runs; base-ignored
    untracked files are in no list).
- RL8-P1 (S3, pack): the fault knew a path as a string, a Buffer or a `URL`; a second read with the path as a
  `Uint8Array` (W-t) or a URL-shaped object (W-t2) passed 22 of 22.
- RL8-P2 (S3, pack): a start moved only `Date`; a day-limited keep measured by `performance`'s clock (W-u) passed.
- RL8-P3 (S3, pack): the fault's error carried only a code; a fix that deletes after a failed read (`syscall: 'read'`,
  taken for a failing disk) and keeps otherwise (W-l3) passed, while a real byte-range lock fails the read with EBUSY.
- Fixed in 1feb090 on `build/sr-pack-4a` (rebased onto ad9e4b0 first; id map below):
  - The fault hands each argument to the real `stat`, so it reads every path form `node:fs` takes; only a descriptor
    or a FileHandle names no path.
  - The fault's error has a real one's shape (libuv's errno and message for the code, the syscall, the path), and it
    fails where a real one does: at the stat, at the open, or at the read of what the open gave (a descriptor's
    `read`/`readv`, a FileHandle's reads). Each code of the journey rows and the other-errno row fails three starts in
    a row, ten years apart, at the stat, the open and the read; the unreadable-run and orphan rows take the phases in
    turn. Still 22 rows.
  - A start's process moves every clock it reads (`Date`, `performance.timeOrigin`, `Intl.DateTimeFormat` with no
    date, `process.hrtime`), and before each start the data directory's file times move back as far as the clock
    moved since they were written. The system's uptime is not moved: ten years on, the system has booted since.
  - Eight new wrong fixes, each 14 of 22: W-t, W-t2, W-u, W-l3 (the reviewer's) and W-u2 (`Intl`), W-u3 (file times),
    W-u4 (boot time), W-l4 (the read told by the error's message) from the class hunt. WRONG-FIXES.md names
    thirty-seven. README: the fault paragraph, the clocks, and the limit "Clocks a start cannot move" (birth and change
    times, clocks outside the process; the boot time fails, W-u4). accepted0 is 970e5e47 (base0 4eaf584a unchanged).
  - The pack follows the kit's new links interface: README steps 3 and 4 seal `node_modules` and `.build` (an empty
    directory when the host has none) right after the install and grade with `--links`; HostPackX21 does the same and
    checks `linksIntact`. The first HostPackX21 run with the clone found this: ad9e4b0 refused every grade of the
    pack (42 failures, 37 of them subtests under a parent pytest printed as PASSED).
  - W-p's row in WRONG-FIXES.md now says FAIL 14 of 22 (was 1 of 22); the second clone run found the mismatch. With
    three unreadable starts in every journey row and in the other-errno row, W-p's delete at the second unreadable
    start in a row fails those 13 rows as well as the unreadable-run row (checked by row title: the 8 other rows
    pass). That run also hit a full disk on C: (7 failures "No space left on device"); the clone run's TEMP moved
    to E:, nothing was deleted.
- RL8-D1 (S4): the bodies of #119, #120 and #122 were stale against the pushed heads, and #122 still carried the
  pre-RL1-2 D-IC3-1 wording. All three refreshed with gh (no AI footer).
- RL8-D2 (S4): this entry, and the lead restart report now has eight rounds, an id table for the pushed branches and
  a Next that matches.
- How the class was hunted: four more routes written as wrong fixes and run against the new test: the age by `Intl`'s
  date, by file times and by the boot time, and the read told by the error's message. The `Intl`, file-time and message
  variants pass the cfe982c test 22 of 22 and fail the new one 14 of 22 (red first). The boot-time variant fails both
  14 of 22 (uptime was never moved), so it guards against a later change that moves it. Two variants were malformed on
  the first run (a backspace byte where the regex `\b` was meant; a ternary that disabled every delete on a readable
  start); both were repaired and rerun, and the failing rows are the expected 14.
- Decisions:
  - The K3 hygiene check flagged the first index fix (it read `os.environ` to set `GIT_INDEX_FILE`). The rule was not
    narrowed; grade.sh was changed so it reads no environment variable.
  - The delete of the index copy has no test that can see it (the grade's outputs do not show which index extensions
    the history holds, and the history is removed when the grade ends), so the docs' "no extension kept" claim was
    removed rather than left unguarded. What the docs claim now (no cache tree the candidate wrote is read) is guarded:
    the cache-tree test goes red when the candidate's index is used as it is.
  - Moving the uptime was tried and reverted: a fix that deletes a pair created before the boot then passed.
  - The reviewer's option of dating the crash in the past was set aside: the rows need several starts ten years apart,
    and each would need its own clocks moved anyway.
- Pack ids after the rebase onto ad9e4b0 (old -> new, by subject): cfe982c -> ae4e0f4, a6d12b8 -> c0bae1e,
  7595509 -> 16977d9, 9ee7222 -> af1d3bc, 7949563 -> 77c61d4, 95998ef -> bce1f57, b06dd11 -> 9a5fbf1,
  40d7ae5 -> 2d56057 (check 5's report), 922942e -> 2115e68 (the unit's first commit).
- Verified:
  - Kit: the full kit suite with no early stop, 155 passed, 1 skipped (the history-less checkout links test: Git Bash
    makes no symlink on this host), pytest exit code 0; ad9e4b0 passed the full regression gate. Red first on 2937b2c
    for the forged object, the cache tree, the links and the pack-commit HEAD; each guard's removal turns a test red.
  - Pack: on a scratch tree the accepted source passes 22 of 22 and the base and every new wrong fix fail 14 of 22;
    the cfe982c test passes W-t, W-t2, W-u and W-l3 22 of 22 (the reviewer's grades) and W-u2,
    W-u3 and W-l4 22 of 22 (this round's runs): red first. tsc 0 errors, eslint clean
    on the test. HostPackX21 without the clone 8 passed, 10 skipped; with the read-only clone 18 passed and 53
    subtests, exit 0 (every wrong fix FAIL with its WRONG-FIXES.md count, accepted and both alternatives PASS,
    linksIntact true for every grade). 1feb090 passed the full regression gate.
  - The MoonAliza clone is unchanged (status, refs and stash list the same before and after).
- Heads: kit ad9e4b0 (pushed, #120), docs this entry's commit (pushed, #119), pack 1feb090 (committed, NOT pushed: the
  pack needs a force-push with lease, which is the owner's; the command is in Next of the lead restart report).
