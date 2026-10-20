# Isolation-provenance check — did the diff come from its claimed worktree+branch?

Supplies the provenance evidence-record structure for `holdshort-review`, alongside
[blocked-review.md](blocked-review.md). Pinned sources: spec-v2.md §6 (isolation lower
bound), §10.1 (Brief `permitted-effects`, `branch-hint`), §11 (Host duties 3–4, 8);
[brief-and-result.md](../../holdshort/references/brief-and-result.md) (sticky ownership,
derived status); [host-task-id.md](../../holdshort/references/host-task-id.md) (id
semantics). Executable form:
[../../../tools/check_provenance.py](../../../tools/check_provenance.py) — the tool is
the specification where prose is ambiguous.

## The reviewer's question

A worker that owned a brief in `sr/<task-id>/<slug>` must have produced a diff that comes
from **that** branch and touches **only** permitted-effects paths. Anything else is a
blocker in one of two categories:

| Observation | Category | Why it blocks |
| --- | --- | --- |
| Branch not named `sr/<task-id>/<slug>` for the brief's task, or task id invalid | Required check | Provenance unprovable — no host naming rule binds this diff to the brief |
| Diff touches files outside `permitted-effects` | Safety / permission | Possible unauthorized effect (Gate 1); scope refused at review, not excused by intent |
| `--base` not an ancestor of the branch (re-homed diff) | Required check | Diff window hides provenance — the merge-base must be the claimed base |
| Live worktree path not on the claimed branch | Required check | Work happened outside the claimed isolation, or the claim is stale |

## Procedure

1. Demand the triple: task id, branch, base (default `main`), plus the brief's
   `permitted-effects` prefixes. Missing triple = unresolved, not approval.
2. Run `tools/check_provenance.py --repo … --task-id … --branch … --permitted …`
   (add `--worktree …` while the worktree is live, `--merge-commit …` after the merge).
3. Exit 0 (`PROVED`) is source-inspection-level evidence for the record: quote the file
   list. Exit 1 (`VIOLATION`) is a blocking record naming the offenders. Exit 2
   (`FAIL-CLOSED`: branch absent, git unreadable) is `unresolved` — absence is never clean.
4. Record per [blocked-review.md](blocked-review.md): ID, category (table above),
   severity, revision, evidence (tool command + output), correction (re-scope the diff or
   re-do the work in the claimed isolation), disposition.

## Hard rules

- A clean `git status` in the wrong directory proves nothing; only the branch-anchored
  diff counts.
- The tool checks structure, not authorship: green provenance plus sticky-ownership
  evidence (same owner received all feedback per
  [brief-and-result.md](../../holdshort/references/brief-and-result.md)) together close
  the loop. Either alone is insufficient.
- Never waive a scope violation through disclosure — a disclosed extra file is still a
  blocker until the brief's `permitted-effects` are amended by a fresh decision.
