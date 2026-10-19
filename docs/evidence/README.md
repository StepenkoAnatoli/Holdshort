# Evidence

Each dated folder here (`docs/evidence/<date>/<name>/`) is the committed record of one measurement: its frozen
protocol, its observations and its scores. A folder is evidence: never edit a file in it, except for the run's own
amendments appended to its protocol. The tools below read the folders and never change them.

Two files sit beside the dated folders: this README, and `qualification-table.md`, which a tool generates.

## Calibration evidence check

`tools/check_calibration_evidence.py` (docs/proposals/calibration-first-onboarding.md Item 4.3) refuses a calibration
results folder whose evidence does not carry the intended rule. The regression gate runs it on every commit over every
`docs/evidence/*/claude-code-calibration*/` and `docs/evidence/*/*-calibration-*/` folder:

```bash
python3 tools/check_calibration_evidence.py                       # every calibration folder
python3 tools/check_calibration_evidence.py docs/evidence/<date>/<host>-calibration-<n>
```

It prints one line per failure, `FAIL <folder> <rule>: <text>`, one per limitation, `LIMIT <folder> <rule>: <text>`,
and a summary line. It exits 1 when any folder fails. A folder with limitations and no failures passes: a limitation
says what the folder cannot answer, and it is never counted as a pass of that rule. A value of the wrong shape (a
string where a cell object belongs, a list where the classification belongs) is a `FAIL` under the rule that reads
it, never a traceback. The check's tests put a value of each other kind, a number, a boolean and null among them, in
place of each object and list of the passing fixture and runs 1 and 3 (one profile of each shape, two items of each
list), and the table renders each folder the check still accepts.

**Two kinds of run.** A *kit run* is a folder whose `protocol.json` carries the calibration kit's keys
(`classification.prongs`, `judging_profile`, `relayed_operator_text`) at the kit template's `schema_version` or later.
Every rule applies to it in full. A *legacy run* carries none of them: calibration runs 1-3 predate the kit. The check
applies what such a folder can answer and records the rest as a limitation. A legacy run is refused only for an
internal contradiction, such as a score its observations do not give, or a flag that disagrees with its own schema.

| Rule | A kit run must carry | A legacy run (runs 1-3) |
|---|---|---|
| `protocol-frozen` | `status` one of the template's two values exactly (`frozen`, or its `run complete; ...` line after the run), `run_id`, `frozen_at`, `schema_version` at or above the template's, no `{{placeholder}}` left, and the same run id in `scores.json`; across the folders checked, no other folder with its run id or its host and run number | a `run_id` that `scores.json` repeats; across the folders checked, as for a kit run |
| `prongs-declared` | the protocol's `classification.prongs` equal the prongs every lens record in `adjudication.json` carries, and `scores.json` `adjudication_schema` states both sets as they are | run 3: `adjudication_schema` declares both sets and the missing prong, consistent with `adjudication.json` and its lens records; a missing prong is a LIMIT. Runs 1-2: no adjudication record, a LIMIT |
| `scores-derivable` | every pin, fix and review score in `scores.json` is what `observations.json` gives through the kit's own `observations.py` functions, with each review's clusters judged real under the declared prongs | each folder's own pass rules (`protocol.json` `cases[].pass_rule`, recognised by their SHA-256) applied to the observations' fields; run 3's review uses its lens records' votes; a rule text the check does not encode, a case stated twice, a scored case with no encoded rule behind it, and an `adjudication_schema` declared beside a review rule that does not apply it (runs 1-2's) are refused |
| `fewer-prong-pass-flagged` | a review PASS that holds only because a prong is missing from the declared set carries `would_fail_under_three_prong: true`; no flag sits on a cell that passes on all three prongs or is not a PASS; and the review pass count in `totals.cells` excludes the flagged PASSes or states the count without them | run 3: its flags are checked (on PASSes only, each with a blocking finding in a cluster real by its lens rule) together with its stated count; the reading behind them is a LIMIT, because the lens records carry no `forbidden` field. Runs 1-2: every review PASS is `unadjudicated`, a LIMIT |
| `pin-category-mapping` | `scores.json` `category_mapping.pin` is `pin-tests` (the host's rule 4; the protocol's label is not the mapping) | run 3 as a kit run; runs 1-2 record no mapping, a LIMIT naming the protocol's label |
| `judging-profile-named` | `judging_profile` with its key, model, effort and its qualification, or the bootstrap line `judging profile not independently qualified, ...` (a LIMIT, and a caveat in the table) | a LIMIT naming the grader that `protocol.json` `cases[review].grading` names |
| `relayed-chat-statement` | `relayed_operator_text.text` is the verbatim relayed text or `null`, and `statement` says what the harness relays | a LIMIT: run 3 recorded the relayed text after the run (amendment A-1); runs 1-2 did not record it |
| `no-secrets-or-bodies` | no file matches `tools/check_secrets.py`'s patterns; no `*.prompt*`, `journal.jsonl` or `transcript*` file is present | the same |

What the check cannot see:

- Whether the run id was recorded *before* the launch. The folder records a run id and a freeze time, not the order of
  the two; the git history of the freeze commit does.
- Pass counts stated in prose (a README, `results-table.md`). The check reads only the counts in `scores.json`.
- Whether every grade entry in a host policy is in the adapter's form (Item 4.3). That is a property of the policy,
  which the adapter's policy validator checks, not of an evidence folder.

The synthetic folders under `tests/fixtures/calibration-evidence/` show each rule failing on its own. They are built
from the kit's fixture journal by `tools/test_check_calibration_evidence.py --write-fixtures`.

## Qualification table

`qualification-table.md` (Item 4.4) is generated by `tools/qualification_table.py` from every folder the check
accepts. The tool runs the check first, and writes nothing when the check fails. The gate runs
`python3 tools/qualification_table.py --check`, which fails when the committed table differs from the generated one.
A results pull request therefore regenerates the table and commits it in the same change.

For each host, the table has one row per profile and category. Each row gives the profile's model, effort and config
as the run's protocol names them, the grade per run in run order (each run headed by its folder's run number,
`<host>-calibration-<n>`), the adjudication schema and prongs each run's
review grade rests on, and the caveats. A caveated PASS is shown and not counted:

- `PASS (2-prong, would fail)`: a review PASS that holds only because the lens schema lacked a prong (run 3's
  `haiku-medium` and `haiku-high` review cells).
- `PASS (unadjudicated)`: a review PASS from a run with no adjudication record (runs 1-2).
- `PASS (supplementary)`: a cell graded in a supplementary run that replaced a void cell (run 3's `fix:haiku-high`
  and `review:haiku-low`). These cells are not counted either, because every caveated PASS is excluded from the count.
- `void`: a void cell with no replacement.
- `PASS (judge not qualified)`: a review PASS judged under the bootstrap limitation.

What the table supports: per host, profile and category, which runs graded the cell and how; how many of those PASSes
carry no caveat; and what each review grade rests on. It is the evidence a host's qualification rules read. What it
does not support, as its header states:

- No ordering between models: no row ranks a model, an effort or a profile above another, however the counts compare.
- No cross-host comparison outside the shared pack's cells: a host pack is graded on that host's own code.
- No claim about tiers it did not run: runs 1-3 record no tier.
- No qualification: the host's rules qualify a profile for a category; the table grants nothing.
