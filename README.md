# SmartRouter

## Canonical routing skills — Phase 2 preview (separate authorization required)

This branch adds a proposed, author-amended **skill preview** for the plan's Phase 2 milestone:

- [skills/smart-router/SKILL.md](skills/smart-router/SKILL.md) — the single **canonical** routing
  authority: ordered eligibility gates, recommendation/direct/delegate/escalate/blocked output
  contract, and pinned references [references/gates.md](skills/smart-router/references/gates.md),
  [references/brief-and-result.md](skills/smart-router/references/brief-and-result.md).
- [skills/smart-router-review/SKILL.md](skills/smart-router-review/SKILL.md) — evidence-backed
  blocker review; defers to the canonical policy and never re-selects or grants score-based
  permission.
- [skills/smart-router-eval-prep/SKILL.md](skills/smart-router-eval-prep/SKILL.md) — evaluation
  preregistration preparation; never authorizes or runs a paid trial.
- [tools/validate_skills.py](tools/validate_skills.py) — packaging validator (frontmatter, name
  matching, reference resolution, no-competing-authority sweep). Run: `python tools/validate_skills.py`.

**Status: proposed, not yet approved.** These skills are not yet installed in any consumer. Nothing
here authorizes adoption, spend, dispatch, or_merge. Per plan section 14/15, Phase 2 exits only
after: valid packaging plus semantic review at the full revision, per-scenario dispositions
recorded, no competing operational authority, and no untested runtime claims. A separately
designated non-author review plus owner acknowledgement is still required before Phase 2 sign-off —
see [docs/PHASE2_REVIEW_RECORD.md](docs/PHASE2_REVIEW_RECORD.md) for the author-side validation
record and the outstanding review requirements.

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
3. **Required status check** — branch protection on `main` requires the
   `regression-gate` check (strict) before any update lands; a push without a
   green gate is refused server-side with `GH006`.
4. **Admin enforcement** — `enforce_admins` is on: the owner's own pushes go
   through the same required check. No human path lands unverified content.

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
