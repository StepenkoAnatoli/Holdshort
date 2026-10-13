# Example: One `delegate` task end to end — decision to ledger outcome

**Status:** worked example — non-normative. The normative contract is [gates.md](gates.md)
(fixture-pinned) and [spec-v2.md](spec-v2.md); where this example and the normative files
ever disagree, **the normative files win**. Unlike the sibling examples (which flag their
abbreviated decision blocks), the decision and Brief below are shown **complete** per
spec-v2.md §9/§10.1, so this file doubles as the shape reference for what "complete"
means. Task id `9d4e2f1a` follows [host-task-id.md](host-task-id.md) (8-hex secrets mint,
not the `a3f9` short form). Executable twins of each host step:
[../../../tools/task_ids.py](../../../tools/task_ids.py),
[../../../tools/host_dry_run.py](../../../tools/host_dry_run.py) (the whole lifecycle,
two workers at once), [../../../tools/check_provenance.py](../../../tools/check_provenance.py),
[../../../tools/outcome_ledger.py](../../../tools/outcome_ledger.py),
[../../../tools/class_breaker.py](../../../tools/class_breaker.py).

## Scenario

> "Implement a caching layer for the product catalog (Redis + in-memory backends),
> wire the configuration system, and add tests. Do not touch payment or order modules."

Gate 5 rejects `direct` (multi-module blast radius, parallel-work risk, verification needs
a clean checkout) and the decision is `delegate` with `worktree+branch`.

## 1. Decision (complete §9 block)

```
Difficulty:        high-or-ambiguous
Route:             delegate
Profile:           (main-host, anthropic, claude-sonnet-5-5@2026-10-01, cfg-tools-v1)
Isolation:         worktree+branch
IsolationReason:   multi-module change with shared-state risk and need for clean test runs
Owner:             worker
HumanGate:         review-before-merge
NestedAllowed:     no
MaxNestingDepth:   1
Reservations:      work $0.31 + review $0.06 all-in, within $1.00 task cap
Calls:             0 used / 4 approved
Deadline:          2026-10-12T12:00:00Z (starts on dispatch; equality expires)
Uncertainty:       [redis test double availability in CI]
```

## 2. Brief (§10.1, verbatim into the worker's environment)

```json
{
  "objective": "Catalog caching layer (Redis + in-memory), config wiring, tests",
  "acceptance": {"checks": [
    {"command": "pytest tests/catalog/test_cache.py -q", "expect": "exit 0"}
  ]},
  "sources": ["docs/catalog-layout.md", "src/catalog/__init__.py:1-40"],
  "permitted-effects": ["src/catalog/cache/", "src/catalog/config.py", "tests/catalog/test_cache.py"],
  "non-goals": ["no payment/order edits", "no schema migration", "no recursive delegation"],
  "isolation": "worktree+branch",
  "branch-hint": "sr/9d4e2f1a/caching-layer",
  "allowance": {"cash": 1.0, "calls": 4, "deadline": "2026-10-12T12:00:00Z"},
  "attempts": 1,
  "stop-triggers": ["verification failure → repair-or-escalate", "budget exhausted → escalate"],
  "ownership": "worker",
  "nested-allowed": false,
  "max-nesting-depth": 1
}
```

Full brief workflow: [brief-and-result.md](brief-and-result.md).

## 3. Host spawns the worker

```bash
TASK_ID="$(python tools/task_ids.py --mint)"          # e.g. 9d4e2f1a (uniqueness-checked)
BRANCH="sr/${TASK_ID}/caching-layer"
git worktree add -b "$BRANCH" "../.sr-worktrees/${TASK_ID}" main   # outside form
cp brief.json "../.sr-worktrees/${TASK_ID}/SMARTROUTER_BRIEF.json" # exact Brief, untracked;
# `SMARTROUTER_BRIEF.json` is a host filename convention, not normative — spec-v2 §11
# requires injecting the exact Brief and names no file
cd "../.sr-worktrees/${TASK_ID}" && launch-agent-here
```

Flow reference: [host-worktree-flow.md](host-worktree-flow.md); id semantics:
[host-task-id.md](host-task-id.md).

## 4. Worker + verification (inside the worktree only)

The worker edits `src/catalog/cache/*`, extends `src/catalog/config.py`, writes
`tests/catalog/test_cache.py`, commits on its branch, and runs the acceptance contract:

```bash
cd "../.sr-worktrees/9d4e2f1a"
pytest tests/catalog/test_cache.py -q     # exit 0, observed — self-report is unverified (plan S10)
```

A failure returns to the **same** worker as a new brief (sticky ownership, at most one
same-profile repair per R01/R02/R03); a second cycle needs a fresh authorized task.

## 5. PR, HumanGate, and review

The host pushes `sr/9d4e2f1a/caching-layer` and opens the PR. `HumanGate:
review-before-merge` pauses the loop: a human approves, and the reviewer runs the
provenance check from
[../../smart-router-review/references/isolation-provenance.md](../../smart-router-review/references/isolation-provenance.md):

```bash
python tools/check_provenance.py --repo . --task-id 9d4e2f1a \
  --branch sr/9d4e2f1a/caching-layer --permitted src/catalog/cache/ \
  --permitted src/catalog/config.py --permitted tests/catalog/test_cache.py
# PROVED sr/9d4e2f1a/caching-layer touches only […]: src/catalog/cache/redis.py, …
```

## 6. Merge, Outcome, ledger, cleanup

```bash
git checkout main && git merge --no-ff sr/9d4e2f1a/caching-layer
python tools/outcome_ledger.py record --ledger outcome-ledger.jsonl --task-id 9d4e2f1a \
  --outcome accepted --owner worker \
  --check "pytest tests/catalog/test_cache.py -q:0:ci-run-4821" --spend 0.35 \
  --file src/catalog/cache/redis.py --file tests/catalog/test_cache.py \
  --note "PR #NN, human-approved" --fingerprint sha256:of-brief --class catalog
python tools/class_breaker.py record --ledger eval-facts.jsonl \
  --task-id 9d4e2f1a --class catalog --outcome accepted
git worktree remove "../.sr-worktrees/9d4e2f1a"
git branch -d sr/9d4e2f1a/caching-layer
python tools/outcome_ledger.py verify --ledger outcome-ledger.jsonl
```

The stored line is a §10.3 Outcome (`task-id`, `outcome: accepted`, `evidence{checks,
actual-spend, files-touched, notes}`, `owner-profile`, plus fingerprint/class extras).
On a later failure the host supplies that Outcome as `PreviousResult` and SmartRouter
re-routes (refined brief, escalation, or `blocked`) — SmartRouter stays stateless; the
host owns the ledger (spec-v2.md §8.5/§11).
