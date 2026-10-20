# Proposal: spec v2.1 delta — Outcome `failure-class`, rule-activation HumanGate

Status: **draft proposal, not normative.** Nothing in `skills/` is amended by
this document. If accepted after independent review (plan §15), the two items
below would become additive spec-v2.md §10/§8 rows under the §13 "strictly
additive" rule; until then hosts MUST NOT emit or require them.

## Context

- spec-v2.md §10.3 `Outcome` classifies results into seven outcome values but
  carries no machine-readable *failure class*: the plan (§7) already requires
  hosts to "classify missing context, transport, reasoning, scope, permission,
  affordability and uncertain-effects failures separately", yet re-routing and
  the Outcome Ledger have no schema field to record that classification. Hosts
  will diverge into free-text notes.
- spec-v2.md §8.2 `HumanGate` has four values, none covering rule-engine
  activations that change tier or skip verification. NadirClaw's cascade
  rules (`force_escalate` / `force_cheap` / `set_threshold`, reviewed at
  `fa6ca99`) show why this matters: a `force_cheap` activation returns an
  answer without verification, and a rule-evaluation failure silently continues
  on the normal path. Under Holdshort both are §12 violations, so the
  activation itself needs a human checkpoint.

## Item 1 — `failure-class` on Outcome (§10.3, additive optional field)

```json
"failure-class": "missing-context | transport | reasoning | scope | permission | affordability | uncertain-effects | none"
```

Rules (proposed): default `none` for `accepted`; required (non-`none`) for
`verification-failed`, `partial`, `cost-overrun`, `blocked`, `escalated`;
`cancelled` uses `none` unless an observed violation reclassifies the task
`failed` per plan §7 priority (then the violation's class applies).
`uncertain-effects` forces `recovery_status = pending` and retains accounting
as pending until reconciled. The class travels with `PreviousResult` so
re-routing can distinguish "retry the same profile" (transport, missing
context once supplied) from "never retry this way" (permission, scope).

## Item 2 — `rule-activation` HumanGate (§8.2, additive enum value)

| Value | Meaning (proposed) |
|---|---|
| `rule-activation` | A routing-rule activation that would change the selected profile, alter verification, or raise/lower an acceptance bar requires explicit human approval before it takes effect. |

Rules (proposed): any host rule matching the NadirClaw-shaped patterns —
force-tier, skip-verification, threshold-change — emits a `rule-activation`
checkpoint with the matched rule, the proposed change, and the unaffected
baseline route. Approval applies to that activation only, never to the rule
generally. A rule-evaluation failure fails closed (route `blocked` or
`needs-human`), never silently continuing. Purely informational rules
(logging, tagging) are out of scope.

## Non-goals

No new routes, no changed gate order, no numeric thresholds, no license or
authority changes. The proposal does not revive the rejected patterns (accept
on verifier error, cheap-only kill switch, empty-set resurrection); it gives
hosts a schema to record and checkpoint the decisions around them.

## Review record (pending)

- Author: Holdshort working thread, 2026-10-12, revision at PR time.
- Independent reviewer: *unassigned* — plan §15 requires a non-author
  verdict at the full reviewed revision plus owner acknowledgement before
  this delta (or any part of it) amends normative files.
- Disposition: *pending*. Substantive edits to this proposal re-date it;
  approval of an earlier revision does not carry forward (P02).
