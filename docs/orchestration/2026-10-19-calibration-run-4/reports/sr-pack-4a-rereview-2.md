# sr-pack-4a, re-review 2: refute-first re-review of the host pack moonaliza-x2-1 after fix round 2

Verdict: **FIX**, and only because F2 (S2) is still open. F2 needs the lead, not another fix round of this unit.
Reviewed `build/sr-pack-4a` at b1af660 (fix round 2, on top of re-review 1 at 12d3e3e; base main 0a6d341) against the
brief `run4-pack-4a-builder.md` (H1-H5), `conventions.md`, `run4-plan.md`, the request `sr-pack-4a.json`, re-review 1
(`sr-pack-4a-rereview-1.md`) and the fix report (`sr-pack-4a-fix-2.md`). Fresh context; I wrote none of the change. This
report is the only file this round adds.

Re-review 1's R1 (S3), R2 and R4 are fixed. I re-ran each proof and each guard removal and got the fix report's
numbers. Nothing the fix added is S1-S3. One new S4 (RR2-1) is the part of R4 the fix did not reach.

## Findings

| id | severity | status | finding |
|---|---|---|---|
| F2 | S2 | **open, lead decision** | The kit's fix prompt still shows the candidate the cause: `tools/calibration/run.template.js:159` on this branch and on origin/main (0a6d341), and `:174` on `build/sr-kit-cases` (ce86512, draft PR #120), all read `Cause: ${f.cause}`. The lead's RUN.md (run folder, last entry 2026-10-25) records no decision. One new fact for that decision is below |
| R1 | S3 | fixed | The signed-out orphan row catches W-m (verified, below) |
| R2 | S4 | fixed | The later starts move `Date` ten years. Age limits of 31 and 365 days are caught (verified) |
| R4 | S4 | fixed, residue RR2-1 | A comment line that mentions either anchor no longer moves the slice (verified) |
| R3 | S4 | open, goes with F2 | The `instructions` sentence about the startup lines. Unchanged |
| F4 | S4 | open, ratification | `--testTimeout=60000` in `commands.test`. Unchanged |
| F5 | S4 | open, owner | The clone's `node_modules/.vite` and `.vite-temp` (2026-10-24 21:33 and 21:43 +0300) are unchanged. This round wrote nothing to the clone |
| F6 | S4 | open, ratification | K3's MoonAliza-name rule stops at `subject-pack/host/`. Unchanged |
| RR2-1 | S4 | **new** | Two shapes of a correct fix still make `wiring()` slice the startup lines wrongly. Each fails 17 of 18 rows with `Transform failed` |

### F2 (S2): one new fact for the lead

For a fix-only pack such as this one, the candidate's prompt is the only thing that reads `cause`. Line 159 reads it for
the fix prompt. Line 176 reads it only for `cases.review.findings`, and this pack has no review case. Neither `grade.sh`
nor `observations.py` reads it (`grep` over `tools/calibration`, outside the host packs). So rewording `cause`, or
leaving only a pointer in it ("not shown: the grader text is in the README"), would remove the leak and lose nothing the
grading uses. But H3 asks for a `cause` that names the reconcile's deletion, so the choice is still the lead's. The
options are unchanged: a kit unit that drops `cause` from the fix prompt or puts it behind a manifest flag, a recorded
decision to reword this manifest's `cause`, or a recorded decision to accept the tier with the cause shown. Stage 4a
should not launch as briefed until one of them is recorded.

### RR2-1 (S4): the start anchor still assumes a one-line engine call with no bare block comment above it

`from` is the first code line that matches `method:\s*['"]vault\.references['"]`, and the slice starts on the next line.
Two candidate edits that leave the behaviour correct still break that slice:

1. **The engine call wrapped across lines**, for example
   `const references = z.array(z.string()).parse(` / `await engine.control({ method: 'vault.references' }),` / `);`.
   `from` lands on the middle line, so the slice starts with `);`. Result: the accepted fix with this change fails
   17 of 18 rows (`Transform failed`). This was true before fix round 2 as well (the old anchor matched the same line).
2. **A `/* ... */` comment whose inner line does not start with `*`** and mentions `method: 'vault.references'`, placed
   above the engine call. `isCode` sees only a line's first characters, so the inner line counts as code. Result:
   17 of 18 rows failed (`Transform failed`).

Neither shape is likely. The subject has no formatter and no `max-len` rule (its `package.json` and `eslint.config.mjs`),
so nothing forces the wrap, and the instructions say the slice starts after "the line that reads the engine's
references". But a correct fix graded FAIL biases the measurement against that candidate. Cheap remedy: move `from` to
the first line at or after the match that ends with `;`, and keep the open/closed state of a `/* */` comment in
`isCode`. This finding does not block on its own.

## Re-run proofs

Probes ran on a scratch copy of MoonAliza 16f637f's tree, taken with `git archive` (a read on the clone). Its
`node_modules` was a symlink to a directory of symlinks to the clone's entries (the kit's `x21_shell_modules`, so
without `.vite` and `.vite-temp`). Each candidate was applied with the kit's own `x21_edit` and the `X21_*` edits
(imported from `tools/test_calibration_kit.py`). The journey test, or a scratch variant of it, was run with
`npx vitest run tests/zz_accepted_x2_1.test.ts --testTimeout=60000 --reporter=json`.

