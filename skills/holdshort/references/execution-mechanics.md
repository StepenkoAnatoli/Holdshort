# Execution mechanics companion (non-normative)

Retry taxonomy, cooldown state machine, and replay/commit rules for hosts that
execute Holdshort routes. This document is guidance: the binding rules are the
plan (§§7–8) and spec-v2.md §§11–12. All upstream behavior below is summarized
from pinned revisions cited inline; no upstream code is vendored or copied.

## 1. Retry taxonomy: what may be retried, and where

A Holdshort host retries a **candidate**, never an ambiguous effect. The
surveyed routers converge on the same split, with different failure modes:

- **Retryable before commitment:** 429 rate-limit, 502/503/504 upstream faults,
  network errors and timeouts observed *before* any effect commits. KeiRouter
  (mydisha/keirouter @ `3d8b702`, `dispatch.go` / `classify429.go`) classifies
  429 bodies into transient / resettable-quota / exhausted-credits and falls
  back to another candidate; ClawRouter's `retry.ts` (BlockRunAI/ClawRouter @
  `b758e03`) retries 429/502/503/504 with exponential sleeps. newapi-smart-router's
  retry README (ginsonko/newapi-smart-router @ `034daab`,
  `parts/algorithms/retry/README.md`) separates transport / protocol / business
  contracts so a transport failure never becomes permission to replay a
  business effect.
- **Never retried blindly:** 4xx validation/auth failures, client cancellation,
  committed semantic streams, ambiguous media creation, and any dispatch whose
  acceptance is unknown (plan §7: reconcile the original operation first).
  NadirClaw's server fallback (NadirRouter/NadirClaw @ `fa6ca99`, `server.py`)
  re-raises HTTP validation/auth failures instead of failing over — a host must
  do the same rather than shopping a rejected request to another profile.
- **Warnings imported from source review, not adopted:** `retry.ts` retries any
  thrown fetch exception (not just network errors), replays POST bodies with no
  idempotency-key policy, and documents an HTTP-date `Retry-After` form its code
  does not parse; an upstream hint is a *lower bound* on backoff, never a
  substitute for the host's own attempt budget. Generic transport retries are
  not replay permission (survey §2, §9).

Every physical dispatch — initial, planner, verifier, transport retry, repair,
escalation — consumes the single approved task call budget (plan §8). A host
that cannot observe or bound hidden retries cannot offer strict-cap or
attempt-guarantee dispatch: unobservable calls still count, so an unobservable
pipeline blocks rather than proceeds.

## 2. Cooldown state machine

Cooldown is per-candidate, time-bounded, and advisory to ranking — it never
resurrects a candidate rejected at an earlier gate (§5: empty/all-unavailable/
all-cooldown filters must not resurrect rejected candidates).

```text
healthy ──(recognized failure × threshold)──▶ cooling_down(until = now + delay)
   ▲                                              │
   │                                   deadline passes → eligible again
   └──────── success resets count/cooldown ───────┘
```

- **Scopes compose, they do not collapse.** KeiRouter scopes cooldowns to
  account (rate-limit/auth/quota/transient: 30s–30min, exhausted balance
  parked 24h), to account+model (model-scoped failures ≥ 5min), and to the
  provider (circuit opens after 3 consecutive failures, 5s doubling to 2min, 1
  quiet minute resets). A model cooling down never disables its provider; a
  provider circuit never rewrites a capability verdict. NadirClaw's provider
  health tracker (default 2 consecutive failures → 60s cooldown) only reorders
  fallback candidates — cooling candidates stay listed, preserving outage
  visibility instead of inventing replacements.
- **All-cooldown behavior is bounded waiting or honest surfacing.** KeiRouter's
  pipeline waits at most ~10s (3 planning retries) then returns the earliest
  retry time; NadirClaw tries cooling candidates in order rather than
  abandoning the chain. A host MUST NOT convert "everything is cooling" into
  success, and MUST NOT strip the cooldown to manufacture an eligible set.
  Equality with the deadline blocks dispatch (plan §8); a long cooldown is
  returned, not waited out beyond the remaining budget.
- **Rejected kill-switch pattern:** NadirClaw's verifier kill switch routes
  cheap-only after 3 consecutive verifier errors, in-memory until restart, with
  no timer. A consecutive-failure counter that degrades verification instead of
  stopping dispatch is a fail-open path and is prohibited here: repeated
  verifier errors escalate to `needs-human` / `blocked`, never to unverified
  success (see verifier-gated-escalation.md).

## 3. Backoff parameters (host-chosen, disclosed)

The plan sets no universal constants; a host declares its own and records them
in the decision trace:

- Exponential base with jitter on locally computed delays; upstream
  `Retry-After` (seconds or HTTP date) raises the delay, never lowers it.
- A MaxRetries-style bound is expressed in *candidate attempts against the task
  call budget*, not silent per-call retries — ClawRouter's default 2 retries /
  3 attempts is a transport-helper bound, not a task budget.
- Magma-Devs/smart-router's callsite budget test
  (`attempt_budget_callsite_test.go`) is the pattern to imitate: exercise the
  real dispatcher with an upstream slower than the internal window but inside
  the total budget, and assert the caller passes the correct remaining budget.
  Test the callsite, not a recreated scoring function.

## 4. Replay and commit rules (summary; prohibitions bind)

- Known replay class + known acceptance/commit state + fresh eligibility +
  remaining budget/deadline, or no replay (plan §7).
- `send_started` with unknown acceptance counts as consumed until host evidence
  proves no send; restart resumes the journal, never replays the ambiguous
  attempt (plan §7, fixture R03).
- Cancellation/Stop reconciles first: no rollback is assumed, no charge is
  released on cancel alone, and pending recovery stays pending (plan §7–§8).

Pinned sources: docs/ROUTER_SURVEY.md §§2, 4, 11–13; docs/ROUTER_SURVEY.md
consolidated recommendations 2–4; deep-dive reports for KeiRouter
(mydisha/keirouter @ `3d8b702`), NadirClaw (`fa6ca99`), router-core
(`a5452c5`) / ClawRouter (`b758e03`) — see repo research log.
