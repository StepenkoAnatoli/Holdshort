# Changelog

New-reviewer guide to **enforcement hardening**, told chronologically: each
protection layer was added because of a real observed failure, and each
entry below names the commit that shipped it. See
[README.md](README.md#enforcing-by-default-the-four-protection-layers)
for the current state of all four layers and
[docs/GO_LIVE_RUNBOOK.md](docs/GO_LIVE_RUNBOOK.md) for the operational use.

All dates 2026; commits hashes as shown (`git log --oneline main`).

## Layer 1 — local pre-commit hook (fail-closed gate, every commit)

This is the layer every clone gets by default; the story starts with the
gate itself and then wires it into the commit path.

- **10-10 `81edfa7`** — Regression gate assembled: one command
  (`tools/run_regression.py`) runs all repo checks in order, fail-fast,
  preserving each subprocess's exit status. Commissioned after the pilot
  tooling (secrets guard, ledger report) made ad-hoc per-file checks
  unmanageable.
- **10-10 `3d6412d`** — **The hook exists because a gate without a trigger
  was observed to be voluntary**: `.githooks/pre-commit` runs the full gate
  on every commit and refuses any commit that fails it. This is the moment
  "run the checks" became "you cannot commit around the checks".
- **10-10 `7282477` / 10-11 `095eb89`** — Machine onboarding
  (`setup_machine.sh`) ends with a *verified* preflight (§0–§2), not just a
  gate proof: a fresh clone self-proves clean-commit-allowed AND
  fake-key-refused before it is called onboarded. Two proof failures were
  real CI bugs and are chronicled below.
- **10-11 `97a7e83`** — Onboarding stopped copying hooks into `.git/hooks`
  and instead wired repo-local `core.hooksPath=.githooks`: per-clone hook
  copies were observed to go stale against the tracked, evolving hook; a
  config pointer cannot. `install_hooks.py` now refuses to install a weaker
  substitute if the tracked hook is missing or unparseable (tested by
  `tools/test_install_hooks.py`, added 10-11 `b72309a`).

## Layer 2 — CI mirror of the gate

For clones where the hook was never wired, and for `--no-verify` bypasses:
same gate, run by GitHub Actions on every push to main and pull request.

- **10-10 `d8db41a`** — CI workflow added mirroring the local gate.
- **10-11 `74d13a5`/`1d4224d`** — The check-run is explicitly named
  `regression-gate`: this was **not cosmetic** — required status checks
  match on context name, and before the rename any protection referencing
  the gate would flake or silently not bind. Kept the runbook-documented
  name authoritative.

## Layer 3 — required status check on `main` + Layer 4 — admin enforcement

Branch protection on `main` requires the `regression-gate` context
before any update lands; a push without a green gate is refused server-side.

- **10-11 `193d1cb`** — Both the required status check (layer 3) and
  `enforce_admins` (layer 4) landed in one protection commit, plus the
  `workflow_dispatch` onboarding proof. `enforce_admins` is what makes the
  required check non-optional for the owner too — no human path lands
  unverified content.

## Strict-mode upgrade — 10-11, via the API (not a commit)

Later the same day, branch protection was upgraded **through
the GitHub API, not by a commit**, to enable **strict** mode: a PR whose
base has moved must re-run `regression-gate` against the updated branch
before it can merge, so the merged tree is always the exact tree a green
gate covered. Read-verified `strict: true` alongside the existing
contexts + admin enforcement.

Why it is recorded as its own event rather than an amendment to
`193d1cb`: strict mode is a distinct, independently verifiable protection
property with its own live-state check (`GET /branches/main/protection`),
its own behavioral contract (stale-base re-run), and its own audit
trail in the README. No deploy step shipped it — the API call itself was
the change — so it deserves its own heading, not a parenthetical note.
(Until this upgrade, the changelog's earlier "strict" phrasing described
intent, not live state — the honest ledger records both.)

## Continuous self-proof of the enforcement itself

A gate can rot silently (wire removed, hook weakened, proof env drifts).
The scheduled/dispatch re-proof exists because that was a real observed
class of failure.

- **10-11 `193d1cb`** — Onboarding proof runs on every manual
  `workflow_dispatch`: a throwaway clone is onboarded and self-proves.
  Three real CI bugs were caught and fixed by this proof, not by review:
  `2e7053f` (bare runners have no git identity — the proof commit failed
  before the hook ever ran), `967a179` (hook lacked the executable bit —
  one of the hooks actually shipped un-runnable), and `095eb89` (proof
  only covered wiring, not the preflight path).
- **10-11 `b72309a`** — Weekly schedule cron added; the `setup-prove`
  job's condition now admits `schedule`, so both gate and onboarding
  re-proof run with zero pushes. In the same commit: `test_install_hooks.py`
  joins the gate (fresh bare→clone, isolated git config), and the README
  gained the four-protection-layers section this changelog mirrors.
- **10-11 `0d7ba58`** — the onboarding proof now also exercises the
  session-close path: `pilot_close --with-sheet` (the single close command)
  runs against the dry-run ledger inside every proof; the report must be
  intact, all tasks closed, both lines placed into the live-fill sheet,
  tally clean, and idempotent on re-run. Close-report generation can no
  longer regress silently either.
- **10-11 `b70f13d`** — the mirror-drift bug that motivated this changelog:
  18 line-continuations in `setup_machine.sh` silently collapsed into
  literal `
` inside a committed file (write-mirror artifact), which made
  the §0 preflight fail end-to-end even while `bash -n` passed. Fixed by
  restoring real backslash-EOL continuations — and caught by exactly the
  end-to-end onboarding proof described above, its first live catch.

- **10-12 `041242f`** — **Strict-mode canary**: `tools/strict_canary.py` and the
  `strict-canary` job (weekly `schedule` + every `workflow_dispatch`) re-prove the
  Layer-3 stale-base refusal instead of leaving it in prose. A throwaway pull request
  is cut from an older `main` commit, a green `regression-gate` check is placed on that
  stale head (synthetic, and its output says so — `GITHUB_TOKEN`-authored events start
  no workflow runs, so CI cannot supply one), and the run must then see
  `mergeable_state: behind`, a `405` refusal, and a refreshed head that is
  `clean`/`unstable` and mergeable — `update-branch` being the remedy it exercises. The
  pull request and branch are deleted on every path; a `2xx` from the attempted merge is
  a protection regression rather than a pass; and exit `3` (`CANNOT PROBE`) keeps a
  configuration gap from reading as a verdict. Three real bugs were found by running it,
  not by review: the HTTP client discarded JSON **arrays** (the commits listing came back
  empty), the probe read the refreshed head before `update-branch` had moved it, and the
  positive control demanded `clean` where GitHub legitimately answers `unstable`. It also
  needed this repository to stop forbidding Actions-created pull requests
  (`can_approve_pull_request_reviews` false → true, 10-12); the alternative, a dedicated
  `CANARY_TOKEN` secret, stays wired and documented. Verified live: dispatch run
  `38181495347` on the pull request that landed this — refusal, refresh, cleanup, PASS.

## Credential stores — the gate now looks outside the repo (10-12, `adc79ba`)

The PAT-cleanup audit found two silent shapes no check could see: a live credential in
the OS store that no gh session manages (no hosts.yml, yet gh's git-credential helper
still serves it to git), and a store entry the effective helper chain no longer reads
(`gh auth setup-git`'s URL-scoped reset orphans the GCM entry for the same URL).

- **10-12 `adc79ba`** — `tools/check_credential_hygiene.py` joins the gate: both shapes
  refuse the next commit until triaged, the same stop-the-line rule `check_secrets` and
  the app-DB scan already carry. The machine's three pre-existing entries are baselined
  with their triage note (`tools/credential_hygiene_baseline.json`), so the gate stays
  green while they remain visible and pruneable. Read-only: no helper is executed, no
  secret value is read into the report, and `cmdkey` is asked for target names only;
  a hosts.yml `oauth_token` is inspected as present-or-placeholder. Its 14-invariant
  test suite (reset semantics, the hook's HOME trap, UTF-16 listings, no value echo,
  fail-closed hosts.yml/baseline) rides the same gate, and POSIX platforms report the
  store surface N/A so the CI mirror runs it unchanged.

## Why the layers are not redundancy

Each layer covers a failure mode of the previous one: the CI mirror covers
clones without the hook; the required check covers `--no-verify`; admin
enforcement covers the owner; the scheduled onboarding proof covers the
enforcement machinery itself going stale. During 10-10..11 every layer
caught at least one real failure (hook: un-runnable executable bit via CI
proof `967a179`; check-run: context-name mismatch `74d13a5`; admin:
protection 422 on a workflow file not yet on origin; onboarding proof:
collapsed continuations `b70f13d`).

`setup_machine.sh` in one command; the full story lives in
[README.md](README.md).
