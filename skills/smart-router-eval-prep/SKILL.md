---
name: smart-router-eval-prep
description: Prepare an evaluation preregistration and cost-per-verified-success comparison plan for SmartRouter trials. Use when designing a pilot, drafting frozen thresholds, or assembling the economic comparison protocol. Prepares documents only; never authorizes, schedules, or runs paid trials, and never substitutes author-supplied numbers for owner-approved values.
license: MIT
metadata:
  version: "1.1.0"
  previous: "1.0.0"
  defers-to: smart-router
  spec-pinned: "docs/DEVELOPMENT_PLAN.md@d7c00f96a17c35e6c47c5ba1f7e3a9160c966042"
  changelog: |
    - v1.1.0: preregistration now freezes isolation, ownership, and feedback-loop
      dimensions (isolation capability, owner accounting, repair budgets) so trial
      evidence can verify what v1.1 reviewers check. Still never authorizes trials.
---

# SmartRouter evaluation preparation — preregistration only

You prepare evaluation paperwork. You never run or authorize a trial, never call a provider, and
never fill in invented numbers where the plan requires owner-approved values.

## When to use
- A Phase-3-style pilot is being planned and needs its preregistration document drafted.
- An economic comparison (cost per verified successful task) needs a defensible, frozen protocol.
- An existing preregistration needs a completeness/gap audit before submission for approval.

## Procedure

1. **Read the pinned specification** (canonical skill [../smart-router/SKILL.md]
   (../smart-router/SKILL.md) and plan sections 10-11) — do not invent thresholds, arms or statistics.
2. **Work through the checklist** at
   [references/preregistration.md](references/preregistration.md). Every item must end with either a
   frozen numeric/protocol value or an explicit "owner must supply" marker — never a blank, and never
   a number you invented to make the document look complete.
3. **Name the host and controls** explicitly: identity/permissions evidence, billing/usage
   observations, conservative bounds, all-call limits, isolation, Stop/recovery, required checks.
   Freeze the v1.1 dimensions per [references/preregistration.md](references/preregistration.md)
   §6: the host's isolation capability (worktree support, branch convention), per-owner
   accounting (which worker owns which brief), and the feedback-loop budget (at most one
   same-profile repair per original task, plan R01/R02/R03 — counted in the arm economics).
   Absence of a host is a reported blocker — not a reason to weaken the protocol.
4. **Separate report closure from promotion eligibility** in the drafted protocol: a complete report
   may close as `rejected` or `inconclusive` with disclosed gaps and still release no reservation and
   permit no adoption.
5. **State evidence limits** in the prepared document: what will and won't be tested, what requires
   owner authorization, what stays untested until a live trial is separately approved.

## Hard boundaries

- **Never authorize or execute a paid/model trial.** Preparation output ends at a document.
- **Never use plan-section-10 synthetic fixture numbers** as live-pilot thresholds — those are
  declared test inputs for decision semantics only.
- **Never invent calibration data**, confidence constants, or "expected" savings.
- **Never treat the canonical router's output as pilot evidence.** Trial evidence requires the
  separately approved protocol and actual observed runs.
- **Never release uncertain reservations or claim savings** while accounting is incomplete — flag
  instead, and hand the blocker back to the owner.

## Output format

```
Prepared document:  <path to drafted preregistration>
Completeness:       <items complete / items awaiting owner value / items blocked>
Named host:         <name + evidence reference, or "none — Phase 3 blocked">
Evidence limits:    <what this document does NOT authorize>
```
