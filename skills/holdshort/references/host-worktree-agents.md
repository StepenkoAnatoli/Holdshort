# How to Use Worktrees in Holdshort for Agents

**Status:** background material — non-normative. It is the agent-focused variant of the
host-side operational flow in [host-worktree-flow.md](host-worktree-flow.md); the normative
contract remains [gates.md](gates.md) (fixture-pinned) and [spec-v2.md](spec-v2.md), and the
git mechanism itself is explained in [worktree-mechanics.md](worktree-mechanics.md). The
assignment and merge lifecycle that follows this flow is covered in
[host-worktree-merge.md](host-worktree-merge.md). Where this document and the normative
files ever disagree, **the normative files win**.

Flagged, not fixed (the document below is preserved as given):

1. **Abbreviated decision block.** Same flag as [example-isolation.md](example-isolation.md):
   a real decision must also contain `HumanGate`, `NestedAllowed`, `MaxNestingDepth`,
   `Reservations`, `Calls`, `Deadline` and `Uncertainty`, and `Profile` is shown as a
   placeholder where spec-v2.md §9 requires the exact identity tuple. `HumanGate` matters to
   this flow specifically: with `review-before-dispatch` or `approval-required`, the Host
   must obtain human sign-off **before** step 3, and `review-before-merge` gates step 6's
   merge.
2. **"Complete isolation" / "only reflects that agent's changes" overstate worktree
   isolation.** Same flag as [host-worktree-flow.md](host-worktree-flow.md): per
   [worktree-mechanics.md](worktree-mechanics.md) ("What is *not* isolated"), databases,
   ports, `.env` files / secrets, ignored dependencies and running processes are shared, and
   nothing prevents an agent from editing paths outside its worktree. Isolation here is
   cooperative and covers the worker's *tracked checkout*; verification inside the worktree
   isolates the code under test, not shared services.
3. **The worktree path sits inside the main working directory.** `WORKTREE_PATH=
   ".sr-worktrees/${TASK_ID}"` (and the naming table) use the *inside* form, while
   [host-worktree-flow.md](host-worktree-flow.md)'s prose rule and
   [worktree-mechanics.md](worktree-mechanics.md)'s examples put worktrees *outside* (`../`).
   Git supports both, but the inside form requires the parent checkout to ignore
   `.sr-worktrees/` — otherwise the nested checkout becomes untracked content that recursive
   tooling (builds, watchers, secret scans) sweeps up. The outside form avoids the issue
   entirely and remains the preferred reading.
4. **`HOLDSHORT_BRIEF.json` is a suggested host-side filename convention, not normative** —
   spec-v2.md §10.1 defines the Brief schema and §11 (Host responsibility 4) requires
   injecting the exact Brief into the Worker's environment, but names no file.

---

Holdshort decides **when** an agent needs isolation.  
The Host is responsible for **creating** the worktree and placing the agent inside it.

Here's the practical end-to-end flow for agents:

### 1. Holdshort Makes the Decision

When a task is risky (multi-file, parallel work, high blast radius, etc.), Holdshort returns:

```
Route:             delegate
Isolation:         worktree+branch
Owner:             worker
Profile:           <chosen agent profile>
+ Brief (machine-readable)
```

This tells the Host: "Spawn a dedicated agent in its own worktree."

### 2. Host Creates an Isolated Worktree for the Agent

```bash
TASK_ID="a3f9"
BRANCH="sr/${TASK_ID}/auth-refactor"
WORKTREE_PATH=".sr-worktrees/${TASK_ID}"

# Create a new branch + worktree from main (or another base)
git worktree add -b "$BRANCH" "$WORKTREE_PATH" main
```

Result:
- The agent gets its **own directory**
- Its **own branch**
- Its **own index**
- No other agent can write to the same files

### 3. Inject the Brief and Launch the Agent

```bash
# Place the exact Brief inside the worktree
cp brief.json "$WORKTREE_PATH/HOLDSHORT_BRIEF.json"

# Start the agent with the worktree as its working directory
cd "$WORKTREE_PATH"
# Launch the chosen profile (Claude Code, Codex, Aider, etc.)
```

The agent now only sees and edits files inside its private worktree.

### 4. Agent Works in Complete Isolation

While the agent is running:

- It can edit files freely.
- It can run tests (`pytest`, `npm test`, etc.).
- It can commit to its private branch.
- Other agents (or the main session) working in different worktrees cannot collide with it.

### 5. Verification Happens Inside the Worktree

All acceptance checks must be run **from the agent's worktree**:

```bash
cd "$WORKTREE_PATH"
pytest tests/auth/ -q
```

This guarantees the results only reflect that agent's changes.

### 6. Feedback Returns to the Same Agent

If tests fail or a reviewer leaves comments:

- The Host sends the feedback back to **the same agent** (ownership is sticky).
- The agent continues working in the same worktree and branch.
- Only after the acceptance contract is satisfied does the work get merged.

### 7. Cleanup After Merge

```bash
git worktree remove "$WORKTREE_PATH"
# Optionally delete the branch after it is merged
```

---

### Recommended Naming Convention

| Item       | Example                        |
|------------|--------------------------------|
| Task ID    | `a3f9`                         |
| Branch     | `sr/a3f9/auth-refactor`        |
| Worktree   | `.sr-worktrees/a3f9`           |

This keeps everything easy to track and clean up.

---

### Summary for Agents

| Step                    | Who          | What happens                                      |
|-------------------------|--------------|---------------------------------------------------|
| Decide isolation needed | Holdshort  | Outputs `Isolation: worktree+branch`              |
| Create worktree + branch| Host         | `git worktree add -b ...`                         |
| Launch agent            | Host         | Starts the agent **inside** the worktree          |
| Agent works             | Agent        | Edits, tests, and commits only in its worktree    |
| Verify                  | Host/Agent   | Runs checks inside the same worktree              |
| Feedback                | Host         | Returns failures/comments to the same agent       |
| Finish                  | Host         | Removes the worktree after merge                  |

**Key rule:**  
The agent should never be started in the main working directory when Holdshort requested `worktree+branch`. Always launch it inside its private worktree.

**v3.0 autonomy default:** a human checkpoint shown in this example applies only
when explicitly requested by the user. Otherwise `HumanGate` is `none`; the Host
verifies and completes authorized work autonomously. Failed eligibility or exhausted
limits yield a recorded automatic stop, not a human approval prompt (spec-v2.md §8.2).
