# sr-kit-cases, lead integration: `cases.fix.cause_in_prompt`

Unit sr-kit-cases (run 4 plan R4-4), branch `build/sr-kit-cases`, on top of ce86512 (re-review 1, ACCEPT). The change is
one commit through the pre-commit hook; this report is part of it, so it cannot name its own sha (the returned gist does).

**Verdict: DONE.** The owner's decision of 2026-10-25 ("fix it instead"): fix the kit so that a fix case's prompt need
not print the finding's cause. The fix prompt of `tools/calibration/run.template.js` printed `Cause: ${f.cause}` into
every candidate's prompt; at tier T3 the cause must be unnamed, and the sr-pack-4a pack (built on a real accepted defect)
needs its real cause kept for the grader and the lenses but hidden from the candidate.

## Decision

A new optional manifest key on the fix case, `cases.fix.cause_in_prompt` (boolean, default true), as the lead designed it.

- **true or absent**: the rendered fix prompt is byte for byte the prompt the template rendered at ce86512, so runs 1-3,
  the shared pack and the fixture stay comparable.
- **false**: the fix prompt leaves out the whole " Cause: <cause>." clause; the summary and the required behaviour stay
  (`THE FINDING (D-2, S3): <summary>. Required behaviour: <required behaviour>.`).
- The finding's `cause` stays required in the manifest and stays in every judging text: `truthText` (the grader's ground
  truth) is unchanged and still reads `<summary>. Cause: <cause>.` whatever the key says.
- **Validation in the launch step** of `run.template.js`, beside its other refusals and before the first agent starts:
  - a value that is not a boolean (a string `"false"`, 0, 1, null, `""`, a list, an object) is refused with
    `cases.fix.cause_in_prompt must be true or false, not <value>`;
  - the key on any other case (`pin`, `review`, `gate`) is refused (`cases.<case>.cause_in_prompt: only the fix prompt
    prints a cause, so the key belongs on cases.fix`);
  - the key on a finding is refused (`findings <id> carries cause_in_prompt: the key belongs on cases.fix`).

### Where the validation lives, and the misplaced key

