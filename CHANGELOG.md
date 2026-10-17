# Changelog

## 2026-10-13 — autonomous default, explicit HITL, observed usage and project boundaries

At the user's explicit direction, canonical skill v3.0 makes HumanGate none the
default for all task classes. Human checkpoints require a recorded user request;
missing authorization, verification, accounting or remaining allowance still blocks.
The command supervisor emits blocked packages without a human action menu unless
--human-requested is supplied, and class-table lookup honors the same opt-in.
Repair limits remain one total (R01/R02/R03), cannot be raised by CLI, and terminal
repair failure prevents another launch. Supervisor output is redacted before logs,
state and packages are written. A metadata-only usage exporter and engineering
record capture observed GPT counts, missing inputs, failures and future risks
without turning subscription usage into an invented provider bill or savings claim.
Removed unrelated consumer handoff/adoption records and named fixture coupling.
Credential custody defaults to ~/.secrets/smart-router; sibling project inventories
are excluded. Historical binary bundles are removed from current source. The ACL
probe uses its selected runtime's own modules; two Windows-only test harness leaks
are fixed without weakening production checks.

New-reviewer guide to **enforcement hardening**, told chronologically: each
protection layer was added because of a real observed failure, and each
entry below names the commit that shipped it. See
[README.md](README.md#3-enable-contributor-checks)
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

## Credential rotation — the other half of `.env` placement (10-12, `79eeb59`)

Placement was documented; removal and replacement were not. `docs/CREDENTIAL_ROTATION_RUNBOOK.md`
closes that: the inventory this machine actually holds (live-dispatch key, the GitHub credential
present in *both* stores, the gh session, the optional `CANARY_TOKEN`, plaintext credential files),
the Windows two-store mechanics that make deletion non-obvious, per-credential procedures, the leak
surfaces no repo check can see, and the verification that proves the new value is the one in use.

- **10-12 `79eeb59`** — the runbook lands, linked from GO_LIVE_RUNBOOK §1 and the README's
  new-clone paragraph. Its central claim is measured, not asserted: on this machine
  `gh auth setup-git`'s URL-scoped `credential.https://github.com.helper =` reset leaves GCM's
  `git:https://github.com` entry unreadable, while two `gh:` keyring tokens stay live with no
  `hosts.yml` — `git ls-remote origin` succeeds through exactly that orphan. So the obvious move,
  rotating in the store you can see, invalidates the copy nobody was using. Each procedure
  therefore ends with an explicit per-target `cmdkey /delete` and a use-test (store check → chain
  inspection → `ls-remote` → push → CI), plus pruning the resolved entry from
  `tools/credential_hygiene_baseline.json`, because a resolved row left in place silently silences
  a recurrence. Read-only by construction, like the checks it documents: no secret value is read,
  printed or validated and no helper is executed. Every read-only command it prescribes was
  exercised before landing; the destructive or interactive steps (`cmdkey /delete`,
  `gh auth login --with-token`, `gh secret set`, GCM `github login/logout`) are marked in its §7 as
  prescribed-but-not-run. Checking the inventory before landing turned up a copy that the 10-11
  audit had only listed: the Desktop token export is byte-identical (sha256 compared locally, never
  printed) to the credential git serves, so replacing the `github.com` credential means replacing
  that file too.

## The app's transcript store is now inside the gate (10-12, `2512d85`)

`check_secrets` can only see `git ls-files`, so a credential echoed into a chat has never been
covered by anything: the Freebuff Desktop app persists thread transcripts into sqlite stores under
`~/.config/freebuff-desktop/projects/*/desktop-v2.db*`, outside every repo. This machine's store
holds token-shaped occurrences today — including a still-live GitHub PAT — which is exactly the
residue class the checks above cannot reach.

- **10-12 `2512d85`** — `tools/check_app_db_secrets.py` joins the gate after `check_secrets` and
  `check_credential_hygiene`, so the hook and the CI mirror both run it. It reuses `check_secrets`'
  audited anthropic/sk patterns and adds the six GitHub families, but not the noisy
  key-assignment/bearer matchers, because on opaque binary transcript blobs those are triage noise.
  Stores are decoded latin-1 so reported offsets are byte offsets; hits print class + offset +
  sha256 digest and never the value, so triaging a leak cannot re-leak it. Exit 1 refuses the next
  commit on a NEW hit; exit 2 fails closed on an unreadable or oversized store or a malformed
  baseline. Resolution puts `USERPROFILE` ahead of `HOME` because the hook exports
  `HOME="$REPO_ROOT"` — the trap `credential_hygiene` documented, now pinned by its own test — and a
  machine with no app directory SKIPs with exit 0, which is why the CI runner stays green. The 16
  digests (184 occurrences) that predate the check are baselined with their class and triage note:
  known and visible to the gate, not harmless. Ten hermetic invariants ride the same gate, and
  `.gitignore` gained the `.local/` rule for the XDG byproducts the hook's HOME export drops into
  the checkout.

## The transcript store is watched, not only gated (10-12, `381bf5b`)

The check above acts at the *next commit*: a value pasted into a thread is refused hours later, or never,
if the thread simply ends. `tools/watch_app_db_secrets.py` is the continuous half — the same scan, run
while the app is in use.

- **10-12 `381bf5b`** — the watcher imports `check_app_db_secrets.py` by path rather than copying its
  patterns, so the pattern set and the fail-closed rules cannot drift from the gate's, and adds a
  literal-prefix prefilter that is conservative by construction: zero-width anchors are stepped over,
  `(?i)` disables the derivation, and any escape or alternation gives up and returns None (the
  prefilter turns itself off rather than risk under-scanning). Its tests pin that the prefilter path
  returns exactly what the check's own `scan_store` returns for the same bytes. Reporting keeps the
  check's discipline — class, byte offset, sha256 digest, never the value — and repeat alerts are
  suppressed by digest through a state file of digests and timestamps only, without changing the
  verdict: a leak that is still there still exits 1. Exit codes match the check (0 clean, 1 untriaged
  hit, 2 fail-closed), `--once` is the cron contract, and `--on-new "<command>"` hands the digest to
  the operator's own notifier. It polls with `stat` only — 0.63 ms for all four stores here — and
  scans on a debounced change or a heartbeat, so it neither reads a store mid-write nor dies on a
  locked one: an unreadable store is a warning, an unscannable one makes the pass incomplete so
  "no new hits" is never read as clean.
- **10-12 `381bf5b`** — its cost is stated rather than sold: a pass over this machine's 23 MB store is
  ~2.3 s, the check's own cost, because the store holds baselined hits and the prefilter therefore
  cannot short-circuit it. The prefilter pays off only on a store with no token-shaped literal at all
  (a 16 MB no-literal corpus: 1.3 s → 0.15 s). What is cheap is the idle watcher: about a millisecond
  every five seconds. The module docstring says exactly this instead of claiming to be lightweight.
- **10-12 `381bf5b`** — the 15-invariant suite joins the gate last (it is the slowest, ~10 s, because
  it starts real watchers and drives one with a live store change). It runs against an *isolated empty*
  baseline, and its first run proved why: W3 planted a fixture and asserted an alert while that very
  fixture's digest had just been triaged into the tracked baseline, so a test coupled to live triage
  state stops asserting the day its fixture is baselined. Triage churn is not hypothetical here — this
  session's own transcript put token-shaped text in the store (rendered fixture values first, then
  raw-byte fragments of them: a live WAL store read as plain bytes yields partial copies as pages are
  rewritten), and every new digest was identified — prefix of, or straddle against, our own fixtures —
  before it was recorded, with two earlier notes corrected rather than left imprecise. The runbook's §4
  and §5 now document both tools where an operator looks for this surface.

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

