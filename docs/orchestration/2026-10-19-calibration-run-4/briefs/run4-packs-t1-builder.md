# Unit sr-packs-t1: four T1 host packs (build-core, build-tests, research-collect, docs-mechanical)

Worktree and branch: created by the lead from the SmartRouter branch carrying `sr-kit-cases` (the launch prompt names
it). Work only under `tools/calibration/subject-pack/host/moonaliza-t1-*/` (four packs), `tools/test_calibration_kit.py`
(one class per pack), `tools/calibration/subject-pack/README.md` (one paragraph), `CHANGELOG.md`, your report file
under `docs/orchestration/2026-10-19-calibration-run-4/reports/`. Conventions: `briefs/conventions.md`.
The subject code is MoonAliza's (`build/github-sign-in`, read only; the launch prompt names the clone); as for `sr-pack-4a`,
a pack carries no MoonAliza code: `make-repo.sh <moonaliza-clone> <target>` exports the named trees as root commits
with deterministic ids, and the clone-dependent tests report UNSUPPORTED without `MOONALIZA_CLONE`. Conventions as
in `briefs/run4-pack-4a-builder.md`; wrong-answer matrix first for every pack (M1 below).

## The lead's decisions (R4-5 of `briefs/run4-plan.md`)

M1. **Each pack starts with its wrong-answer matrix**, committed as `WRONG-ANSWERS.md`, every row shown FAIL by the
    pack's grade, before the accepted test or checker is final.
M2. **`moonaliza-t1-build-core`**, fix-shaped, `cases.fix.category: build-core`, `tier: T1`. Subject U2-R7
    (`18a6d21`): base `18a6d21^`, accepted `18a6d21`. The candidate's task: implement the stated rule "a clear whose
    tombstone persist and every file write failed returns 'not-durable' and removes no file, so the next start can
    commit the staged pair the account file still names" in `src/main/github-account-store.ts`, red-first in
    `tests/github-account-store.test.ts`, the map sentence updated. T1: one source file, one test file, the rule
    named, the existing harness. Accepted pin: the two U2-R7 rows at `18a6d21`. Wrong answers: return 'not-durable'
    but still unlink; unlink after the retry only when the file write failed but the tombstone persisted; keep files
    on every clear (the durable case must still remove).
M3. **`moonaliza-t1-build-tests`**, pin-shaped with mutants, `cases.pin.category: build-tests`, `tier: T1`. Subject
    `src/main/github-oauth.ts` at `01a8604` (base = accepted = that tree). The candidate's task: a new test file
    covering three stated rules of the wire module (choose three rules spec 3.5 and 3.9 state and the shipped tests
    already pin, so the subject is known good: e.g. the 64 KiB body bound, a non-JSON 2xx body is a failure result,
    a redirect is not followed), green at head. Three mutants, one per rule, each a commit exported by
    `make-repo.sh` from a patch the pack carries (the patch removes that rule's guard only). Pass: green at head and
    red at every mutant, no source change, eslint clean. Wrong answers: a file that pins two of the three rules; a
    file that passes at every mutant (asserts nothing); a file that edits the source.
M4. **`moonaliza-t1-research-collect`**, gate-graded, `cases.gate.category: research-collect`, `tier: T1`. Subject
    `docs/research/2026-10-03-electron-fuses` (6 pages, 7 unknowns). Base tree: the project with `research/BRIEF.md`
    removed, every DISCOVERY unknown reset to OPEN and every EVIDENCE `Finding` cell reset to its auto-extracted text
    (derive the base from the accepted by a script the pack carries, so the lead can check it). Accepted: the
    committed project. Task: close every unknown from the cached corpus with quoted claims, pass preflight, write the
    brief; collection is refused on this machine, and that is the point (nothing is spent). Gate command:
    `node research-kit/bin/preflight.mjs && node research-kit/bin/handoff.mjs` in the project directory (the kit path
    as MoonAliza vendors it; say which). Invariants: `research/raw/.fetches.jsonl` and every file under
    `research/raw/`. Required: `research/BRIEF.md` with the sections the kit names (a checker the pack ships verifies
    them and the `Reviewed by: agent` line). Wrong answers: a brief with the sections empty; a closure that edits a
    capture (the ledger check fails: show it); a CLOSED unknown with no quote (preflight warns or fails under the
    policy: show which).
M5. **`moonaliza-t1-docs-mechanical`**, gate-graded, `cases.gate.category: docs-mechanical`, `tier: T1`. Subject: the
    five-part commit report of `18a6d21` written to `reports/u2-r7-report.md` from the commit's diff and the test
    log the pack ships (not from the commit message: the base tree's git log is one root commit without it). The
    checker (`check-report.py`, shipped) verifies: the five named parts present in order; every claim under "what you
    verified" carries exactly one of verified/untested/expected; the got-wrong part present (text or "nothing to
    report"); the files named equal the diff's files; the test counts equal the log's. Invariants: everything but the
    report path. Wrong answers: four parts; "the suite passes" without a status word; a file list with a file the
    diff does not touch.
M6. **Tests** per pack: deterministic ids; the accepted answer PASS and every WRONG-ANSWERS row FAIL through
    `grade.sh` (fix, pin with mutants, gate); the filled template launches under the stub harness with that pack and
    a protocol whose only case is the pack's. Without the clone: hygiene, shapes, hashes.
M7. **Docs**: each pack's README (what the cell measures, what it does not); one paragraph in the pack-format README;
    one CHANGELOG line.

## Deliverables and stop triggers

A. Four packs per M2-M5 with their matrices (M1). B. Tests per M6. C. Docs per M7. D. Gate green through the hook on
every commit. Stop and report if a pack needs a kit change beyond `sr-kit-cases` (name it) or if a subject's accepted
tree does not pass its own gate on this machine (say which command failed and how).
