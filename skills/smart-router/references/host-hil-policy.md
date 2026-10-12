# Mostly Autonomous + Human-in-the-Loop (HITL) Policy

**Status:** background material — non-normative. It sketches concrete host behavior for the
`HumanGate` field (spec-v2.md §8.2) and layered loop-prevention limits; the normative
contract remains [gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md). Where
this document and the normative files ever disagree, **the normative files win**. The
document below is preserved as given (its outer markdown packaging fence omitted);
its "mandatory"/"must" wording is host-policy aspiration, and the divergences from the
pinned rules are flagged here:

Flagged, with flag 1 fixed by tightening this policy (2026-10-12):

1. **RESOLVED — tightened to one repair total (plan R01/R02/R03 kept as the cap).** §4 (steps 4
   and 7) and §9.1 previously allowed one implementation repair **plus** one CI repair — up to
   two same-profile corrective dispatches on one task. spec-v2.md §7 and
   [brief-and-result.md](brief-and-result.md) (plan R01/R02/R03) cap this at **one**
   same-profile corrective dispatch per original task; the Brief's `attempts` field (§10.1,
   default 1) *records* that cap and cannot raise it, and the allowance is never renewed by
   restart, rename, profile change or escalation. Resolution: this policy now allows at most
   **one** same-profile corrective dispatch per original task **total** (implementation or CI,
   not each). A second cycle requires a fresh, separately authorized task with its own
   allowance (all dispatches still roll up to the original task), or an explicit spec
   revision. Flags 2–3 below remain flagged, not fixed.
2. **"Missing acceptance criteria → `review-before-dispatch`" (§3, rule 2) misroutes a Gate 3
   failure.** The acceptance contract must exist **before** work starts; a missing
   prerequisite before start ⇒ **blocked** ([gates.md](gates.md), Gate 3), and the Brief must
   pin exact acceptance checks ([brief-and-result.md](brief-and-result.md)). A human review
   is not a substitute for an acceptance contract. "Ambiguous requirements" alone can justify
   `review-before-dispatch`; "missing acceptance criteria" fails closed first.
3. **§9.6's circuit breaker computes above-attempt statistics.** A class-level escalation
   rate (">30%") is aggregated data; [brief-and-result.md](brief-and-result.md) reserves
   stats above attempt level for the separately authorized evaluation flow
   (`smart-router-eval-prep`), never per-task routing. Treat the breaker as a host safety
   switch that fails closed toward more human review, and run any rate computation under
   that authorized flow.

Everything else checked out against the normative sources: `HumanGate` as an autonomy
ceiling the Host may never lower (§8.2 + Host responsibility 7; fail-closed upward is
always allowed), the §2 behavior table (including creating the worktree *before*
`review-before-dispatch` approval, which correctly avoids dispatch), sticky ownership on
"request changes", never-reset counters, hard budget ceilings with cancelled candidates
still consuming dispatches, `needs-human` escalation triggers, and recording final status in
the Outcome Ledger (§8 audit) — which also supplies part of what
[host-worktree-merge.md](host-worktree-merge.md) flag 4 called for (the merge step *is* gated
by `HumanGate` here).

---

**SmartRouter + Isolated Workers — Concrete Host Policy v1.1**

### 1. Goal

Maximize autonomy for routine work while guaranteeing that a human is inserted exactly when risk, ambiguity, or repeated failure makes it necessary.  
SmartRouter sets the maximum allowed autonomy for every task through the `HumanGate` field. The Host must never exceed that gate.

---

### 2. HumanGate → Concrete Host Behavior

| HumanGate                    | What the Host is allowed to do                                      | What requires a human                  | Typical use |
|-----------------------------|---------------------------------------------------------------------|----------------------------------------|-------------|
| `none`                      | Full loop: worktree → agent → repairs → PR → CI → auto-merge       | Nothing                                | Trivial / low-risk |
| `review-before-merge`       | Full loop until PR is green, then pause                             | Final merge decision                   | Normal features |
| `review-before-dispatch`    | Create worktree + Brief only                                        | Starting the agent                     | Ambiguous scope |
| `approval-required`         | Nothing beyond preparing context                                    | Explicit authorization to proceed      | High-risk changes |

---

### 3. Default Risk Classification Rules

Apply these rules in order (first match wins):

1. **Security / irreversible / high-blast-radius**  
   (auth, payments, data deletion, migrations, public breaking API, production config)  
   → `HumanGate: approval-required`

2. **Ambiguous requirements or missing acceptance criteria**  
   → `HumanGate: review-before-dispatch`

3. **Multi-module or moderate architectural change**  
   → `HumanGate: review-before-merge`

4. **Normal feature work with clear tests**  
   → `HumanGate: review-before-merge`

5. **Trivial, single-file, low blast radius**  
   → `HumanGate: none`

SmartRouter may raise the gate higher than these defaults; the Host may never lower it.

---

### 4. Detailed Autonomous Loop (`HumanGate: none`)

