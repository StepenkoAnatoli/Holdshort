# Autonomous Host Policy — HITL only on explicit request

Status: explanatory host companion. The normative homes are [gates.md](gates.md)
and [spec-v2.md](spec-v2.md) §8.2. The user directive of 2026-10-13 changes the
default; historical risk-based human checkpoints are superseded.

## 1. Default

Run authorized tasks autonomously. Set `HumanGate` to `none` unless the user
explicitly asks for human involvement in that task or project. Store that request
with its source; a model-generated risk label or eval table is not a user request.

Risk still informs isolation and verification. Unknown permissions, missing
acceptance checks, exhausted allowances, or unsafe recovery mean `blocked`.
Produce the evidence record and stop automatically; do not manufacture an approval
question, silently weaken a gate, or transfer ownership.

## 2. HumanGate → Concrete Host Behavior

| HumanGate | Host behavior | Applies when |
| --- | --- | --- |
| `none` | Work, checks, one bounded repair, eligible merge and cleanup within authorization | Default |
| `review-before-dispatch` | Prepare the Brief and isolation; wait before launching | User explicitly requested pre-launch review |
| `review-before-merge` | Work and verify; wait before merging | User explicitly requested merge review |
| `approval-required` | Prepare evidence; wait before the named effect | User explicitly requested approval |

## 3. Autonomous lifecycle

1. Collect current identity, permission, capability, verifier, price and accounting
   inputs. Apply the five gates. A blocked route starts no worker.
2. Create the required isolation and inject the exact Brief. The filename
   `SMARTROUTER_BRIEF.json` is a Host convention, not a normative schema field.
3. The owning worker implements and runs the acceptance contract. Required checks
   run as observed commands; self-reported success is unverified.
4. A failure returns to the same owner. At most one same-profile repair total is
   available under the original allowance (R01/R02/R03); implementation, CI and
   review feedback share it. Never renew counters by restart, rename or escalation.
5. A repeated failure, no progress, expired deadline, exhausted cap, or forbidden
   effect stops automatically with a redacted `blocked` evidence package. The Host
   may request a fresh eligible routing decision using the recorded Outcome;
   it cannot launch an unpriced, unauthorized or unqualified fallback.
6. After observed acceptance and required CI, the Host performs the authorized
   merge and cleanup. A human merge checkpoint exists only on explicit request.

## 4. Executable supervisor

`tools/host_watchdog.py` wraps one command per invocation. Default exit codes:
0 successful command, 1 one corrective dispatch granted, 2 terminal automatic
stop, 3 invalid configuration. The Host consumes a repair grant exactly once.
Terminal reasons persist in the state file and refuse later launches for that task,
including when the caller no longer supplies the original stop signal.

The default terminal package has `status: blocked`, `human_requested: false`
and an empty action menu. It retains the Brief, decision, history, log and diff/PR
references. Logs are redacted before state/package persistence and before output.

`--human-requested` is supplied only from an explicit user instruction. In that
mode a terminal package has `status: needs-human` and the optional human action
menu. To enforce an explicitly requested pre-dispatch checkpoint, the Host also
passes `--gate-raised`; the command is not launched.

Timeouts stop the supervised command. Descendant process-tree cleanup, crash-safe
cash/call reservations, fresh model identity and end-to-end agent dispatch remain
Host responsibilities; a policy verdict alone does not establish those guarantees.

For dispatcher accounting, load the current
[host compatibility amendment](../../../docs/DISPATCH_ACCOUNTING.md#host-compatibility-amendment--2026-10-16)
before resuming a persisted pilot. Preserve terminal abandonment and reservation
identities. `dispatch-unsettled` is return-only recovery evidence, not a journal
append or permission to resend; a pending mirror does not prove a failed send.
An unknown canonical decision stops automatically with a contract finding.

## 5. Class statistics

`tools/class_breaker.py` records facts per task and recomputes rates only under
the separately authorized eval protocol. `gate` defaults to `none`; a published
human gate is applied only with `--human-requested`. A statistic cannot opt a user
into HITL. Evaluation authorization and permission to spend remain separate inputs.
