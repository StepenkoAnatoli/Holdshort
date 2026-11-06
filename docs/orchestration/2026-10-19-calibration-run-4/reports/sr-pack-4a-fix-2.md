# sr-pack-4a, fix round 2: the findings of re-review 1 on the host pack moonaliza-x2-1

Verdict: DONE. One commit on `build/sr-pack-4a` on top of re-review 1 (12d3e3e), not pushed; the structured return
names the head. R1 (S3) is fixed red-first, and so are the cheap S4 findings R2 and R4. F2 (S2) stays with the lead: it
needs a kit change or a recorded decision, outside this unit's permitted paths. R3 goes with F2 and is unchanged. F4,
F5 and F6 are ratifications or owner actions and change nothing here.

## What changed

| finding | change | files |
|---|---|---|
| R1 (S3) | New row, the **signed-out orphan row**: sign in, sign out (`clear` returns `durable`, the file reads `account: null`), then a sign-in that crashes after staging, before the file write (`afterStaged` at count 4). The readable start that follows must delete the orphan pair: no entries, no `.bin` files, the store and the file signed out. New wrong fix W-m (the keep flag set from an unread file or a file that names no account) in `X21_WRONG` and `WRONG-FIXES.md`, measured 1 of 18 | `zz_accepted_x2_1.test.ts`, `WRONG-FIXES.md`, `tools/test_calibration_kit.py` |
| R2 (S4) | The journey rows and the orphan row now move `Date` ten years (`later(3650)`) instead of a month. The store's clock is injected and fixed, so only the vault sees the move. New wrong fix W-n (W-k's idea with a year for the limit), measured 12 of 18. The README's limit now reads "Time limits beyond ten years" | `zz_accepted_x2_1.test.ts`, `WRONG-FIXES.md`, `README.md`, `tools/test_calibration_kit.py` |
| R4 (S4) | `wiring()` anchors on code lines only. `from` is the first code line that matches `method: 'vault.references'` (the engine call). `to` is the first code line after it that matches `supervisor.attach(`. A line that starts with `//`, `/*` or `*` is skipped, so a candidate's comment cannot move either anchor | `zz_accepted_x2_1.test.ts`, `README.md`, `tools/test_calibration_kit.py` |

Consequences: the accepted commit holds the journey test, so `accepted0` is now
`1cf7ceb64fcba4077c5cc8353bf5b91b7837f69c` (it was f39d775b). `base0` is unchanged (09fe935e). The manifest's
`accepted_fix` (in both places) and `source_hashes` follow. `WRONG-FIXES.md` counts out of 18. W-c now also fails the new
row (5 of 18, was 4), and every other count is unchanged. The kit tests expect 18 rows. They check statically that the
signed-out orphan row is present, that both later starts use `later(3650)` and none uses `later(30)`, and that both
anchors are filtered to code lines. The CHANGELOG line now says sixteen wrong fixes. The candidate-facing text
(`required_behaviour`, `instructions`) is unchanged. `required_behaviour` already says "an unreferenced staged entry is
deleted by the next start that reads the file", which covers a file that names no account.

## Red first

Probes ran on a scratch checkout of MoonAliza 16f637f's tree, taken with `git archive` (a read on the clone). Its
`node_modules` was a directory of symlinks to the clone's entries, without `.vite` or `.vite-temp`. Each candidate was
applied with the kit's own `x21_edit` and `X21_*` edits, and the journey test was run with
`npx vitest run tests/zz_accepted_x2_1.test.ts --testTimeout=60000 --reporter=json`.

