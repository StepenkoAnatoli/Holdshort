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
