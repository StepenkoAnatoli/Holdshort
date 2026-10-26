# Unit sr-kit-cases: a category on calibration task objects, mutants for a pin case, and a gate-graded case kind

Worktree and branch: created by the lead from Holdshort `main` (the kit, #106-#108 merged; the launch prompt names
the head). Work only under `tools/calibration/` (`grade.sh`, `observations.py`, `run.template.js`, `README.md`,
`subject-pack/README.md`), `tools/test_calibration_kit.py`, `tests/fixtures/calibration/`, `CHANGELOG.md`, your report
file under `docs/orchestration/2026-10-19-calibration-run-4/reports/`. The regression gate runs on every commit through
the hook; never --no-verify; no push. Conventions: `briefs/conventions.md` (beside this brief).

## Why

Host-policy-6 (E6) left `build-core`, `build-tests`, `research-collect` and `docs-mechanical` without a delegate
until a host-pack cell qualifies one. The kit keys cases `pin | fix | review` and `observations.json`'s task objects
carry no category; the adapter maps them by position. The run 4 plan (`briefs/run4-plan.md`, R4-4) needs: a
`build-core` cell that is fix-shaped, a `build-tests` cell that is pin-shaped against several mutants, and two cells
graded by a command. The evidence check (#108, rule e `pin-category-mapping`) reads the category mapping from
`scores.json`; it must keep passing on the three real folders.

## The lead's decisions

K1. **`category` on the task object.** `observations.py` writes `"category": <manifest cases.<case>.category>` into
    each `pin`, `fix` and `gate` task object and into `review` when present; absent in the manifest, the fixed
    mapping (`pin-tests`, `fix`, `review`) as today, so runs 1-3's folders rebuild byte-identically (test it on the
    fixture folder: the output with no category keys equals today's).
K2. **`mutants` on a pin case.** `cases.pin.mutants`: optional list of `{id, commit}`; `grade.sh pin` then requires
    the candidate's new tests red at every mutant commit's source (each swapped in turn, the mtime step kept) as well
    as at the base, and green with the accepted source; the grade carries `redAtMutants: {id: bool}`. No mutants:
    today's behaviour byte for byte.
K3. **A `gate` case kind.** `cases.gate`: `{base, category, tier, pass_rule, instructions, commands: {gate,
    timeout_seconds}, invariants: [paths], required_paths: [paths]}`. The candidate's prompt is the manifest's
    `instructions` plus the common preamble (relayed-text reconciliation, the checkout, the commit command); the
    cell passes when `commands.gate` exits 0 in the candidate's checkout, every `invariants` path hashes as at the
    base, every `required_paths` path exists, and the candidate committed. `grade.sh gate` grades it; the grade
    carries `gateExit`, `invariantsIntact: {path: bool}`, `requiredPresent: {path: bool}`, `committed`.
    `run.template.js` runs `gate` items like `pin` and `fix` (no grader agent); `observations.py` counts them in
    `scores.json` (`cells.gate`, `category_mapping.gate`). One case per kind per pack stays the rule.
K4. **A run with no review case may leave `judging_profile` null.** The launch step accepts `judging_profile: null`
    only when `cases.review` is absent; with a review case the current refusal stands.
K5. **Tests, red-first with guard proofs:** K1 on the fixture folder (identity without categories; a category
    present when the manifest carries one); K2 with a fixture mutant commit (a test that catches the base defect but
    not the mutant grades FAIL; one that catches both PASS); K3 with a fixture gate case (exit 0 and intact
    invariants PASS; a changed invariant FAIL; a missing required path FAIL; exit 1 FAIL); K4 both branches of the
    launch refusal under the stub harness. `python tools/check_calibration_evidence.py` and
    `python tools/qualification_table.py --check` stay green (#108 is merged).
K6. **Docs.** The kit README (the three keys, one paragraph each), the pack-format README (the new manifest keys),
    one CHANGELOG line. Note for the adapter: the task object's `category` is what `rate` will read (host-policy-7).

## Deliverables and stop triggers

A. K1-K4 in the kit files. B. Tests per K5. C. Docs per K6. D. Gate green through the hook on every commit. Stop and
report if K3 cannot be expressed without a second case per kind or a change to the evidence check (name the change).
