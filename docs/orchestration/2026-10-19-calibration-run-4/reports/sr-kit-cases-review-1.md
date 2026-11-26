# sr-kit-cases, review 1 (refute-first)

Reviewed: branch `build/sr-kit-cases`, commit f9e7b3b on base 0a6d341, against the brief
(`briefs/run4-kit-cases-builder.md`, K1-K6), the decided request (`briefs/requests/sr-kit-cases.json`), the
conventions and the plan (R4-4). The builder's report is `reports/sr-kit-cases-1.md`.

**Verdict: FIX.** One S3 is open: a guard that grade.sh relies on, and that its own header documents, has no test.
Everything else the report claims was reproduced. The remaining findings are S4.

## Findings

**R-1 (S3): no test catches the gate grade's "read before the command runs" guard.** grade.sh reads `invariants`
and `required_paths` before it runs `commands.gate`, so that the command's side effects cannot grade the candidate's
work. The grade.sh header, the kit README and the pack-format README all promise this. The conventions say "a guard
no test catches is a missing test".

- Guard-removal proof, in a scratch copy outside the repository: I moved the `intact` and `present` lines after the
  gate command. `KitCaseGrades` (all 13 tests) stayed OK (969 s). Every gate test's command is `python3 check.py`,
  which writes nothing.
- The consequence, shown with the unit's own helpers (`make_gate_pack`, `GATE_CASE`): the gate command is
  `mkdir -p out && echo x > out/summary.md && python3 check.py`, and the candidate commits `notes.txt` without
  `out/summary.md`.
  - At f9e7b3b: `requiredPresent {'out/summary.md': False}`, PASS false (correct).
  - With the guard moved: `requiredPresent {'out/summary.md': True}`, PASS true. The candidate passes on the
    command's output.
- The real gate packs make this likely. R4-5's `research-collect` gate runs preflight and handoff, which write the
  brief and handoff files. A command that writes under an invariant directory would also fail every candidate.
- Fix: add a test with a gate command that creates the required path and writes into an invariant directory. Assert
  that a candidate without the path FAILs, and that a candidate with intact invariants is still read as intact. Then
  record the guard-removal proof.

**R-2 (S4): a vacuous mutant is not refused.** grade.sh swaps only `paths.source` files from a mutant commit. Two
mistakes in a pack would therefore go unnoticed:

- If a mutant's source files equal the base's, `redAtMutants` is true for every pin that is red at the base. The
  mutant adds nothing, and nothing says so.
- If a mutant's change lies outside `paths.source`, the swapped source equals the accepted source. Every candidate
  then FAILs, which at least shows.

The pack-format README defines a mutant as "holding the mutant's `paths.source` files", so this is a pack-authoring
error, and the sr-packs-t1 review would see it. It would be cheaper to refuse it in grade.sh: refuse a mutant whose
source files equal the base's or the accepted's. Not blocking.

**R-3 (S4): the review's category goes on `review-grade`, not on `review`.** K1 says "into `review` when present".
The builder chose `review-grade`, beside the review's `tier`, because `review` exists only when the candidate
returned structured output. The kit README says so, and the report raises it as FU-4. The lead's RUN.md entry
(2026-10-24 20:35) carries it to sr-policy-7. The policy-7 brief's G2 still lists `review` among the task objects, so
sr-policy-7 must read `review-grade` for the review. This is noted for the lead, not a defect of this unit.

**R-4 (S4): `inside()` has untested clauses.** Only `..` is exercised: `../x` and `../y`. If the leading `/` clause
or the `:` clause (a drive-letter path) were removed, no test would fail. A backslash-rooted path such as
`\x` is not refused at all.

**R-5 (S4): a gate command that times out can leave children running.** `subprocess.run(["bash", "-c", ...],
timeout=...)` kills only bash. On Windows, a `node` or `python` child keeps running and can still write into the
checkout after the grade. run_tests already has this pattern; the test sidesteps it with a pure-bash loop. Note it
in the README limits, or kill the process tree.

**R-6 (S4): inconsistencies in the report and the commit message.**

- The report still opens with the STOP-1 narrative, and its "Checks" section still says the gate "FAILED". Only the
  last section says the work was committed.
- The commit message counts "26 guard removals". The report's table has 27 rows, but D1 is a test change, so 26
  guards is right.
- The report does not name its commit sha. It explains that it cannot.

None of these changes a result.

## What I re-ran (all verified)

| Claim | My run | Result |
|---|---|---|
| Red first: 28 new tests, 25 red (19 FAIL, 6 ERROR), 3 green by design | The 4 new classes in a copy of HEAD with the six kit files and docs reverted to 0a6d341 | 28 run, 19 FAIL, 6 ERROR. The green ones are k1 golden identity, k2 no mutant key, and k3 another kind refused. Exactly as reported. |
| Green after | The same 4 classes on a copy of f9e7b3b | 28 tests OK (988 s) |
| Guard proofs G1, G7, G11, O2, T1 | Each removed in its own fresh copy of f9e7b3b, with the named test run | Each named test FAILs, as the report's table says |
| Pin, fix and review prompts byte-identical after the preamble split | Stub harness on the fixture config, base vs head | Identical (`cmp`) |
| The evidence fixture change is regeneration only | Diff of the 9 files | Only `"category"` lines: 9 each of `pin-tests`, `fix` and `review` |
| The golden-no-category fixture is the pre-change builder's output | k1 golden test against the base observations.py | Green on the base code |
| K3 stop trigger did not fire | A gate-only manifest (no subject, paths, commands or accepted_fix) through observations.py, then check_calibration_evidence.py on the folder | Builds (`cells.gate` "1 of 1 PASS", `category_mapping.gate`), and the evidence check gives 0 failures when the protocol names a judge |
| `check_calibration_evidence.py` | Worktree | 3 folders, 0 failures, 14 limitations |
| `qualification_table.py --check` | Worktree | The generated table, exit 0 |
| `check_secrets.py` | Worktree | Clean |

## Brief and rules, checked

- **K1** is met. The category is written only when the manifest names one; with none, no key is written. The
  byte-identical claim is proved by a golden copy built from the fixture inputs with the categories stripped. Runs
  1-3 are legacy folders the kit does not rebuild, and they still pass the evidence check.
- **K2** is met: `redAtMutants` and `atMutants`, one mtime step per swap, and the key order unchanged without
  mutants. The mutant list is validated: a list of `{id, commit}`, no duplicate ids, each rev-verified. See R-2.
- **K3** is met: `gateExit`, `invariantsIntact`, `requiredPresent` and `committed`. Gate items have no grader. The
  prompt is the instructions plus the preamble and never shows the grading command or the invariants. See R-1.
- **K4** is met: null is accepted only without a review case, absent is still refused, and a filled profile still
  needs its qualification.
- **K6** is met: the README section, the format README keys, one CHANGELOG line, and the adapter note.
- **Permitted effects.** All changed files are in the request's list, plus `tests/fixtures/calibration-evidence/**`.
  That deviation is recorded in the lead's RUN.md (2026-10-24 20:35, owner-confirmed at 21:40) and is limited to
  regeneration, which the diff confirms.
- **Hygiene.** The added lines contain no absolute host path, session id, run id, key-shaped value or model name. The
  fixtures use synthetic ids only.
- **Commit rules.** The identity is correct, the message has all five parts and ends with the Co-Authored-By
  trailer, it went through the hook, and nothing was pushed.

## What I got wrong and fixed

My first gate-only evidence probe failed `protocol-frozen` because I gave the run file its own id instead of the
fixture protocol's. With matching ids it passed. Otherwise, nothing to report.
