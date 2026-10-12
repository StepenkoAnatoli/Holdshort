# How the Host Knows Which Worktree to Use & Whether the Agent Knows the PR URL

**Status:** background material — non-normative. It is the host-bookkeeping companion to
[host-worktree-flow.md](host-worktree-flow.md), [host-worktree-agents.md](host-worktree-agents.md)
and [host-worktree-merge.md](host-worktree-merge.md); the normative contract remains
[gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md). Where this document and
the normative files ever disagree, **the normative files win**.

Flagged, not fixed (the document below is preserved as given):

1. **The in-memory `workers` dict is bookkeeping, not the Outcome Ledger.** spec-v2.md §11
   (Host responsibility 8) requires an **auditable** Outcome Ledger (§8.5: the Host owns it).
   A plain in-memory mapping is lost on restart and proves nothing; the
   `task_id → worktree/branch` record should persist in the same host state that records
   §10.3 Outcomes. Also, `status` must be derived from observable facts (checks actually run,
   PR/CI state, acceptance results — see [brief-and-result.md](brief-and-result.md)), never
   from the worker's self-report.
2. **"Agent creates the PR" is not a free neutral option.** Pushing a branch and opening a PR
   are side effects beyond editing the checkout: Gate 1 ([gates.md](gates.md)) covers
   permitted actor/provider/destination/effects and any transmission, and the Brief's
   `permitted-effects` (spec-v2.md §10.1) bounds what the worker may touch. Whether the
   worker may run `gh pr create` is a host authorization decision recorded in the brief, not
   a default.
3. **Review comments must reach the Owner regardless of PR-URL visibility.** spec-v2.md §7
   and Host responsibility 6: verification failures, CI failures and review comments
   **always** return to the current Owner as a new brief. Sharing the PR URL is only one
   delivery mechanism; a host-managed PR does not exempt the host from routing feedback to
   the worker.
4. **The `.sr-worktrees/{task_id}` path is the inside-the-checkout form again** (see
   [host-worktree-agents.md](host-worktree-agents.md) flag 3,
   [host-worktree-merge.md](host-worktree-merge.md) flag 3 and
   [host-worktree-flow.md](host-worktree-flow.md) flag 1), and the
   `git worktree add -b branch worktree_path main` line is illustrative pseudo-code (bare
   identifiers, not runnable shell).

---

### 1. How the Host Knows Which Worktree to Use

The Host is the one that **creates** the worktree, so it already knows the mapping.

Typical pattern used by good Hosts:

```python
# When spawning the worker
task_id = "a3f9"
branch = f"sr/{task_id}/auth-refactor"
worktree_path = f".sr-worktrees/{task_id}"

git worktree add -b branch worktree_path main

# Store the mapping
workers[task_id] = {
    "path": worktree_path,
    "branch": branch,
    "profile": "...",
    "status": "working",
    "pr_url": None          # filled later
}
```

Later, whenever the Host needs to interact with that worker (send feedback, run final checks, clean up, etc.), it simply looks up the `task_id` in its own table and gets the correct `worktree_path`.

**The Host never has to guess** — it created the worktree and keeps the record.

---

### 2. Does the Agent Know the PR URL?

**By default: No.**

The agent usually does **not** know the PR URL unless the Host explicitly tells it.

#### Common patterns:

| Approach | Does the agent know the PR URL? | When it is used |
|---------|----------------------------------|-----------------|
| **Host-managed PR** (most common) | No | Host creates the PR after the agent finishes. Agent stays focused on code. |
| **Agent creates the PR** | Yes | Agent runs `gh pr create` (or equivalent) itself and receives the URL in the command output. |
| **Host injects the URL later** | Yes (after the fact) | Host creates the PR, then sends a message to the agent: "Your PR is at https://..." |

#### Recommended practice in SmartRouter-style systems

- Let the **Host** (or a later automation step) create the Pull Request.
- Keep the agent focused on implementing + verifying inside its worktree.
- Only inform the agent of the PR URL if it needs to respond to review comments directly.

If you want the agent to be aware of the PR, the Host can simply send it a message after the PR is opened:

```text
Your pull request is ready:
https://github.com/org/repo/pull/1234

Please address any review comments that appear on this PR.
```

---

### Summary

| Question | Answer |
|---------|--------|
| How does the Host know which worktree to use? | It created it and stores the mapping (`task_id → worktree_path + branch`). |
| Does the agent know the PR URL? | Not by default. Only if the Host (or the agent itself) explicitly creates/shares it. |

The cleanest design keeps worktree management and PR creation under the Host's control, while the agent just works inside the directory it was launched in.