The kit has two places that validate case keys: `grade.sh` (at grading: `cases.gate.*`, `cases.pin.mutants`) and the
launch step of `run.template.js` (at launch: the judging profile against `cases.review`). The cause only ever reaches a
candidate through the template's fix prompt, so the check belongs in the launch step, and `grade.sh` is not touched
(it is outside this change's files, and grading never reads the key).

The existing case keys are not refused when misplaced (`grade.sh` silently ignores `mutants` on a fix case). I refused
this one anyway, as the lead preferred, because its failure mode differs: a misplaced `mutants` grades less than its
author meant, visibly in the grade; a misplaced `cause_in_prompt: false` leaves the cause in the prompt while its author
believes it hidden, and nothing in the run shows it. I extended the refusal from the other cases to the findings: the
likeliest slip is to put the key on the finding beside `cause`, and the lead's design named only pin/gate/review. A true
value is refused in those places too, so a stray key never survives.

## Alternatives set aside

- **Derive it from the tier** (`T3` hides the cause): the tier lives in the protocol, not the manifest, and coupling the
  prompt to it would change the prompts runs 1-3 rendered for any tier they recorded; a key on the case states the choice
  where the prompt is built.
- **Default false**: would change the shared pack's and runs 1-3's fix prompt bytes, so their cells would no longer
  compare with a new run's.

## Files

- `tools/calibration/run.template.js`: the launch-step checks (one comment, three lines), the conditional clause in
  `PROMPT.fix`, one sentence in the lineage header.
- `tools/test_calibration_kit.py`: `fill_template` and `execute_template` take an optional template text (to render the
  ce86512 template from git); the new class `FixCauseInPrompt` (four tests) with `GOLDEN_HOST`, `FIX_PROMPT_GOLDEN`,
  `BEFORE_CAUSE_KEY`, `golden_manifests()`; `import hashlib`; the three `KitCaseDocs` tests each check the new key;
  `SharedPack.test_the_manifest_carries_every_field_of_the_format` checks the new field on a run 4 shape (see the
  mistakes).
- `tools/calibration/README.md`: a `cause_in_prompt` paragraph in "Run 4's case keys".
- `tools/calibration/subject-pack/README.md`: the Isolation sentence ("its summary, cause and required behaviour;
  without the cause when `cases.fix.cause_in_prompt` is false"), `findings[].cause` (required; who reads it), and a
  `cases.fix.cause_in_prompt` entry.
- `CHANGELOG.md`: one clause folded into sr-kit-cases' existing "Calibration kit: run 4 case keys" line (no new line).
- This report.

## Tests (`FixCauseInPrompt`, and the docs checks)

All render prompts through the existing harness (`run_config` + `execute_template`, the stub harness under node), with
fixed host paths (`GOLDEN_HOST`, `/golden/...`) so the prompt bytes do not depend on the temporary directory or the OS.

- (a) `test_false_leaves_out_the_cause_and_keeps_the_summary_and_required_behaviour`: for the fixture manifest and the
  shared pack's manifest, each first with its own cause and then with a cause whose every word is unique
  (`QQcause-one in QQcause-two of QQcause-three`): no `Cause:` label, not the cause, no `QQcause` fragment in the fix
  prompt; the exact `THE FINDING (...): <summary>. Required behaviour: <rb>.` clause present; and the grader's prompt
  still carries `<summary>. Cause: <cause>.`.
- (b) `test_absent_or_true_renders_the_fix_prompt_byte_for_byte_as_before`: for both manifests, absent and explicit
  true, the fix prompt's (UTF-8 length, sha256) equals `FIX_PROMPT_GOLDEN`, computed from the template at ce86512 before
  any edit (fixture 2580 bytes `5e66cf5f...`, shared 3066 bytes `54a0353d...`). When the history is there, the test
  also renders `git show ce86512:tools/calibration/run.template.js`, checks that it still yields the golden, and compares
  the new prompt with it byte for byte; without the history (a scratch copy, a shallow clone) the hashes stand alone.
- (c) `test_a_non_boolean_value_is_refused`: `"false"`, 0, 1, null, `""`, `[]`, `{}` each refused with the message, no
  agent called.
- (c') `test_the_key_outside_the_fix_case_is_refused`: the key (false and true) on `pin`, `review` and a `gate` case, and
  on finding D-2, each refused with its message, no agent called.
- Docs: `KitCaseDocs` now also requires `` `cause_in_prompt` `` in the kit README's case-keys section,
  `` `cases.fix.cause_in_prompt` `` in the format README, and `cause_in_prompt` in the one CHANGELOG line.

## Red first

The new tests and the extended docs tests, run with the template, the READMEs and the CHANGELOG still at ce86512
(7 tests, 8.8 s): 6 FAIL, 1 ok.

| Test | Before the change | After |
|---|---|---|
| test_false_leaves_out_the_cause_and_keeps_the_summary_and_required_behaviour | FAIL: `'Cause:' unexpectedly found` (fixture) | ok |
| test_absent_or_true_renders_the_fix_prompt_byte_for_byte_as_before | ok, by design: it pins today's bytes; its teeth are guards G5 and G6 | ok |
| test_a_non_boolean_value_is_refused | FAIL: no refusal (error `''`) on `"false"` | ok |
| test_the_key_outside_the_fix_case_is_refused | FAIL: no refusal on `cases.pin.cause_in_prompt` false | ok |
| test_k6_one_changelog_line | FAIL: `cause_in_prompt` not in the line | ok |
| test_k6_the_format_readme_documents_the_new_manifest_keys | FAIL: `` `cases.fix.cause_in_prompt` `` absent | ok |
| test_k6_the_kit_readme_documents_the_three_keys | FAIL: `` `cause_in_prompt` `` absent | ok |

## Guard-removal proofs

Each check removed (or changed) in its own scratch copy outside the repository (the `tools` folder, the kit fixtures and
`CHANGELOG.md`; no git history, so test (b) ran on its hashes alone), then `FixCauseInPrompt`, `RunTemplate`,
`KitCaseTemplate`, `KitCaseDocs` and SharedPack's three template and format tests (24 tests) run there. A control copy
with no change was all green (24 OK). Every guard went red:

| Guard removed | Tests that went red |
|---|---|
| G1 the non-boolean refusal | test_a_non_boolean_value_is_refused |
| G2 the refusal on another case | test_the_key_outside_the_fix_case_is_refused |
| G3 the refusal on a finding | test_the_key_outside_the_fix_case_is_refused (its finding half: the case half still passed) |
| G4 the prompt's conditional (the cause always printed) | test_false_leaves_out_the_cause_and_keeps_the_summary_and_required_behaviour |
| G5 the default flipped (the cause printed only on an explicit true) | test_absent_or_true_renders_the_fix_prompt_byte_for_byte_as_before, SharedPack.test_the_workflow_template_launches_on_this_pack |
| G6 the clause's bytes changed (its final period dropped) | test_absent_or_true_renders_the_fix_prompt_byte_for_byte_as_before |

## Checks

| Check | Result |
|---|---|
| `python tools/test_calibration_kit.py` (the whole file, after the change) | 116 tests OK, 1 skipped (663 s); before this change the file had 112 |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations (unchanged) |
| `python tools/qualification_table.py --check` | exit 0, the generated table |
| `python tools/check_secrets.py` | clean (0 hits) |
| The full regression gate through the pre-commit hook | passed: the commit exists only if it passed |

Verified: all of the above, and the golden hashes (computed from the template at ce86512 before any edit, and re-checked
by test (b) against `git show ce86512:...` in the worktree). Expected, untested: a real run with `cause_in_prompt: false`
(sr-pack-4a's launch exercises it).

Every check ran with TEMP and TMP set to the gittoken `.tmp-gate` folder on drive C.

## Notes for the lead

- A pack that hides the cause must also keep it out of `cases.fix.instructions`, `findings[].summary` and
  `findings[].required_behaviour`, which the fix prompt prints verbatim; the template cannot tell a cause restated in
  other words. That is the pack author's (and the pack reviewer's) check for sr-pack-4a.
- The pin and review prompts never printed the cause; this change leaves them as they were.

## What I got wrong and fixed

- My first full suite run (116 tests) failed one test I had not foreseen:
  `SharedPack.test_the_manifest_carries_every_field_of_the_format` requires every field the format README documents to
  be present in the shared pack's manifest, and the new `cases.fix.cause_in_prompt` entry is not (the shared pack must
  not carry it: its prompt and manifest hash stay as they are). Fixed in the test the way run 4's other optional keys
  are: the field is checked on a run 4 shape (`{"fix": {"cause_in_prompt": false}}`) beside `mutants` and `gate`. Then
  the full suite was re-run.
- My first guard run included the whole SharedPack class and was started before that fix, so every guard copy would have
  shown the format test red as noise; I stopped it and re-ran the guards on the fixed test file with the template-facing
  SharedPack tests only.
