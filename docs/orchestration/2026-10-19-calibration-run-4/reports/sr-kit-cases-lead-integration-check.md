# sr-kit-cases, lead integration check (refute-first, fresh context)

Checked: branch `build/sr-kit-cases` at c72419a (the lead integration, `cases.fix.cause_in_prompt`) on ce86512
(re-review 1, ACCEPT). Read against the brief (`briefs/run4-kit-cases-builder.md`), the conventions, the sr-pack-4a
brief (H3, the pack the key is for) and the integration report (`reports/sr-kit-cases-lead-integration.md`).

**Verdict: ACCEPT.** I tried to break each claim. None broke. The cause leaves the candidate prompts when the key is
false, and only the fix prompt changes. With the key absent or true, every agent call and the run result match
ce86512's template byte for byte. Every non-boolean value is refused. The grader keeps the cause. All six guard
proofs reproduce, and five more of my own went red too. No S1-S3. Two new S4s (LC-1, LC-2) and two notes; none blocks.

All renders went through the kit's own stub harness (`run_config` + `execute_template`, node). Guard copies were
`git archive` of c72419a outside the repository, with no history. Every run had TEMP and TMP on the gittoken
`.tmp-gate` folder.

## Claims, attacked

| Claim | How I tried to break it | Result |
|---|---|---|
| `false` keeps the cause out of the candidate's prompt | Fixture and shared manifests, each with and without a gate case. First with the pack's own cause, then with a cause whose every word is unique (`QQcause-...`). I searched every candidate prompt (pin, fix, gate, review) and its schema for the `Cause:` label, the cause, any 3-word fragment of it, and the `QQcause` token. | Clean in every candidate prompt and schema. The only 3-word overlap with a real cause is `a str chunk` in the shared pack's D-2: that phrase is in the pack's own `required_behaviour`, not leaked from the cause. With the unique cause, nothing matched in any prompt. The cause can only reach the prompt through the manifest text the template prints (summary, required behaviour, instructions, subject, commit rule), and the template prints no cause there. |
| `false` changes nothing else | Rendered `false` on the new template and absent on ce86512's template, then compared every call. | Same number of calls. Only `fix:alpha-low` differs. Its prompt equals the old prompt with exactly ` Cause: <cause>.` removed once. Label, phase, schema, model and effort are unchanged, and so is the run result. |
| absent/true is byte-identical to before | Rendered ce86512's `run.template.js` from git and the new one, for absent and explicit `true`. Packs: fixture and shared, each with a review case, with a review case plus a gate case, and with a gate case and no review case (`judging_profile: null`). Host paths: the golden ones and the per-run temporary ones. | Identical in every combination: every call's prompt, label, phase, schema, model and effort, plus the error and the result (JSON compared, 10, 11 or 3 calls). The fix prompt measured 2580 bytes / `5e66cf5f...` (fixture) and 3066 / `54a0353d...` (shared), matching `FIX_PROMPT_GOLDEN`. |
| non-boolean values are refused | `"false"`, `"true"`, `"False"`, 0, 1, 0.0, null, `""`, `[]`, `[false]`, `{}`, `{"value": false}` | Each one refused with `cases.fix.cause_in_prompt must be true or false, not <value>`, before any agent call. |
| a misplaced key is refused | `cases.pin`, `cases.review`, an unknown case `cases.extra`, finding D-2, finding D-1, and the key on both fix and pin | All refused before any agent call. Other placements are accepted silently and the cause still prints (LC-2). |
| graders still see the cause | The grader prompts in the `false` runs | Both `grade:` prompts carry `<summary>. Cause: <cause>.` for D-2 (the fixture's and the shared pack's review findings include it). This holds only for the grader, and only for findings listed in `cases.review.findings` (LC-1). |
| other edge values | `cases.fix: null`, and the cause null with `false` | Both launch. `false` with a missing cause renders a clean fix prompt. Nothing enforces that `findings[].cause` is required (see LC-1). |

## Docs and CHANGELOG

- Kit README: the paragraph matches the behaviour (false removes the whole clause; true or absent leaves the prompt
  unchanged; the three refusals), except for "the lenses read" (LC-1).
- `subject-pack/README.md`: the Isolation sentence and the `cases.fix.cause_in_prompt` entry match. The new
  `findings[].cause` text ("Required: the grader and the lenses read it") is wrong about the lenses (LC-1).
- CHANGELOG: only one existing line changed (numstat 1/1), and it is still the single
  `- **Calibration kit: run 4 case keys**` line. The new clause names neither `tools/calibration/` nor
  `check_calibration_evidence.py`. So both one-line rules hold: the kit test's single Unreleased line naming the kit
  path, and the evidence check test `test_one_changelog_line_names_the_check_and_the_table`. Both test files pass.
- The commit message has the five parts. It names the model only in the trailer. The changed files contain no host
  paths or session or run ids (grep).

## Guard-removal proofs (re-run)

