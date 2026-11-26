# sr-kit-cases, re-review 1 (refute-first, fresh context)

Reviewed: branch `build/sr-kit-cases` at 7ae4577 (fix round 1), on 607dd30 (review 1), f9e7b3b (the builder's commit)
and base 0a6d341. Read against the brief (`briefs/run4-kit-cases-builder.md`, K1-K6), the decided request
(`briefs/requests/sr-kit-cases.json`), the conventions, the plan (R4-4), review 1 (`reports/sr-kit-cases-review-1.md`)
and the fix report (`reports/sr-kit-cases-fix-1.md`).

**Verdict: ACCEPT.** Every review-1 finding is fixed or answered as the fix report says, and I re-ran each proof. No
S1-S3 is left. Re-attacking the whole change found three new S4s (RR-1 to RR-3); none blocks.

All runs were in scratch copies of the tree outside the repository (`git archive` of 7ae4577), with TEMP and TMP on the
same drive as the copies.

## Review-1 findings, re-verified

| Finding | Fix claimed | My re-run | Status |
|---|---|---|---|
| R-1 (S3) no test for "paths read before `commands.gate` runs" | new test `test_k3_the_grade_reads_the_paths_before_the_gate_command_runs`, proof P1 | Green at 7ae4577. I split P1 into two removals. P1a moved only the `intact` line after the command: FAIL, `{'data/ledger.txt': True, 'captures': False} != {... 'captures': True}`. P1b moved only the `present` line: FAIL, `{'out/summary.md': True} != {'out/summary.md': False}`. So each half of the guard has a test that catches it. | fixed |
| R-2 (S4) vacuous mutant | `grade.sh` refuses a mutant equal to the base or the accepted fix; `test_k2_a_vacuous_mutant_is_refused` | Red on f9e7b3b's grade.sh (exit 0, not 2, on the base-equal mutant). Green at 7ae4577. P2, the base clause removed: FAIL on "equal the base's". P3, the accepted clause removed: FAIL on "equal the accepted fix's". | fixed |
| R-3 (S4) the review's category is on `review-grade` | kept by design, noted for the lead | The kit README states it. Report 1 carries it as FU-4, and the lead's RUN.md carries it to sr-policy-7. | answered |
| R-4 (S4) `inside()` clauses untested, `\x` not refused | `\` refused; `test_k3_a_rooted_or_drive_path_is_refused` | Red on f9e7b3b (exit 0 on `\x`). Green at 7ae4577. P4 (`/` clause removed): FAIL on `/x`. P5 (`\` clause removed): FAIL on `\x`. P6 (`:` clause removed): FAIL on `C:x`. | fixed |
| R-5 (S4) a timeout leaves children running | `run_bash` kills the process tree; `test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing` | Red on f9e7b3b. Green at 7ae4577. P7 (taskkill removed, bash still killed): FAIL when run alone (16 s), but OK when run beside 8 other test processes. See RR-1. I also probed four command shapes at 7ae4577 with a 1 s timeout: a python child with `; true`, a python child as the only command, a `node` child, and a bash background subshell `(...) & wait`. One more shape was `& disown; sleep 30`. In every case gateExit was 124 and no late file appeared 8 s later. With P7, and on f9e7b3b, every one of those shapes left the late file. | fixed (test weakness RR-1) |
| R-6 (S4) report and message inconsistencies | report 1 corrected | Report 1 now opens with the final state (DONE, f9e7b3b), heads the STOP-1 story as history, gives the gate's result on f9e7b3b, and explains 26 guards plus D1. | fixed |

Red first: on HEAD's tests with f9e7b3b's grade.sh, the four new tests gave 3 FAIL (vacuous mutant, timeout child,
`\x`) and 1 OK (R-1, where the guard already existed). That matches the fix report. At 7ae4577 all four are OK (142 s).

## New findings (all S4)

**RR-1 (S4): under load, the timeout test can pass with the tree kill removed.** The test gives the gate command a
1 s timeout. If bash has not started its python child within that second, the kill finds no child, and nothing tests
the tree kill. I showed this with P7 (no taskkill) on a CPU-loaded host, using a child that writes `started.txt`
first. In 3 of 3 runs, neither `started.txt` nor `late.txt` existed: the child never started. Run alone on a quiet
host, the same P7 test FAILs, as it should. The test cannot fail spuriously, and the regression gate runs the kit's
tests one after another, so on this host the guard is caught in practice. Fix: have the child write a start marker
before it sleeps. Then assert that the marker exists (the child ran) and that `late.txt` does not. Or wait in the
command until the child has started before the timeout can matter.

**RR-2 (S4): ignore rules hide a file added under an invariant directory.** `cand_blobs` lists untracked files with
`--exclude-standard`. So a file that the checkout's ignore rules cover can be added under an invariant directory, and
the invariant still reads intact. Probe at 7ae4577: the candidate adds `.gitignore` with `captures/extra.txt` (or
`captures/`), creates `captures/extra.txt`, and commits. The grade gives `invariantsIntact {'captures': True}` and PASS
true. grade.sh's docstring states this choice. The pack-format README instead says "a file added or removed under a
directory breaks it", with no caveat, and R4-5's research-collect cell wants "every capture byte-identical".
Modifications and deletions of tracked files are caught. The candidate's `.gitignore` shows in `changed`. Fix: one
README clause ("files the checkout's ignore rules hide are not read"), or list untracked files under invariant paths
without `--exclude-standard`, minus the checkout links.

**RR-3 (S4, as briefed): a required path may be left uncommitted.** `requiredPresent` reads the checkout as it
stands, and `committed` only needs one commit. Probe: the candidate commits `notes.txt` only and leaves
`out/summary.md` untracked. The grade gives `requiredPresent {'out/summary.md': True}`, `committed` true and PASS true,
with `untracked ['out/summary.md']` in the grade. This is what K3 says ("every `required_paths` path exists, and the
candidate committed"). This is a note for sr-packs-t1: a pack whose output must be committed should check that in its
gate command (for example `git ls-files --error-unmatch <path>`).

## Re-attack: also checked, found correct

- **The `run_bash` change** for pin and fix: a test timeout still reads 124, which is not red. A lint timeout still
  reads "fail". stdin, stdout and stderr are still DEVNULL. No key or result changed without a timeout.
  `start_new_session` is set only on POSIX.
- **The mutant check** runs only for a pin case with mutants. It compares `git show` bytes of `paths.source` at the
  mutant, the base and the accepted fix. A source file missing at a revision reads as None on both sides. The refusal
  exits 2, as an unusable manifest. The mutant-free pin path is untouched.
- **A gate-only pack in `run.template.js`.** Every use of `M.subject`, `M.paths` and `M.commands` is inside a lazily
  called function. The gate prompt uses only `preamble` and never the grading command, invariants or required paths.
  K4: null is accepted only without a review case, and absent is still refused. The judge is used only for review
  grading, clustering and lenses, and those run only with a review case.
- **The evidence check refuses a null `judging_profile`** (rule f, `judging-profile-named`). This is a known
  follow-up (report 1 FU-2, RUN.md), outside this unit's paths. It is not new.
- **Hygiene.** I grepped the added lines of `git diff 0a6d341 7ae4577` for host paths, session or run ids, key shapes
  and model names. No hits.
- **Permitted effects.** The fix commit touches only `tools/calibration/grade.sh`, `README.md`,
  `subject-pack/README.md`, `tools/test_calibration_kit.py` and two `reports/sr-kit-cases-*.md` files, all on the
  request's list.
- **Commit 7ae4577.** It has the identity from the conventions, the five-part message and the Co-Authored-By trailer.
  It went through the hook (the commit exists). Nothing was pushed.

## Checks (all verified)

| Check | Result |
|---|---|
| `python tools/test_calibration_kit.py`, whole file, at 7ae4577 (scratch copy) | 112 tests OK, 1 skipped (1188 s; part of the run shared the host with my CPU-load probe) |
| The four new tests at 7ae4577 / on f9e7b3b's grade.sh | 4 OK / 3 FAIL + 1 OK |
| Guard removals P1a, P1b, P2, P3, P4, P5, P6, P7 | all red; P7 red only when run alone (RR-1) |
| `python tools/check_calibration_evidence.py` (worktree) | 3 folders, 0 failures, 14 limitations |
| `python tools/qualification_table.py --check` (worktree) | exit 0 |
| `python tools/check_secrets.py` (worktree) | clean (0 hits) |
| The regression gate through the pre-commit hook | runs on this report's commit |

Untested: the POSIX `os.killpg` branch. This host is Windows. CI on Linux runs the same test (expected).

## What I got wrong and fixed

My first P7 run happened alongside eight other test processes, and the test stayed green. Before I recorded that as a
false claim in the fix report, I re-ran P7 alone, and it went red. That difference became RR-1, not a finding against
the fix report.
