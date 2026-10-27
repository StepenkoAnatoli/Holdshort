# sr-kit-cases, fix round 1

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`. Fix round 1 answers review 1
(`reports/sr-kit-cases-review-1.md`, FIX: one S3, five S4) on top of 607dd30 (the review), which sits on f9e7b3b (the
builder's commit) and base 0a6d341. The fix is one commit through the pre-commit hook; this report is part of it, so it
cannot name its own sha (the returned gist does).

**Verdict: DONE.** All six findings are answered. R-1 (S3) and R-2, R-4, R-5 (S4) are fixed with tests, each red-first
or proved by guard removal. R-6 (S4) is fixed in the builder's report. R-3 (S4) is a note for the lead; this unit keeps
its documented choice.

## Findings and what was done

| Finding | Severity | Done |
|---|---|---|
| R-1 no test for "invariants and required paths are read before `commands.gate` runs" | S3 | New test `test_k3_the_grade_reads_the_paths_before_the_gate_command_runs`. Its gate command creates `out/summary.md` and writes `captures/by-gate.txt` (under an invariant directory), then runs the checker. A candidate without `out/summary.md` FAILs (`requiredPresent` false, gate exit 0, the command's file left in place); a candidate with it PASSes with both invariants intact. Guard-removal proof P1. No code change: the guard was already there. |
| R-2 a vacuous mutant is not refused | S4 | `grade.sh` refuses a mutant whose `paths.source` files equal the base's ("adds nothing to the base's red") or the accepted fix's ("no candidate's pin can be red at it"); the second covers a mutant whose change lies outside `paths.source`. New test `test_k2_a_vacuous_mutant_is_refused` (three sub-cases: the base commit, the accepted commit, and a commit that changes only `docs/note.md`). Proofs P2, P3. |
| R-3 the review's category is on `review-grade`, not on `review` | S4 | Not changed, by design: `review` exists only when the candidate returned structured output, so the category sits on `review-grade` beside the review's `tier`. The kit README says so. For the lead: sr-policy-7's brief, G2, should read `review-grade` for the review (FU-4 in report 1). |
| R-4 `inside()`: the '/' and ':' clauses untested, a '\'-rooted path not refused | S4 | `inside()` now also refuses a path that starts with a backslash. New test `test_k3_a_rooted_or_drive_path_is_refused` (`/x`, `\x`, `C:x`, `C:/x` in `required_paths`, the message checked). Proofs P4, P5, P6, one per clause. The format README states the rule. |
| R-5 a timed-out command leaves its children running | S4 | `grade.sh` runs every command (test, lint, gate) through one `run_bash`. On a timeout it kills the whole process tree (`taskkill /F /T` on Windows; on other systems the command runs in its own session and the process group gets SIGKILL), then bash, and the exit reads 124 as before. New test `test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing`: the gate command starts a python child that sleeps 4 s and then writes `late.txt`, with a 1 s timeout; 7 s after the grade, `late.txt` must not exist. Proof P7. The kit README says so. |
| R-6 the builder's report | S4 | `reports/sr-kit-cases-1.md` now opens with the final state (DONE, f9e7b3b, gate passed on that commit), the STOP-1 story is headed as history, the Checks section gives the gate's result on f9e7b3b, the guard table explains 26 guards plus D1 (a test change, 27 rows), and the continuation names f9e7b3b. The commit message of f9e7b3b is not rewritten (its "26 guard removals" is right, as the review says). |

## Files

- `tools/calibration/grade.sh`: R-2, R-4, R-5, header lines. `show()` moved up so the manifest checks can use it.
- `tools/test_calibration_kit.py`: four new tests in `KitCaseGrades`, and `import time`.
- `tools/calibration/README.md`: the mutants paragraph (vacuous mutants refused) and the gate paragraph (paths read
  before the command; a timeout kills the process tree).
- `tools/calibration/subject-pack/README.md`: `cases.pin.mutants[].commit` (must differ from base and accepted) and
  `cases.gate.required_paths` (the relative-path rule).
- `docs/orchestration/2026-10-19-calibration-run-4/reports/sr-kit-cases-1.md` (R-6) and this report.

All inside the request's permitted effects.

## Red first

The four new tests, run before any code change (74 s):

| Test | Before the change | After |
|---|---|---|
| test_k2_a_vacuous_mutant_is_refused | FAIL: exit 0, not 2 (base-equal mutant graded, `redAtMutants` true) | ok |
| test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing | FAIL: "the gate command's child outlived the timeout and wrote into the checkout" | ok |
| test_k3_the_grade_reads_the_paths_before_the_gate_command_runs | ok (the guard existed; proved by P1 instead) | ok |
| test_k3_a_rooted_or_drive_path_is_refused | FAIL: exit 0, not 2, on `\x` | ok |

Green after: the full `tools/test_calibration_kit.py` (see Checks).

## Guard-removal proofs

Each guard removed in its own scratch copy outside the repository (the kit folder, the test file and the kit fixtures),
the named test run there. All seven went red.

| Guard removed | Test | Result |
|---|---|---|
| P1 invariants and required paths read before the command (moved after it) | test_k3_the_grade_reads_the_paths_before_the_gate_command_runs | FAIL: `requiredPresent` `{'out/summary.md': True}`, expected False |
| P2 a mutant equal to the base refused | test_k2_a_vacuous_mutant_is_refused | FAIL: exit 0, not 2, on the base-equal mutant |
| P3 a mutant equal to the accepted fix refused | test_k2_a_vacuous_mutant_is_refused | FAIL: exit 0, not 2, "equal the accepted fix's" sub-case |
| P4 `inside()`: '/'-rooted refused | test_k3_a_rooted_or_drive_path_is_refused | FAIL on `/x` |
| P5 `inside()`: '\'-rooted refused | test_k3_a_rooted_or_drive_path_is_refused | FAIL on `\x` |
| P6 `inside()`: a drive letter refused | test_k3_a_rooted_or_drive_path_is_refused | FAIL on `C:x` |
| P7 the process-tree kill on a timeout (taskkill or killpg removed, bash still killed) | test_k3_a_gate_that_overruns_its_timeout_leaves_no_child_writing | FAIL: the child wrote `late.txt` |

## Checks

| Check | Result |
|---|---|
| `python tools/test_calibration_kit.py` (the whole file, after the change) | 112 tests OK, 1 skipped (929 s); before this fix the file had 108 |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations (unchanged) |
| `python tools/qualification_table.py --check` | exit 0 |
| `python tools/check_secrets.py` | clean (0 hits) |
| The full regression gate through the pre-commit hook | passed: the commit exists only if it passed |

Every check ran with TEMP and TMP on drive C (the host's E: temp breaks `test_live_dispatcher`, a host fault).
Verified: all of the above. Untested: the POSIX branch of the process-tree kill (`os.killpg`) has not run on this
Windows host; it runs in CI (Linux) through the same test, which would fail if a child survived.

## What I got wrong and fixed

- The first draft of the vacuous-mutant test built the outside-the-source mutant with a stray `add_mutant` call and a
  heredoc that turned `\n` into a real line break inside a string literal. Rewritten before the red run.
