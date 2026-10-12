# How to Use Worktrees in SmartRouter

**Status:** background material — non-normative. It explains the host-side operational flow
behind the `worktree+branch` isolation level; the normative contract remains
[gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md). Where this document and
the normative files ever disagree, **the normative files win**. It is the operational
companion to [worktree-mechanics.md](worktree-mechanics.md), which explains the git
mechanism itself. An agent-focused variant of the same flow lives in
[host-worktree-agents.md](host-worktree-agents.md); how the worktree assignment is made and
how the branch is merged and cleaned up afterwards:
[host-worktree-merge.md](host-worktree-merge.md). Host bookkeeping (which worktree belongs to
which task, PR-URL visibility):
[host-worktree-registry.md](host-worktree-registry.md).

Flagged, not fixed (the document below is preserved as given):

1. **Worktree location, internal inconsistency.** The prose rule says "outside the main
   working directory" and the shell example uses `../.sr-worktrees/${TASK_ID}`, but the
   pseudo-code uses `.sr-worktrees/{task_id}` — *inside* the working directory. The outside
   form is the correct reading: a nested worktree appears in the parent checkout's untracked
   files and can be swept up by recursive tooling. Hosts should use the `../` form. (The agent-focused variant
   [host-worktree-agents.md](host-worktree-agents.md) adopts the inside form throughout;
   see its flag 3 for the conditions that make it safe.)
2. **"Guarantees the results reflect only that worker's changes" overstates worktree
   isolation.** Per [worktree-mechanics.md](worktree-mechanics.md) ("What is *not*
   isolated"), databases, ports, `.env` files / secrets, ignored dependencies and running
   processes are shared. Verification inside the worktree isolates the worker's *tracked
   checkout* only; shared services can still contaminate results.
3. **`SMARTROUTER_BRIEF.json` is a suggested host-side filename convention, not normative.**
   spec-v2.md §10.1 defines the Brief schema and §11 (Host responsibility 4) requires the
   Host to "inject the exact Brief (or SpeculativeSet) into each Worker's environment" — but
   names no file. Any mechanism that delivers the Brief verbatim satisfies the contract.

---

SmartRouter itself **never creates** worktrees.  
It only *recommends* isolation. The **Host** is responsible for actually creating and managing them.

Here's the complete practical flow:

### 1. SmartRouter Recommends Isolation

When the task is risky enough (multi-file changes, parallel work, high blast radius, etc.), SmartRouter will output something like:

```
Route:             delegate
Isolation:         worktree+branch
IsolationReason:   multi-module change with shared-state risk
Owner:             worker
```

Plus a machine-readable `Brief`.

### 2. Host Creates the Worktree

When the Host sees `Isolation: worktree+branch`, it must:

```bash
# Example Host-side commands
TASK_ID="a3f9"
BRANCH="sr/${TASK_ID}/caching-layer"
WORKTREE_PATH="../.sr-worktrees/${TASK_ID}"

git worktree add -b "$BRANCH" "$WORKTREE_PATH" main
```

Key points:
- Create a **new branch** for the worker (recommended naming: `sr/<task-id>/<short-slug>`).
- Put the worktree **outside** the main working directory.
- The new directory now has its own clean checkout of the files.

### 3. Inject the Brief and Start the Worker

```bash
# Write the exact Brief into the worktree
cp brief.json "$WORKTREE_PATH/SMARTROUTER_BRIEF.json"

# Start the chosen agent profile inside that directory
cd "$WORKTREE_PATH"
# (launch Claude Code / Codex / whatever profile was chosen)
```

The worker now operates only inside its isolated directory and branch.

### 4. Run Verification Inside the Worktree

All tests and checks should be executed **from inside the worktree**:

```bash
cd "$WORKTREE_PATH"
pytest tests/catalog/ -q
```

This guarantees the results reflect only that worker's changes.

### 5. Handle Feedback and Cleanup

- Verification failures or review comments are sent back to the **same worker** (ownership is sticky).
- When the work is accepted and merged, the Host should clean up:

```bash
git worktree remove "$WORKTREE_PATH"
# optionally delete the branch after merge
```

---

### Minimal Host Pseudo-code

```python
def spawn_worker(decision):
    if decision["Isolation"] == "worktree+branch":
        task_id = generate_id()
        branch = f"sr/{task_id}/{slugify(decision['Brief']['objective'])}"
        path = f".sr-worktrees/{task_id}"

        subprocess.run([
            "git", "worktree", "add", "-b", branch, path, "main"
        ], check=True)

        # Inject brief
        write_json(f"{path}/SMARTROUTER_BRIEF.json", decision["Brief"])

        # Start agent in that directory
        start_agent(profile=decision["Profile"], cwd=path)

        return {"task_id": task_id, "path": path, "branch": branch}
```

---

### Summary

| Step | Who does it | What happens |
|------|-------------|--------------|
| Decide isolation | SmartRouter | Outputs `Isolation: worktree+branch` |
| Create worktree + branch | Host | `git worktree add -b ...` |
| Inject Brief | Host | Writes the exact brief into the worktree |
| Run agent | Host | Starts the profile inside the worktree |
| Verify | Host / Worker | Runs checks only inside the worktree |
| Feedback | Host | Returns results to the same owner |
| Cleanup | Host | `git worktree remove` after merge |

SmartRouter only says *when* and *how strong* the isolation should be.  
The Host is the one that actually runs the `git worktree` commands.