## Skill v1.1.0 — isolated-worker delegation contract (10-12)

The routing skill gained the operational patterns of a multi-agent supervisor
without gaining any of its authority. Source studied and verified:
`OrchestratorInc/agent-orchestrator`, cloned 10-12 — its `docs/architecture.md`
("Project sessions own isolated Git worktrees"; "Display status is never
stored. It is computed at read time from durable facts") and its README ("the
orchestrator owns planning and delegation; workers own implementation, tests,
commits, and pull requests"). Lands with this change; the commit hash is the
one that ships it.

- **Isolation contract** — every `delegate` route now names an isolation
  expectation (`worktree+branch` preferred), and "no shared mutable working
  tree across concurrent workers" joins the hard prohibitions. Adopted because
  branch/worktree collision between parallel workers is exactly the failure
  mode the source project exists to solve.
- **Ownership + closed feedback loop** — project-orchestrator vs worker split
  with sticky ownership: verification failures, CI failures and review comments
  return to the same owning profile as a new brief, and ownership never
  transfers silently. This pairs with our own verification gate: a failed gate
  becomes a new brief for the same owner, not a fresh dispatch.
- **Machine-readable briefs** — the brief emits `isolation`, `branch-hint`,
  `ownership` and the rest as fields a host can dispatch without
  reinterpretation; the harness joins the profile identity tuple so one
  decision can target different runtimes.
- **Derived status, never self-report** — an agent's "done" stays unverified
  until observed facts (checks run, PR/CI state) support it (plan S10,
  retained).

Deliberately **not** copied: the Electron desktop + Go daemon (heavy for a
skill-focused project), the Kanban look-and-feel, and any orchestrator freedom
to spend or switch models — this repo's fail-closed gates stay stricter. All
v1.0.0 rules are retained unchanged (`metadata.previous: "1.0.0"`).

## Skill v2.0.0 — complete surface contract (10-12)

`skills/smart-router/references/spec-v2.md` lands the consolidated
SmartRouter + Isolated Workers specification (routes, isolation, ownership,
HumanGate, nesting, speculative sets, machine-readable objects, Host
responsibilities, compliance), and the skill consumes it as its external
contract. Every addition is strictly additive and default-deny, per the spec's
own §13 rule; gate semantics stay fixture-pinned to the plan.

- **Fifth route `speculative`** — bounded parallel candidates; first to satisfy
  the acceptance contract becomes sole owner; opt-in only (high uncertainty +
  explicit host opt-in), the shared budget is a hard ceiling, cancelled
  candidates still consume their dispatches, and nested speculative sets are
  disallowed (§8.4, added when the Gate-5 explainer surfaced the gap).
- **HumanGate + nested delegation** — `review-before-dispatch` /
  `review-before-merge` / `approval-required`; nested sub-briefs only when the
  decision sets `NestedAllowed: yes` (parent keeps ownership, counters roll up
  to the original task, depth ≤ 1, host policy may raise to 2). Without it,
  "no recursive delegation" still holds.
- **Isolation lattice as a lower bound** — `none < directory < worktree+branch
  < ephemeral-container`; the host may only strengthen, never weaken.
- **Normative objects** — Brief, SpeculativeSet and Outcome/PreviousResult
  schemas (spec-v2.md §10) and the Host's ten musts (§11).

Verified against the pinned evidence base: the decision fixture suite keeps all
52 pinned fixture IDs green and gains additive v2.0 fixtures (X1/X2 speculative
opt-in and budget ceiling, N1 nesting default-deny, H1 HumanGate enum, I1
isolation lower bound); `validate_skills` passes strict. Deliberately still
absent: the Host itself (execution, worktree spawning, Outcome Ledger) — the
spec defines its contract; this repo remains the decision layer only.