```
1. Create isolation
   - If Isolation == worktree+branch → git worktree add -b sr/<task-id>/... 
   - Record mapping: task_id → {path, branch, profile, attempts: 0}

2. Inject Brief and start agent inside the worktree

3. Agent Implementation Phase
   - Agent works and runs acceptance checks
   - On success → go to step 5
   - On failure → go to step 4

4. Implementation Repair (max 1 TOTAL per original task — this is the one allowed repair)
   - attempts += 1
   - If attempts > 1 → escalate to needs-human
   - Send failure evidence + logs back to the same agent
   - Agent may try one more time (this consumes the single repair allowance)
   - If still failing → escalate (no further same-profile repair; CI failures later also escalate)

5. Create Pull Request
   - Push branch
   - Open PR with link to Brief and task_id

6. CI Phase
   - Watch CI
   - On success → go to step 8
   - On failure → go to step 7

7. CI Failure (no additional repair — the §4 allowance is already the one repair total)
   - On CI failure: if attempts == 0 (implementation needed no repair), the host may spend
     the single allowance here — send CI logs back to the same agent for one repair cycle
   - If attempts >= 1 (the allowance is consumed) → escalate to needs-human immediately
   - If the one repair still fails → escalate to needs-human
   - A further cycle needs a fresh, separately authorized task (counters still roll up)

8. Auto-merge Decision
   - All acceptance checks passed
   - CI green
   - No unresolved review comments
   - Branch up to date with base
   - Difficulty is trivial or moderate
   → Host may merge
   → Then delete worktree and branch

9. Cleanup
   - git worktree remove ...
   - Record final status in Outcome Ledger
```

---

### 5. Mostly-Autonomous Flow (`HumanGate: review-before-merge`)

Exactly the same as the autonomous loop above, **except**:

- Step 8 is replaced by:  
  "PR is green → notify human and wait."
- Human can:
  - Approve → Host merges and cleans up
  - Request changes → feedback goes to the same agent (ownership remains sticky)
  - Reject → task closed or re-routed

---

### 6. Escalation Rules (Force Human Immediately)

The Host **must** stop and mark the task `needs-human` when any of these occur:

- Repair allowance exhausted (max 1 same-profile corrective dispatch per original task total,
  implementation or CI — plan R01/R02/R03; a CI failure after a consumed implementation repair
  escalates with no second cycle)
- Budget or call limit defined in the Brief is exhausted
- Agent process crashes or becomes unresponsive
- SmartRouter re-evaluation raises the HumanGate
- Agent violates non-goals or touches forbidden paths
- Any high-risk signal appears (security, data loss, production impact, etc.)

**Escalation package** sent to the human must contain:
- Original Brief
- Full SmartRouter decision (including reasons)
- Complete attempt history + logs
- Current diff / PR URL
- Clear action options: Approve / Guide / Take over / Abort

---

### 7. Auto-Merge Conditions (Strict)

All of the following must be true:

- `HumanGate == none`
- Acceptance checks passed inside the worktree
- CI fully green
- Zero unresolved review comments
- Branch successfully rebased / merged with base
- Difficulty ∈ {trivial, moderate}
- Repository policy explicitly allows auto-merge for this class of task

Otherwise leave the PR open.

---

### 8. Audit Requirements

Every task must record:

- SmartRouter decision (Route, Isolation, HumanGate, Reason, Profile)
- Worktree path + branch
- Every agent attempt (timestamp, outcome, evidence)
- CI results
- Human decisions (if any)
- Final status + merge commit SHA (if merged)

---

### 9. Preventing Agent Loops (Critical Section)

Agent loops are one of the biggest risks in autonomous systems.  
The following hard limits are **mandatory**:

#### 9.1 Attempt Caps
- Maximum **1** same-profile corrective dispatch per original task **total** (implementation
  or CI, not each — plan R01/R02/R03; the Brief `attempts` field records this cap)
- A CI failure after the allowance is consumed escalates to `needs-human`; a further cycle
  needs a fresh, separately authorized task (all dispatches still roll up to the original task)
- Total attempts are also bounded by the `attempts` field in the Brief
- Counters are never reset by restarting the agent, renaming the branch, changing profiles,
  or escalating

#### 9.2 Budget Caps
- Cash and call limits in the Brief are hard ceilings
- Speculative sets share one budget; exceeding it cancels remaining candidates
- Host must reject any further dispatch once the limit is hit

#### 9.3 Progress Detection
The Host should detect lack of progress:
- Same failing tests after a repair attempt
- No meaningful file changes between attempts
- Repeated identical error messages

→ Treat as failure and escalate instead of allowing another loop.

#### 9.4 Ownership + Feedback Discipline
- Feedback always returns to the **same owner**
- The agent may not spawn new workers or change its own ownership
- Nested delegation is allowed only when explicitly permitted and still counts against the original budget

#### 9.5 Timeouts
- Each agent session should have a wall-clock timeout
- Unresponsive agents are killed and the task escalated

#### 9.6 Circuit Breaker
If a task class shows repeated autonomous failures (e.g. >30% escalation rate), the Host should temporarily raise the default HumanGate for that class until the issue is understood.

---

### 10. Summary

- Most tasks run with high autonomy.
- Humans are called only at high-leverage points (final review or real risk).
- SmartRouter sets the ceiling; the Host enforces it.
- Loops are prevented by strict attempt caps, budget caps, progress checks, timeouts, and a circuit breaker.
- Every action is fully audited.

This policy gives speed on routine work while keeping strong, selective human control and hard protection against runaway agent loops.

---

### How do we prevent agent loops?

We prevent loops with **layered hard limits**, not hope:

1. **Strict attempt caps** — only 1 same-profile repair total per original task (plan R01/R02/R03).
2. **Budget ceilings** — cash and call limits are never renewed.
3. **Progress detection** — if the agent makes no real progress, stop and escalate.
4. **Timeouts** — kill unresponsive sessions.
5. **Sticky ownership** — the same agent must fix its own work; it cannot endlessly re-delegate.
6. **Circuit breaker** — if a whole class of tasks keeps failing, temporarily reduce autonomy.

These rules turn potential infinite loops into finite, predictable escalations to a human.
