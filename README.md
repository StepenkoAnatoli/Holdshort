# SmartRouter

**Clear model choices for coding tasks, with verification and limits built in.**

SmartRouter helps a coding agent decide which model is suitable for a task, when to
delegate work, and when to stop. It checks whether a model can do the job safely and
within the available budget before comparing eligible options.

This repository provides the routing policy, local host tools, and validation
fixtures. The application that runs the agent—the **host**—connects those decisions
to actual model calls, permissions, billing, and project state.

[Getting started](#getting-started) · [How it works](#how-it-works) ·
[Local example](#try-the-local-supervisor) · [Current limits](#current-status-and-limits) ·
[Documentation](#documentation)

> **Current status:** the v3.0 routing policy and local tools are available.
> Live-provider routing remains experimental, with known accounting and recovery
> gaps. Start with the local checks below; they do not call a model provider.

## Why use SmartRouter?

Different coding tasks need different capabilities. A small edit, a difficult
debugging session, and a change involving private data should not be routed using
difficulty or price alone.

SmartRouter makes those decisions explicit:

- **Check eligibility first.** Permissions, tools, verification, and budget must
  pass before price or convenience can influence the choice.
- **Keep ownership clear.** Delegated work receives a defined task and acceptance
  checks, preferably in its own Git worktree and branch.
- **Limit recovery.** A task gets at most one repair under its original allowance
  (R01/R02/R03). Repeated failures and exhausted limits produce a recorded stop.
- **Make decisions inspectable.** Record the route, reasons, verification evidence,
  and accounting gaps rather than treating a model's confidence as proof.

## How it works

![SmartRouter checks permissions, capabilities, verification, budget, and economics in that order. A failed check blocks the candidate.](docs/assets/routing-overview.svg)

SmartRouter applies five checks, in order, to each candidate **model profile**.
A profile identifies a model together with the tools, settings, and qualification
evidence needed to use it.

| Check | Beginner explanation |
| --- | --- |
| 1. Permissions and privacy | Is this model allowed to receive the data and perform the requested action? |
| 2. Capabilities | Does the profile have the required tools, tested abilities, and enough context capacity? |
| 3. Verification | Are the acceptance checks defined and available before work begins? |
| 4. Affordability | Does the conservative cost of work **and verification** fit the remaining money, calls, and time? |
| 5. Economics | Among eligible options, which route is justified after coordination and review costs are included? |

Missing required evidence blocks a candidate. A cheaper model cannot bypass a
failed check. When no candidate is eligible, the result is `blocked`.

The policy returns one of five routes:

| Route | Meaning |
| --- | --- |
| `direct` | Recommend handling the task with an eligible current profile. |
| `delegate` | Recommend assigning one bounded task to an eligible isolated worker. |
| `speculative` | Recommend bounded parallel exploration when the host has explicitly enabled it and the policy conditions pass. |
| `recommend-escalation` | Recommend another eligible profile when direct work is unsuitable. |
| `blocked` | Stop because a required condition is missing or has failed. |

The [canonical skill](skills/smart-router/SKILL.md) defines the decision procedure.
The [host contract](skills/smart-router/references/spec-v2.md) defines the objects
and responsibilities an integration must implement.

## Autonomous by default

The v3.0 policy runs authorized tasks without routine human checkpoints.
**Human-in-the-loop (HITL) involvement is opt-in:** a human gate is enabled only
when the user explicitly requests it for the task or project.

The default is `HumanGate: none`. The local supervisor stops automatically when a
deadline expires, a limit is exhausted, progress stalls, or a forbidden effect is
reported. It writes a redacted `blocked` evidence package with no approval menu.
Terminal stops remain in the task's state file across restarts.

For an explicitly requested human checkpoint, the host passes `--human-requested`.
That enables a `needs-human` package. A requested pre-dispatch stop also uses
`--gate-raised`. The host must retain the user's request and its source across
invocations. Human involvement does not waive eligibility or budget checks.

See the [autonomous host policy](skills/smart-router/references/host-hil-policy.md)
for the lifecycle and optional human gates.

## Getting started

### 1. Prepare your environment

You need Git, Python, and Bash. The GitHub workflow uses **Python 3.12**.
On Windows, use Git for Windows with Git Bash available on `PATH`.
The commands below assume `python` selects the intended interpreter; on systems
where it is named `python3`, substitute that command.

### 2. Clone the repository and run the policy checks

```bash
git clone https://github.com/StepenkoAnatoli/SmartRouter.git
cd SmartRouter
python tools/validate_skills.py --strict
python tests/smart_router_decisions.py
```

These validate the skill packaging and deterministic routing fixtures. A passing
fixture suite verifies the documented cases; it does not qualify a live model or
demonstrate real-provider savings.

### 3. Enable contributor checks

In a fresh clone, install the repository's commit hook and run the complete gate:

```bash
python tools/install_hooks.py
python tools/run_regression.py
```

The installer sets this clone's `core.hooksPath` to `.githooks`. Each subsequent
commit runs the gate against the content being committed and refuses on failure.
The gate includes local credential and application-store checks; an untriaged
finding can stop a commit. Keep credentials out of tracked files.

For the extended onboarding proof in a **clean checkout**, run:

```bash
bash tools/setup_machine.sh
```

That script exercises temporary commit/refusal proofs and local preflight checks.
It changes the clone's Git configuration, including its local author identity for
the proof. Use a fresh clone for this path and set your intended Git author
identity before contributing. The checks do not authorize live spending.

## Try the local supervisor

This example runs a harmless Python command under the supervisor. It needs no API
key and makes no model call. Use a new task ID and state path for a new task:

```bash
python tools/host_watchdog.py --task-id readme-demo --state .local/readme-demo/state.json --timeout 10 -- python -c "print('SmartRouter local example completed')"
```

The supervisor records the attempt in `.local/readme-demo/state.json`. If the
command succeeds, it exits with code `0`.

| Exit code | Meaning |
| --- | --- |
| `0` | The supervised command succeeded. The host still owns the task's full acceptance checks. |
| `1` | One corrective attempt is granted within the original allowance. The host decides and performs the repair. |
| `2` | Terminal stop: `blocked` by default, or `needs-human` when explicitly requested. |
| `3` | Invalid configuration or unreadable state; execution is refused. |

This tool supervises one command per invocation. A host integration must supply
current budget counters and enforce model dispatch, reservations, and descendant
process cleanup. The example is a local supervision demonstration.

## Use SmartRouter in a coding-agent host

The repository contains three skills:

| Skill | Purpose |
| --- | --- |
| [smart-router](skills/smart-router/SKILL.md) | Make the routing recommendation for a task or dispatch decision. |
| [smart-router-review](skills/smart-router-review/SKILL.md) | Review a result against its acceptance contract and provenance. |
| [smart-router-eval-prep](skills/smart-router-eval-prep/SKILL.md) | Prepare an evaluation protocol before separately authorized model trials. |

To integrate them, configure your host to read the canonical skill and provide its
required inputs: authorized data and actions, exact model profiles, fresh
qualification evidence, acceptance checks, price bounds, and remaining allowances.
The host then executes eligible decisions and records outcomes.

Cloning this repository does not install the skills into an agent or switch its
running model. Provider setup and dispatch adapters belong to the host integration.
The [worktree guide](skills/smart-router/references/host-worktree-flow.md) explains
isolated delegation; the [lifecycle example](skills/smart-router/references/example-lifecycle.md)
shows how the pieces fit together.

## Current status and limits

The project has a validated policy, deterministic fixtures, local lifecycle
tools, and a completed local pilot report. Live-provider comparisons and consumer
adoption require their own evidence. The current **policy version is v3.0**;
older release tags describe the snapshots published at those tags.

The [October 13 review](docs/SMARTROUTER_USAGE_REVIEW_2026-10-13.md) records these
important open implementation gaps:

- The existing live dispatcher can send before enforcing remaining cost headroom.
- Pilot spending resets with a new dispatcher instance instead of being shared persistently.
- Corrupt persisted task state can reset counters instead of blocking or reconciling.

These gaps prevent treating the current live dispatcher as a dependable spending
boundary. The review also covers process-tree cleanup, shared-state coordination,
stream encodings, host qualification, and integration evidence.

Observed GPT usage is stored in a [metadata snapshot](docs/evidence/2026-10-13/usage-snapshot.json).
It is cumulative session telemetry, not a final bill or proof of savings. Cached
input is included in input totals; reasoning output is included in output totals.
Unknown dollar cost remains unknown.

## Documentation

| Start here when you want to… | Read |
| --- | --- |
| Understand the exact routing rules | [Canonical skill](skills/smart-router/SKILL.md) and [eligibility gates](skills/smart-router/references/gates.md) |
| Build a host integration | [Host contract and schemas](skills/smart-router/references/spec-v2.md) |
| Understand autonomous stops and optional HITL | [Host policy](skills/smart-router/references/host-hil-policy.md) |
| Inspect observed use, bugs, and GPT usage | [Engineering review](docs/SMARTROUTER_USAGE_REVIEW_2026-10-13.md) |
| Review the local pilot and its limits | [Pilot report](docs/PHASE4_PILOT_REPORT.md) |
| Trace milestones and historical releases | [Project completion record](docs/PROJECT_COMPLETION.md) |
| Handle credential rotation and custody checks | [Credential runbook](docs/CREDENTIAL_ROTATION_RUNBOOK.md) |
| Read the original roadmap and source survey | [Development plan](docs/DEVELOPMENT_PLAN.md) and [routing survey](docs/ROUTER_SURVEY.md) |

## Contributing

Work on a feature branch, define acceptance checks before implementation, and run
the local gate before pushing. Open a pull request against `main`; GitHub runs the
regression gate and watcher proof. Merge only after the required checks pass
against the current base. Keep project-specific consumer code and credential
inventories in their own repositories.

See [LICENSE](LICENSE) for the license grant and its stated scope.
