# RELEASE_NOTES.md — SmartRouter v1.0.1 (enforcement & docs refresh)

> **Base release:** [`v1.0.0-pilot`](https://github.com/StepenkoAnatoli/SmartRouter/releases/tag/v1.0.0-pilot)
> at commit `b6e04fd525fa886b07d149ab5a7f88da3f7b7c89`. This revision supersedes it on `main`
> (tip: `f4d1522`) with enforcement, testing, and documentation upgrades. **No change to the
> three executable skills' routing semantics** — the canonical policy content of
> `skills/smart-router{,-review,-eval-prep}` is byte-identical in intent; what changed is
> everything that enforces and proves the pipeline around them.

## What's new since v1.0.0-pilot

### Enforcement hardening (the four protection layers get stronger)

1. **Gate wiring self-check (Layer-1 self-proof)** — `tools/check_hook_wiring.py` (new,
   `ee0049c`) is the regression gate's *first* check: it fails the gate when the pre-commit
   hook cannot fire — repo-local `core.hooksPath` unset/wrong, `.githooks/pre-commit` missing
   or non-executable (POSIX), or tracked mode ≠ 100755. CI view checks tracked mode only
   (bare CI checkouts have no wiring by design). Covered by 11 tests
   (`tools/test_hook_wiring.py`), including a proof that a *global* hooksPath can never
   satisfy the wiring contract.

2. **Secrets scan: fail-closed decode policy** (`72c8014`) — previously a tracked file that
   failed UTF-8 decoding was *silently skipped* (an unscanned hole). Now: `utf-8-sig` →
   strict `utf-8` → `utf-16` decode chain with NUL-byte-parity endianness selection for
   BOM-less utf-16; undecodable/unreadable text-class tracked files produce **exit 2
   (fail-closed)** with the offending path, never a silent pass. 6 new tests (DecodePolicy
   class, total 17 in `test_secrets_env_guard.py`) cover utf-8-sig / utf-16 LE, BE, BOM
   leaks caught, plus an end-to-end fail-closed case through a synthetic git repo.

3. **Strict branch protection** (API change 2026-10-11, no code) — protection on `main`
   now requires `regression-gate` **strict**: a PR whose base has moved must re-run the
   gate against the updated branch before merging. The CHANGELOG and README document the
   exact provenance (see `bc47903`).

4. **Test-env isolation fix** (`24f9aa2`) — the wiring test's global-only-config case now
   scrubs `GITHUB_ACTIONS`/`CI` before spawning the CLI subprocess, so the test measures
   local-view semantics deterministically on a Linux runner too (this bug was itself caught
   by CI running the new gate — the enforcement stack working as designed).

### Documentation honesty upgrades

- **README header rewritten** (`c39f838`, and refined via `bc47903`) from the stale
  *"Phase 2 preview, proposed, not yet approved"* framing to the live ledger: Phases 1–4
  **closed** at `v1.0.0-pilot`, **Live Phase 4 open** (the only executable item left),
  Phases 5–7 **consumer-owned by design**. Skill descriptions preserved as
  *"validated packaging, not yet installed in any consumer."*
- **CHANGELOG gains the four-layer enforcement story** (chronological, hash-referenced),
  the API-driven strict-protection upgrade, and an honest note about the intent-vs-live
  state period.
- **Live-start packet reconciled** (`170967b`, merged via PR #13) — §4.2's stale
  *"still pending"* for reviewer designation replaced with the DONE provenance
  (`P02_REVIEWER_NOTICE.md` signed 2026-10-10, row-3 owner-deviation basis); the
  strict-P02 countersignature is explicitly an *upgrade*, not a pilot-start gate.
- **PAT-rotation hardening of the auth path** — the origin URL no longer carries an
  embedded token; pushes run through Git Credential Manager (proven by an actual
  protected-merge via PR #12 and #13). This is an operations change, not a packaged-file
  change, but it is recorded here for the provenance chain.

## Verification basis for this packaging

- Full regression gate: **13/13 PASS** (run by the pre-commit hook at each packaging commit;
  `hook_wiring`, `validate_skills`, all test suites, `check_secrets` fail-closed).
- Packaged-tree spot-checks executed in the staging directory before zipping:
  - `python tools/validate_skills.py` → exit 0 ("3 skills validated")
  - `python tests/smart_router_decisions.py` → exit 0 (79 assertions / 52 fixtures)
  - `python tools/check_secrets.py` → exit 0 (0 hits)
- Asset built from the parity tree `f4d1522` (local main == origin/main at packaging time).
- **Ships-nothing exclusions verified in the zip itself**: no `.env`, no ledger files, no
  `tools/task_state`, no `__pycache__`, no nested `.git`.

## Contents

| Path | Purpose |
| --- | --- |
| `README.md` | Current phase-state ledger + the four-protection-layers story |
| `CHANGELOG.md` | Chronological enforcement hardening narrative (hash-referenced) |
| `skills/smart-router/` | Canonical five-gate routing policy (v1.0.0, unchanged semantics) |
| `skills/smart-router-review/` | Blocker-focused reviewer procedure (v1.0.0) |
| `skills/smart-router-eval-prep/` | Preregistration prep, no live spend (v1.0.0) |
| `tools/` | Full enforcement + dispatch + close toolchain (incl. new `check_hook_wiring.py`) |
| `tests/`, `fixture_checks.py` | 79-assertion decision suite + smoke harness |
| `docs/GO_LIVE_RUNBOOK.md` | Operational runbook for the first live pilot session |
| `docs/PROJECT_COMPLETION.md` | Phase-1..4 closure record, merge-authority ledger |
| `LICENSE` | Repo-local license; does not cover historical or linked third-party works |

## Gates preserved

Everything gating `v1.0.0-pilot` still gates this release: strict branch protection with
`regression-gate` required (now also strict) + `enforce_admins`; pre-commit hook +
repo-local `hooksPath` + its self-check; fail-closed secrets scan; row-4 key placement
(gitignored `.env` with `$1`/`$20` caps, `api.anthropic.com`-only egress, 90-day window).
Consumer phases 5–7 remain owned by their respective owners; handoff notes unchanged:
`docs/HANDOFF_MOONZILA.md` and `docs/HANDOFF_RESEARCH_KIT.md`.
