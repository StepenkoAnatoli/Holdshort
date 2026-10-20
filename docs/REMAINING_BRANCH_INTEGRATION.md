# Remaining branch integration — 14 October 2026

The remaining gap-closure branch is integrated with current `main`. Its commit
titles describe broader work than its actual diff: it does not include budget
reservations, persistent pilot spending, or a monotonic dispatcher clock.
Those capabilities are not claimed by this integration.

## Resulting behavior

- Corrupt, unreadable, or invalid task state blocks dispatch. The original file
  stays intact, no replacement counters are written, and the refusal records
  an unknown attempt number as `null`. Only a missing file starts a new task.
- State counters must be nonnegative numbers of the expected type. Task identity
  must match the requested task. Unsupported clock domains block resumption.
- Worker creation can require a shared-resource declaration. Port conflicts and
  invalid declarations refuse creation before any branch or worktree is made.
- Launch checks bind the declaration to the requested task, branch, and worktree;
  a truthy string or unrelated registry record cannot authorize the launch.
- The original local snapshot's redaction layer protects ledger and task-state
  writes. Reasons are redacted before truncation. The text filter also covers
  common UTF-16 logs and refuses unsupported or ambiguous byte encodings.
- CI pins twelve canonical policy sentences and tests a reproducible route-score
  harness. Harness tests are not live-model qualification evidence.

## Optional shared-resource checks

For a task that edits files without touching a shared mutable service, add these
arguments to the existing `spawn_worker.py spawn` command:

```bash
--no-shared-surface --require-shared-plan
```

For a task that uses a service, describe its resources instead:

```bash
--shared-plan '{"env_scope":"task-a","ports":[18080],"namespace":"task-a"}' --require-shared-plan
```

Then include `--registry PATH --require-shared-plan` in the corresponding
`guard_launch.py` invocation, alongside its task ID and exact branch. This is
an execution eligibility check; it does not introduce a human checkpoint.

These declarations are host assertions. Port checks compare declarations in
one registry; they do not bind sockets, reserve external services, validate
environment isolation, or lock simultaneous registry updates. Hosts still own
those controls.

## Preserved original work

The redaction module and its writer tests originate from local snapshot
`d9645140767684f6db629c953b8937fb656f086b`, with encoding coverage and integration
adjustments added here. Its older structured watchdog API is retained on the
snapshot branch because the current command supervisor already implements the
relevant repair and autonomous-stop behavior. Replacing that supervisor with the
older API would regress the current contract.

## Remaining gaps

Live dispatch still needs budget reservation before transport and a shared,
persistent pilot-spend authority (issues #47 and #48). Recovery of invalid task
state requires an authoritative reconciliation procedure; this integration
stops safely rather than inventing repaired counters. Wall-clock steps and
simultaneous state/registry writers remain host integration risks.

Holdshort was applied to this integration as an advisory routing policy:
additional automatic provider dispatch remains blocked on missing host identity,
qualification, reservation, and accounting evidence. HumanGate is `none`; the
existing user-directed coding session continued. No additional provider trial
or dollar-savings claim was created.

Acceptance checks include corrupt-state egress refusal, preservation of original
bytes, unknown counter reporting, rejected-spawn cleanup, registry binding,
malformed score rejection, writer redaction, and UTF-16 filtering. The full
staged regression gate and GitHub checks are required before merge.