Each guard ran in its own scratch copy on the 24 tests the report names (FixCauseInPrompt, RunTemplate,
KitCaseTemplate, KitCaseDocs, SharedPack's format test, launch test and refusals test). Control copy: 24 OK.

| Guard | Red |
|---|---|
| G1 non-boolean refusal removed | test_a_non_boolean_value_is_refused |
| G2 other-case refusal removed | test_the_key_outside_the_fix_case_is_refused |
| G3 finding refusal removed | test_the_key_outside_the_fix_case_is_refused |
| G4 cause always printed | test_false_leaves_out_the_cause_and_keeps_the_summary_and_required_behaviour |
| G5 default flipped (cause only on explicit true) | test_absent_or_true_..., SharedPack.test_the_workflow_template_launches_on_this_pack |
| G6 the clause's final period dropped | test_absent_or_true_... |
| G7 (mine) `!FIX_CAUSE` in place of `=== false` (absent hides) | test_absent_or_true_..., SharedPack.test_the_workflow_template_launches_on_this_pack |
| G8 (mine) truthText drops the cause when the key is false | test_false_leaves_out_... (the grader assertion) |
| G9 (mine) the refusal lets the string `"false"` through | test_a_non_boolean_value_is_refused |
| G10 (mine) the CHANGELOG clause removed | KitCaseDocs.test_k6_one_changelog_line |
| G11 (mine) the format README's `cases.fix.cause_in_prompt` entry removed | SharedPack.test_the_manifest_carries_every_field_of_the_format (Note N-2) |

G1-G6 reproduce the report's table exactly.

## Checks

| Check | Result |
|---|---|
| `python tools/test_calibration_kit.py` at c72419a | 116 tests OK, 1 skipped (876 s) |
| `python -m unittest tools/test_check_calibration_evidence.py` | 51 tests OK |
| `python tools/check_calibration_evidence.py` | 3 folders, 0 failures, 14 limitations |
| `python tools/qualification_table.py --check` | exit 0 |
| `python tools/check_secrets.py` | clean (0 hits) |
| Diff ce86512..c72419a | six files: CHANGELOG.md, the integration report, the kit README, `run.template.js`, `subject-pack/README.md`, `tools/test_calibration_kit.py`. All are within the brief's permitted set. |

## Findings

**LC-1 (S4): the docs say the lenses read the cause; they never do, and the grader reads it only for review
findings.** `lensPrompt` fills `lens.prompt.md`, which has no ground-truth placeholder. A lens sees only the cluster's
claim, title and members, never `findings[].cause`. `truthText` is built from `cases.review.findings` only. sr-pack-4a
is `fix@T3` alone, with no review case. In that pack no agent reads the cause at all: the fix cell is graded by
`grade.sh`, which does not read it. The wrong wording is in three places: the kit README ("stays in the ground truth
the grader and the lenses read"), `subject-pack/README.md` `findings[].cause` ("Required: the grader and the lenses
read it"), and the integration report. The word "Required" is also enforced nowhere (a null cause launches). Fix: say
"the grader reads it when the finding is one of `cases.review.findings`", and drop "the lenses". The behaviour is
correct; only the docs overstate it.

**LC-2 (S4): a misplaced `false` outside `cases.<case>` and `findings[]` is silently ignored.** These are accepted
and the fix prompt still prints the cause:
- `cause_in_prompt` at the manifest's top level, on `subject` or on `paths`;
- `cases.cause_in_prompt: false`: the case loop skips it because its value is not an object;
- typo keys on `cases.fix` (`cause_in_prompts`, `Cause_in_prompt`).

The report argues for refusing this key wherever it is misplaced, because the cause stays in the prompt while the
author believes it hidden. The same argument covers these placements. The documented scope ("on any other case or on
a finding") is accurate, so this is S4. Cheap fix if wanted: also refuse the key at the manifest's top level and as a
`cases` entry. Otherwise, the sr-pack-4a reviewer checks that the key sits on `cases.fix`.

## Notes

- **N-1 (sr-pack-4a).** The sr-pack-4a brief (H3) asks for "`summary` and `cause` written for the grader only". The
  key hides the cause, but the fix prompt still prints `summary`, `required_behaviour` and `cases.fix.instructions`
  verbatim. The integration report's note for the lead already says this. The pack author must keep the summary free
  of the cause.
- **N-2.** `KitCaseDocs.test_k6_the_format_readme_documents_the_new_manifest_keys` would stay green with the format
  README's `cases.fix.cause_in_prompt` entry removed (G11), because the key is still named in the Isolation sentence
  and in `findings[].cause`. SharedPack's format test catches that removal instead, so the entry is guarded.

## What I got wrong and fixed

- My first probe rendered packs with a gate case using the default stub outputs, which have no gate output. Those
  runs failed with `"undefined" is not valid JSON` after the gate call, in both templates, so they proved nothing. I
  re-ran them with the kit's `gate_canned()`: all 12 combinations matched.
- My first 3-word fragment search flagged `a str chunk` in the shared pack. I traced it to the pack's own
  `required_behaviour`, not to a leak. The unique-word cause settles the question.