| candidate | journey test at b1af660 | fix report 2 |
|---|---|---|
| base (16f637f) | 12 of 18 failed: every journey row, at the pair-state check after the unread start (`[undefined, undefined]` against `['staged','staged']`; `['committed', undefined]` for refresh before commit 4). The 6 other rows pass | 12 of 18 |
| accepted (01a8604's three source files) | 0 of 18 failed | 0 |
| `X21_ALTERNATIVE` / `X21_ALTERNATIVE_HELPER` | 0 of 18 failed each | 0 each |
| W-m: keep when unread or the file names no account (R1) | 1 of 18 failed: the signed-out orphan row (`expected { (2) } to deeply equal {}`) | 1 |
| W-n: keep while less than 365 days old (R2) | 12 of 18 failed: every journey row | 12 |
| W-n with 31 days (R2) | 12 of 18 failed: every journey row | 12 |
| the accepted fix plus a `//` comment above the engine call naming `method: 'vault.references'` and `supervisor.attach()`, and one between the anchors naming both (R4) | 0 of 18 failed | 0 |
| **new:** the accepted fix with the engine call wrapped over three lines (RR2-1) | **17 of 18 failed**, `Transform failed` | (new probe) |
| **new:** the accepted fix with a bare `/* */` comment above the engine call (RR2-1) | **17 of 18 failed**, `Transform failed` | (new probe) |
| **new:** W-o, keep when unread or the file was read and refused (corrupt; `this.unread \|\| this.startupWrite`) | 1 of 18 failed: the app-changed row. Caught | (new probe) |

Guard removals (scratch variants of the journey test):

| guard removed | result | fix report 2 |
|---|---|---|
| the signed-out orphan row deleted | W-m: 0 of 17 failed | 0 of 17 |
| `later(3650)` set back to `later(30)` | W-n (365 days): 0 of 18 failed. W-n with 31 days: 0 of 18 | 0 of 18 |
| the anchors set back to the first line matching `vault\.references` / `supervisor\.attach\(`, with no code-line filter | the commented accepted fix: 17 of 18 failed, `Transform failed` (the vault-default row, which runs no start, passes) | 17 of 18 |

## Other attacks (checked, not findings)

- A store that re-reads the file through an API the test does not fail (callback `fs.readFile`, a stream) would read
  the account during the "unreadable" start. The row's `expect(unread.store.current()).toBeNull()` fails it. Considered,
  not run.
- An age limit taken from the encrypted file's mtime is caught too: the vault's `Date.now()` is faked ten years on, so
  the age it computes is ten years. Only a clock vitest does not fake (`performance`, `process.hrtime`) would get past
  it. Considered, not run.
- The new row cannot fail a correct fix: its start reads a file, so no correct fix sets the keep flag, and the base
  reconcile deletes the orphan pair (the row passes at the base).
- WRONG-FIXES.md has 16 rows, matching the CHANGELOG's "sixteen", the `X21_WRONG` keys and the counts out of 18.
  `required_behaviour` already covers a signed-out file ("deleted by the next start that reads the file"), so the
  candidate-facing text did not need to change.

## Checks

| check | result |
|---|---|
| `python tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (TEMP and TMP on drive C) | untested in this round: the run started, but this session had to return before it passed `test_every_wrong_fix_grades_fail_on_the_accepted_journey_test_alone` (about 33 minutes). Fix report 2 states 12 OK in 2030 s. My own probes above cover W-m, W-n, base, accepted and both alternatives on the journey test, but not through `grade.sh` |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py HostPackX21 Docs Hygiene` without the clone | 25 tests OK, 6 skipped with the UNSUPPORTED reason (verified) |
| `python tools/check_secrets.py` | clean, 0 hits (verified) |
| Hygiene scan of every line the branch adds (absolute paths, session or run ids, UUIDs, key shapes, model names) | none. The two hits were the regex `method:\s` matching the drive-letter pattern (verified) |
| Changed files against `sr-pack-4a.json`'s permitted effects | all within them: the pack directory, `tools/test_calibration_kit.py`, `tools/calibration/subject-pack/README.md`, `CHANGELOG.md`, the reports (verified) |
| Commit b1af660: identity, trailer, five-part report | `StepenkoAnatoli <318295322+…@users.noreply.github.com>`, the `Co-Authored-By` trailer, all five parts (verified) |
| The MoonAliza clone | `git status` clean. The `.vite` and `.vite-temp` timestamps are unchanged. Probes reached `node_modules` only through the symlink shell, and the clone was only read (`git archive`, `git show`) (verified) |
| F2 on the branches | `Cause: ${f.cause}` in the fix prompt at `run.template.js:159` (this branch and origin/main 0a6d341) and `:174` (`build/sr-kit-cases` ce86512) (verified) |
| The regression gate through the pre-commit hook on this report's commit | not run: this session had to return before the 36-50 minute commit could finish, so the report is uncommitted in the worktree |

## For the lead

1. F2: record a decision (the three options above). R3 goes with it. As things stand, the unit cannot reach ACCEPT through
   another fix round, because every S3 and below that it can fix is fixed. The block is F2 alone.
2. RR2-1 (S4, optional): end-of-statement and block-comment handling for the `from` anchor. Do it in the same round as
   anything else that touches the pack, or leave it disclosed.
3. F4, F5, F6: unchanged ratifications or owner actions.

## What I got wrong and fixed

- My first variant-building script used plain Python strings holding regex escapes (`\s`, `\.`). It printed
  SyntaxWarnings, but the strings were kept literally, and its assertions confirmed every replacement before any run.
  Nothing to correct.
