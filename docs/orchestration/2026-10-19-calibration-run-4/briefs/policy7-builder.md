# Unit sr-policy-7: host-policy-7, the adapter reads a calibration task object's category and the gate task

Worktree and branch: created by the lead from the SmartRouter branch carrying `sr-kit-cases` (the launch prompt names
it). The live adapter is SmartRouter's `hosts/claude-code/` (since 2026-10-19; MoonAliza's
`docs/orchestration/smartrouter/` copy is no longer where SmartRouter's runs are recorded). Work only under
`hosts/claude-code/` (`route.mjs`, `route.test.mjs`, `host-policy.json`, `README.md`,
`trace/policies/host-policy-6.json` as the fixture that freezes revision 6), your report file under
`docs/orchestration/2026-10-19-calibration-run-4/reports/`. Conventions: `briefs/conventions.md` (beside this brief).
Checks: `node --test hosts/claude-code/route.test.mjs`, `node --check hosts/claude-code/route.mjs`,
`python tools/test_claude_code_host_artifacts.py`, `python tools/test_conform_spec.py`, and the full gate through the
hook. No push.

## Why

The kit unit `sr-kit-cases` (K1, K3) writes `category` into each calibration task object and adds a `gate` task.
`rate` maps tasks to categories by position (`CALIBRATION_TASKS`): a `build-core` cell would print as `fix`, and a
`gate` cell would not be counted. Run 4's T1 cells (`briefs/run4-plan.md`, R4-4..R4-6) need both read.

## The lead's decisions

G1. **Freeze revision 6**: copy the live policy to `trace/policies/host-policy-6.json`; the revision-6 table test
    pins to the fixture, the live table test moves to revision 7 (as every revision did).
G2. **`rate` reads `category`.** For each task object (`pin`, `fix`, `review`, `gate`) a string `category` that is
    one of the policy's categories counts the grade under that category; absent, the positional mapping as today
    (runs 1-3 print unchanged: assert byte-equal `rate` output on the committed trace); a category the policy does
    not define, or a non-string, refuses the run (exit 4, the message naming the observation and key), never a
    silent fallback. A `gate` task object is read like `pin` and `fix` (`score` true/false/null, `tier`, `category`
    required: a gate with no category refuses).
G3. **The grade entry line** `calibration-<n>: <category>[@T<k>] PASS|PARTIAL|FAIL (n=<k>)` is unchanged; a policy
    may now cite `calibration-5: build-core PASS (n=1)`. E2 (typed evidence) is unchanged: a PASS grade entry at the
    tier supports a `qualified-for` entry.
G4. **No routing change.** Host-policy-7 is revision 6 plus the key `"policy-revision": "host-policy-7"` and the
    README section; every `decide` assertion of the revision-6 table holds on revision 7 (assert it). The policy's
    `smartrouter.revision` binding moves from `fbe7bca` to the SmartRouter main commit the unit starts from (recorded
    for this revision on 2026-10-19); if a check pins the old value, move it too and say so in the report.
G5. **Tests**: G2's four branches (positional fallback byte-equal; a category counted; an unknown category refused;
    a gate without category refused), G1's fixture pinning, G4; guard proofs for each. README: a "Calibration task
    categories (host-policy-7)" section, the applied decisions G1-G6, friction items if any.
G6. **README head.** The first paragraph says the adapter is live here, in SmartRouter `hosts/claude-code/`, for
    SmartRouter's own runs (its ledger and trace beside it, the run folders under `docs/orchestration/`), and that
    MoonAliza is the subject of the host packs, read from a clone, not where the adapter runs.

## Deliverables and stop triggers

A. route.mjs per G2-G3. B. Policy per G4, fixture per G1. C. Tests per G5. D. README per G5-G6. Stop and report if a
committed trace observation carries a category the policy does not define (none should).
