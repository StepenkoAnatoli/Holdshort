# SmartRouter

## Project phase state (updated 2026-10-11)

Executable phases of the plan are **closed** — released as
[`v1.0.0-pilot`](https://github.com/StepenkoAnatoli/SmartRouter/releases/tag/v1.0.0-pilot)
at commit `b6e04fd`. The authoritative ledger is
[docs/PROJECT_COMPLETION.md](docs/PROJECT_COMPLETION.md); summary:

| Phase | State |
| --- | --- |
| 1 — plan, review brief, acceptance packets, §10 fixtures | **Closed** (plan rev `d7c00f96`) |
| 2 — canonical `smart-router` skill + review/eval-prep siblings | **Closed** (3 skills validated by `tools/validate_skills.py`) |
| 3 — preregistration (task pool, seeds, pricing, thresholds) | **Closed** — owner-deviation closure at `6d0b140`; formal exit in [docs/PHASE3_ACCEPTANCE_RECORD.md](docs/PHASE3_ACCEPTANCE_RECORD.md) |
| 4 — pilot evaluation, non-live scope | **Closed** — 5/5 task contracts executed; report in [docs/PHASE4_PILOT_REPORT.md](docs/PHASE4_PILOT_REPORT.md) |
| **Live Phase 4** — real-provider pilot (real spend) | **Open** — the only executable item left; gated on §10 row 4: real rate sheets, live qualification records, explicit owner spend approval |
| 5–7 — consumer integrations (Research-Kit, Moonzila) | **Consumer-owned by design** — their owners approve and execute; handoff notes in `docs/HANDOFF_MOONZILA.md` / `docs/HANDOFF_RESEARCH_KIT.md` |

**Open ≠ unguarded.** Nothing live can run without the §10 row-4 key in a
gitignored `.env`, dispatch hard-caps, and the enforcement stack described
below. The skill set shipped in Phase 2 — the single canonical routing
authority [skills/smart-router/SKILL.md](skills/smart-router/SKILL.md) with
[references/gates.md](skills/smart-router/references/gates.md), non-author
review procedure [skills/smart-router-review/SKILL.md](skills/smart-router-review/SKILL.md),
and no-spend eval prep [skills/smart-router-eval-prep/SKILL.md](skills/smart-router-eval-prep/SKILL.md) —
is validated packaging, not yet installed in any consumer; adoption still
requires each consumer's own authorization (plan §14/15).

## Enforcing-by-default: the four protection layers

A clone of this repo enforces the Phase-4 regression gate by default, and main
cannot receive unverified content through any path. Four independent layers —
each has caught a real failure during development:

1. **Local pre-commit hook** — `core.hooksPath` is wired repo-locally by
   `python tools/install_hooks.py` (or one-command `bash tools/setup_machine.sh`);
   every commit runs the full gate on HEAD+index and refuses on any failure.
   The hook is tracked at mode `100755` so Linux checkouts execute it.
2. **CI mirror** — the `regression-gate` GitHub Actions workflow runs the same
   gate on every push to main and every pull request, so clones *without* the
   hook wired are still covered, and `--no-verify` bypasses still get audited.
3. **Required status check (strict)** — branch protection on `main`
   requires the `regression-gate` check, with strict mode on (since
   2026-10-11, set via the API): the check must be green against the
   current base — a PR whose base moved re-runs the gate before it can
   merge. A push without a green gate is refused server-side with
   `GH006`.
4. **Admin enforcement** — `enforce_admins` is on: the owner's own pushes go
   through the same required check. No human path lands unverified content.

   For a new contributor's first attempt to land code by pushing a commit
   straight to `main` (the classic `--no-verify` bypass or a fresh clone with
   no hooks): there is no first-attempt grace period — the very first push is
   refused server-side with `GH006` (required status check not green), and
   install-hooks-wiring doesn't matter, because the enforcement here is
   server-side and hooks exist only to prevent you from ever getting to that
   refusal. The correct first move is a pull request against a feature
   branch, which gets the CI gate run on the PR head before any merge is
   considered; strict mode additionally guarantees the gate re-runs if the
   base moves between the PR's CI pass and merge.

Plus continuous self-proof: a weekly scheduled run (and every manual
`workflow_dispatch`) re-runs the gate AND the onboarding proof — a throwaway
clone goes through `setup_machine.sh` (wire → clean commit allowed → staged
fake key refused → §0–§2 preflight) so enforcement itself cannot rot silently.

### New-clone setup (one command)

```bash
bash tools/setup_machine.sh https://github.com/StepenkoAnatoli/SmartRouter.git
```

This clones, wires the hook, proves enforcement (clean commit allowed, staged
fake key refused), and ends with the automated runbook §0–§2 preflight — the
machine is verified ready, not just gated. `python tools/install_hooks.py` alone
re-wires an existing checkout; the key for live dispatch stays out of the repo
(row-4: local gitignored `.env` only).

## Historical planning documents (superseded README content preserved)

The Phase-1 plan-only documents remain on this branch as historical/specification references:

- [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md): original and follow-up correction maps,
  final coverage-gap register, fail-closed qualification, deterministic task/attempt states, complete
  positive/negative/boundary fixtures, independent plan acceptance, pilot prerequisites and separate
  report/adoption gates.
- [docs/ROUTER_SURVEY.md](docs/ROUTER_SURVEY.md): pinned 13-repository survey; no upstream code or
  assets copied.
- [docs/ACCEPTANCE_PACKET_b7e4827.md](docs/ACCEPTANCE_PACKET_b7e4827.md) and
  [docs/REVIEW_BRIEF_4654158.md](docs/REVIEW_BRIEF_4654158.md): reviewer handoffs pinned to
  historical revisions; not current-head acceptance records.

The previous README's tier flowchart, response-header mandates and score-average approvals are
available in the [historical policy](https://github.com/StepenkoAnatoli/SmartRouter/blob/f575225642155e2e5abe1a718c8f6924e9a4f66d/README.md)
only. They are **not** operational instructions on this branch and must be deactivated in any
consumer before Phase 2 exits (plan finding F4/S14).

## Scope and license

Specification fixes are not a claim that all future work is verified. Outstanding owners, evidence
and blocking milestones are named in the plan. Authorization is still required for skill adoption,
paid calls, consumer reconfiguration and merge. Research-Kit and Moonzila sources remain unchanged.
Proposed requirements and synthetic fixture results are not evidence of runtime enforcement,
qualified real models or economic benefit.

[LICENSE](LICENSE) applies to the newly authored planning documents and — for this branch — the new
skill files listed above. It does not license historical SmartRouter content or linked third-party
repositories.

<!-- strict-test marker: deliberate PR left open while main moves (stale-base merge refusal check), safe to delete -->
