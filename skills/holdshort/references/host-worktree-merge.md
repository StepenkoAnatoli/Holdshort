# How the Agent Knows Which Worktree to Use & How to Merge After Acceptance

**Status:** background material — non-normative. It is the assignment-and-merge-lifecycle
continuation of [host-worktree-flow.md](host-worktree-flow.md) and
[host-worktree-agents.md](host-worktree-agents.md); the host-side worktree registry and
PR-URL visibility this flow relies on are covered in
[host-worktree-registry.md](host-worktree-registry.md); the `HumanGate` → host-behavior
mapping its flag 4 calls for is sketched in [host-hil-policy.md](host-hil-policy.md); the
normative contract remains
[gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md). Where this document and
the normative files ever disagree, **the normative files win**.

Flagged, not fixed (the document below is preserved as given):

1. **"Best practice: also inject the Brief" understates a normative Host duty.**
   spec-v2.md §11 (Host responsibility 4) *requires* the Host to inject the exact Brief (or
   SpeculativeSet) into the Worker's environment — injection is not optional. Only the
   well-known filename (`HOLDSHORT_BRIEF.json`, a host convention — see
   [host-worktree-flow.md](host-worktree-flow.md)) and any extra branch-name file are
   optional; the Brief already carries `branch-hint` (§10.1).
2. **"Every file operation, `git` command, and test … automatically happens in the correct
   isolated environment" overstates isolation.** Same flag as
   [host-worktree-flow.md](host-worktree-flow.md) and
   [host-worktree-agents.md](host-worktree-agents.md): relative operations resolve inside the
   worktree, but absolute paths, `..` traversal, environment variables and tool configs
   pointing at shared services, and running processes are not confined
   ([worktree-mechanics.md](worktree-mechanics.md), "What is *not* isolated"). Starting the
   process in the worktree is cooperative placement, not a sandbox.
3. **The `.sr-worktrees/a3f9` path is the inside-the-checkout form again** (see
   [host-worktree-agents.md](host-worktree-agents.md) flag 3 and
   [host-worktree-flow.md](host-worktree-flow.md) flag 1): the parent checkout must ignore
   `.sr-worktrees/`, or the `../` outside form avoids the untracked-content and
   recursive-scan pitfalls entirely.
4. **The merge step is not gated by `HumanGate`, and acceptance evidence has no stated
   destination.** When the decision carries `HumanGate: review-before-merge` (or
   `approval-required`), a human must approve before either merge step — the PR flow's
   "after approval + green CI" covers this, the standard flow omits it. Acceptance evidence
   (check commands, exit codes, output refs) should be recorded as a spec-v2.md §10.3
   Outcome in the Host's Outcome Ledger, and "deliberately abandoned" corresponds to
   `Outcome: cancelled` — abandoned work still consumes its dispatches. This document
   closes the create → use → merge → delete lifecycle but leaves Ledger and abandonment
   semantics open.

---

### 1. How the Agent Knows Which Worktree to Use

The agent does **not** choose the worktree itself.  
The **Host** decides and forces the agent to run inside it.

Here's the clean flow:

1. Holdshort outputs:
   ```
   Isolation: worktree+branch
   + Brief
   ```

2. The Host creates the worktree and branch:
   ```bash
   git worktree add -b sr/a3f9/auth-refactor .sr-worktrees/a3f9 main
   ```

3. The Host **starts the agent with that directory as its working directory**:
   ```bash
   cd .sr-worktrees/a3f9
   # launch Claude Code / Codex / Aider / etc. here
   ```

Because the agent's process is started **inside** the worktree, every file operation, `git` command, and test it runs automatically happens in the correct isolated environment. The agent doesn't need any special logic to "discover" the worktree — its current working directory *is* the worktree.

**Best practice:**  
Also inject the Brief (and optionally the branch name) into a well-known file inside the worktree (e.g. `HOLDSHORT_BRIEF.json`). This gives the agent explicit context about its task and ownership.

---

### 2. How to Merge After Acceptance

Once the agent finishes and the acceptance checks pass, the Host (or a human) performs the merge. The agent itself normally does **not** merge.

#### Standard Merge Flow

```bash
# 1. Make sure the agent's branch is up to date (optional but recommended)
cd .sr-worktrees/a3f9
git fetch origin
git rebase origin/main          # or merge, depending on your style

# 2. Run final verification inside the worktree
pytest ...                      # or whatever the acceptance contract requires

# 3. Switch to the main repository and merge
cd /path/to/main/repo
git checkout main
git pull
git merge sr/a3f9/auth-refactor

# 4. Clean up
git worktree remove .sr-worktrees/a3f9
git branch -d sr/a3f9/auth-refactor   # after the merge is successful
```

#### Alternative: Pull Request Flow (Recommended for teams)

Many Hosts prefer this safer pattern:

1. The agent (or Host) pushes the worktree branch:
   ```bash
   git push -u origin sr/a3f9/auth-refactor
   ```

2. A Pull Request is opened (manually or automatically).

3. CI runs on the PR.

4. After approval + green CI, the PR is merged into `main`.

5. The Host then removes the worktree:
   ```bash
   git worktree remove .sr-worktrees/a3f9
   ```

---

### Summary

| Question | Answer |
|---------|--------|
| How does the agent know which worktree to use? | It doesn't choose. The Host starts the agent **inside** the correct worktree directory. |
| Who merges? | Normally the Host (or a human via PR). The agent stays focused on implementing and verifying inside its isolation. |
| When is the worktree deleted? | Only after the branch has been successfully merged (or deliberately abandoned). |

This separation keeps the agent simple: it just works in whatever directory it was launched in. All worktree lifecycle management (create → use → merge → delete) stays with the Host.

**v3.0 autonomy default:** a human checkpoint shown in this example applies only
when explicitly requested by the user. Otherwise `HumanGate` is `none`; the Host
verifies and completes authorized work autonomously. Failed eligibility or exhausted
limits yield a recorded automatic stop, not a human approval prompt (spec-v2.md §8.2).
