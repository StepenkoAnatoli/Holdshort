# Git Worktree Mechanics Explained

**Status:** background material — non-normative. It explains the mechanism behind the
`worktree+branch` isolation level; the normative contract remains [gates.md](gates.md)
(fixture-pinned) and [spec-v2.md](spec-v2.md). Where this document and the normative files
ever disagree, **the normative files win**.

A normal Git repository has **one working directory** (the files you see and edit) and one
**`.git` directory** (the database of all commits, branches, and objects).

A **worktree** lets you attach **extra working directories** to the *same* repository. Each
extra directory can have a different branch checked out at the same time, without interfering
with the others.

## Core Idea

```
Main repository
├── .git/                    ← shared object database + refs
│   ├── objects/
│   ├── refs/
│   └── worktrees/           ← metadata for each linked worktree
│       ├── feature-a/
│       └── hotfix/
│
├── (main working files)     ← main worktree
│
../feature-a/                ← linked worktree 1
└── ../hotfix/               ← linked worktree 2
```

- **Shared**: commit history, objects, branches, tags, configuration.
- **Private to each worktree**: the actual checked-out files, the index (staging area), and
  `HEAD`.

## How It Works Internally

1. When you run `git worktree add`, Git creates a new directory.
2. Inside that new directory it places a **file** named `.git` (not a folder) that points
   back to the main repository:
   ```
   gitdir: /path/to/main/repo/.git/worktrees/feature-a
   ```
3. In the main repository, under `.git/worktrees/`, Git stores the private metadata for that
   worktree (its `HEAD`, index, etc.).
4. Because the heavy data (objects) stays in one place, creating a worktree is very cheap —
   usually just a checkout of the files for that branch.

## Important Rules

- **One branch per worktree**
  Git refuses to check out the same local branch in two worktrees at the same time. This
  prevents two people (or two agents) from stepping on each other.

- **Linked vs Main**
  - The original directory is the *main worktree*.
  - Every additional one is a *linked worktree*.

- **What is *not* isolated**
  Worktrees only isolate the filesystem checkout. They do **not** isolate:
  - databases
  - ports
  - `.env` files / secrets
  - `node_modules` or other ignored files (you usually need to install dependencies again or
    symlink them)
  - running processes

## Common Commands

```bash
# Create a new worktree with a new branch
git worktree add -b feature/caching ../repo-caching main

# Create a worktree for an existing branch
git worktree add ../repo-hotfix hotfix/payment

# List all worktrees
git worktree list

# Remove a worktree when finished
git worktree remove ../repo-caching
```

## Why This Matters for AI Agents / SmartRouter

When multiple agents (or a main session + workers) need to edit the same repository at the
same time, a shared working directory causes collisions.

A worktree gives each agent:

- its own clean set of files
- its own branch
- its own index

…while still sharing the same Git history and object store. That is why SmartRouter's
preferred isolation level is `worktree+branch`.

For the host-side operational flow that materializes this isolation level (create worktree +
branch, inject the Brief, verify inside the worktree, clean up), see
[host-worktree-flow.md](host-worktree-flow.md) (agent-focused variant:
[host-worktree-agents.md](host-worktree-agents.md)).