| candidate | old journey test (ad5138f) | new journey test |
|---|---|---|
| W-m: keep when unread or the file names no account (R1) | **0 of 17 failed** (re-review's probe, reproduced) | 1 of 18 failed: the signed-out orphan row (`expected { (2) } to deeply equal {}`) |
| W-n31 / W-n365: keep while less than 31 / 365 days old (R2) | **0 of 17 failed** each (re-review's probe, reproduced, and a year) | 12 of 18 failed each: every journey row, at the pair-state check after the unread start |
| the accepted change with a comment above the engine call that mentions `vault.references` (R4) | **16 of 17 failed**: `Transform failed` (the slice started at the comment) | 0 of 18 failed |
| the same, plus a comment between the anchors that mentions `supervisor.attach()` | (not run on the old test; the guard below shows it) | 0 of 18 failed |
| base (16f637f) | 12 of 17 failed | 12 of 18 failed: every journey row; the 6 other rows pass (the new row passes at the base, which deletes every unreferenced staged entry) |
| accepted (01a8604's three source files) | 0 of 17 failed | 0 of 18 failed |
| `X21_ALTERNATIVE` / `X21_ALTERNATIVE_HELPER` | 0 of 17 failed | 0 of 18 failed each |

Every wrong fix against the new journey test (one probe each): W-a 12, W-b 1, W-b2 1, W-c 5, W-d 13, W-e 13, W-f 12,
W-g 9, W-h1 1, W-h2 1, W-i 12, W-j 1, W-k 12, W-l 4, W-m 1, W-n 12, each out of 18. These are the counts in
`WRONG-FIXES.md`.

## Guard-removal proofs

Each guard was removed in a scratch copy of the new journey test:

| guard removed | result |
|---|---|
| the signed-out orphan row deleted | W-m: 0 of 17 failed |
| `later(3650)` set back to `later(30)` | W-n365: 0 of 18 failed |
| the anchors set back to the first line matching `vault\.references` and `supervisor\.attach\(`, with no code-line filter | the accepted change with both comments: 17 of 18 failed. With only the comment above: 17 of 18 failed. The vault-default row, which runs no start, passes |

## Checks

| check | result |
|---|---|
| `python tools/test_calibration_kit.py -v HostPackX21` with `MOONALIZA_CLONE` (TEMP and TMP on drive C): every wrong fix through `grade.sh fix`, one at a time, with the count `WRONG-FIXES.md` states; the three correct fixes; make-repo ids and cleanup; the launch refusals | 12 tests OK in 2030 s, exit 0 (verified). Every wrong fix W-a..W-n grades FAIL with candidateGreen, guardRed, scopeOk true and lint ok, and with exactly the `acceptedPin` count of 18 that `WRONG-FIXES.md` states (the test asserts each). The accepted change, `X21_ALTERNATIVE` and `X21_ALTERNATIVE_HELPER` grade PASS. make-repo builds base0 09fe935e… and accepted0 1cf7ceb6…, equal to the manifest, and removes its target on a mismatch. The launch refusals hold |
| `python -W error::SyntaxWarning tools/test_calibration_kit.py HostPackX21 Docs Hygiene` without the clone | 25 tests OK, 6 skipped with the UNSUPPORTED reason (verified) |
| `make-repo.sh` on a scratch copy | base0 09fe935e94d43d787d00268fa2a8e67015891668, accepted0 1cf7ceb64fcba4077c5cc8353bf5b91b7837f69c, exit 0 (verified) |
| `npx eslint` on the journey test and the three source files (helper alternative applied), and `npx tsc --noEmit -p .` on the subject with the new journey test | exit 0 both (verified) |
| `python tools/check_secrets.py` | clean, 0 hits (verified) |
| The MoonAliza clone | `git status` clean. The `node_modules/.vite` and `.vite-temp` timestamps are unchanged (2026-10-24 21:33 and 21:43 +0300). Probes reached `node_modules` only through the symlink shell, and the clone was only read (`git archive`, `git show`, make-repo's `cat-file`/`pack-objects`) (verified) |
| The regression gate through the pre-commit hook | verified by the commit landing (TEMP and TMP on drive C, the host fault named in the launch prompt) |
| Changed files against the permitted effects | the pack directory, `tools/test_calibration_kit.py`, `CHANGELOG.md` (the existing line) and this report, all within `sr-pack-4a.json` (verified) |

## F2, R3, F4, F5, F6: for the lead

- **F2 (S2), open, lead decision.** `tools/calibration/run.template.js` still puts `Cause: ${f.cause}` into the fix
  prompt. The kit file is outside this unit's permitted effects. The options are the same as in fix report 1: a kit unit
  that drops `cause` from the fix prompt or puts it behind a manifest flag, a recorded decision to reword this manifest's
  `cause`, or a recorded decision to accept the tier with the cause shown. Stage 4a should not launch as briefed until one
  of these is recorded.
- **R3 (S4), goes with F2.** The `instructions` sentence about the startup lines stays. It is the price of F1's option
  (b): without it, a correct fix whose wiring uses another name of `index.ts` fails with no warning. If F2 is settled by
  keeping the cause from the candidate, the lead decides whether this sentence stays too. R4 does not change what the
  sentence says.
- **F4, F5, F6 (S4).** Unchanged: the `--testTimeout=60000` ratification, the clone's old `.vite` caches (the owner's to
  delete), and K3's MoonAliza-name rule stopping at `subject-pack/host/`.

## What I got wrong and fixed

- The first R4 edit named its filter `code`, which clashed with the `const { code } = transformSync(...)` further down in
  `wiring()`. I renamed it to `isCode` before any run.
- The first version of the kit-test edit wrote a literal line break into W-n's string, and its regex checks were plain
  strings with backslash escapes (`SyntaxWarning`). I fixed both: `\n` in the string and raw strings for the checks. The
  no-clone run now passes under `-W error::SyntaxWarning`.
