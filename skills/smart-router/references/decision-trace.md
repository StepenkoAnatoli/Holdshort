# Decision-trace companion (non-normative)

What a host records for every routing decision so that review, re-routing,
accounting and audit can replay it without re-executing it. Binding rules:
the plan (§§5, 7–8) and spec-v2.md §§10–11. The trace is host-owned;
SmartRouter stays stateless (spec §8.5).

## 1. One trace per decision

```text
decision:
  task-id, input-ref (exact bytes or pinned digest — summaries are not evidence)
  workspace / authority / authorization revision
  capability / catalog / verifier / price revisions + freshness limits
  timestamp (monotonic task clock for deadline arithmetic)
  route: direct | delegate | speculative | recommend-escalation | blocked
  per-candidate gate walkthrough with deterministic reasons
  allowance reserved (cash / calls / deadline) + remaining budget
attempts[]: one entry per physical dispatch (see §2)
terminal: execution_state / verification_status / recovery_status / accounting_status + reason
```

- **Bindings first.** A recommendation is bound to task/input, workspace,
  authority/authorization, capability/catalog, verifier and price revisions
  (plan §5). Any changed, expired or unknown evidence invalidates the route;
  re-evaluate without resetting the task ledger. Revocation always wins over a
  stale cache.
- **Reasons, not scores.** Record the deterministic reason for
  direct/delegate/escalation/blocked per candidate (plan §5 acceptance).
  Confidence values, price labels and tier names are not reasons and never
  establish sameness or qualification (R02).
- **Estimates apart from accounting.** Bounds and estimates are labeled as
  such; settled charges, outstanding reservations and uncertain retentions are
  recorded separately per currency unit, each attempt exactly once (plan §8).
  Missing billable usage is `unknown`, never zero.

## 2. Attempt entries: the replay-safety journal

Before each send, persist the task/attempt ID and reserve one call slot
(plan §7). Each entry records: attempt ID, profile tuple, reservation ref,
`send_started` flag, acceptance/commit state, and outcome axis values.

- `send_started` with unknown acceptance counts as consumed until host
  evidence proves no send occurred; restart resumes this journal, never
  replays an ambiguous attempt (R03).
- Cancelled/timeout calls still count; unresolved charges and reservations
  survive recovery (plan §8, S11/S19).
- An attempted decision with no send consumes no physical call but never
  resets the ledger.

## 3. Secret-free by construction

No API keys, raw prompts, private bodies, authorization headers or credential
URLs — only opaque pinned references, attempt IDs, commitment/recovery state,
check evidence and cost basis (plan §8). Unknowns remain unknown; no
mandatory verbose headers. The small secret-free receipt concept follows the
*need* identified by newapi-smart-router's route-receipt schema
(@ `034daab`, `parts/spec/route-receipt.schema.json`) — versions, attempts,
reservation/settlement/reconciliation, operator review — independently
authored here, without adopting its gateway or schema.

## 4. Terminal reporting and superseding

Apply the plan §7 priority at terminal reporting (failed > cancelled >
blocked > recommendation-only > accepted > unverified), recording the reason
and all four axes. Corrected ordinary defects retain their failed attempt
records (R04); new evidence appends a superseding receipt and recomputes
affected totals without erasing history (S22a). A later discovered violation
reclassifies the task (plan §1).

Pinned sources: docs/ROUTER_SURVEY.md §13 and recommendations 2–4; plan
§§1, 5, 7–8 and fixtures B01–B02, R01–R04, S19, S22a, V01–V09.
