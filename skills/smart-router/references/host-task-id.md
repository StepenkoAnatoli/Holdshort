# Host task-ID semantics — minting, format, entropy, uniqueness

**Status:** background material — non-normative, like the host-worktree companions it
specifies. It pins down what the companions' running example (`task_id = "a3f9"`,
branch `sr/a3f9/auth-refactor`, worktree `.sr-worktrees/a3f9`) implies but never states;
the normative contract remains [gates.md](gates.md) (fixture-pinned) and
[spec-v2.md](spec-v2.md). Where this document and the normative files ever disagree,
**the normative files win**. Executable form: [../../../tools/task_ids.py](../../../tools/task_ids.py)
(the tool is the specification where prose is ambiguous).

## 1. Format

`^[0-9a-f]{4,16}$` — lowercase hexadecimal, 4 to 16 characters. Validation is exact:
uppercase, non-hex, shorter than 4 or longer than 16 are not task ids. The companions'
`a3f9` is a valid 4-hex short id — an illustrative short form, acceptable at small scale
**with** the §3 uniqueness check, never a minting default.

## 2. Minting

`secrets.token_hex`, never `random`. Default 8 hex characters (32 bits of entropy per
mint) — negligible accidental-collision odds once §3 runs, still readable on a branch
name. Callers needing more room (large registries, long-lived hosts) may mint up to 16
hex chars; below 4 is refused. The mint length is even (whole bytes) by construction.

Why 32 bits and not 16: two random 4-hex ids collide with probability 50% at ~256 live
tasks (birthday bound) — exactly the parallel-worker regime the worktree flow exists for.
The default doubles the mint cost (8 chars) and keeps the check; entropy plus the check,
not entropy alone, is the guarantee.

## 3. Uniqueness (never reset, never assumed)

An id is unique only against the live scope at spawn time:

- the host registry's task ids,
- known Outcome-Ledger task ids,
- live worktree directory names (`git worktree list`) matching the §1 format,
- live branches matching `sr/<hex>/*` (`git branch --list`).

`ensure_unique` retries minting (default 32 tries) against that scope. An unreadable
scope or an exhausted retry budget fails closed (`ScopeUnreachable`) — the host spawns
nothing rather than handing two workers one checkout. Restart, rename, or profile change
never clears the taken set; only merge/abandon cleanup releases an id.

## 4. Derivation (fixed — every host builds the same names from one id)

- Branch: `sr/<task-id>/<slug>`, slug = lowercase alnum runs of the objective joined by
  single dashes, 1–64 chars (`task` fallback). Slugs distinguish tasks to humans; only the
  id distinguishes them to the host.
- Worktree path (preferred): `../.sr-worktrees/<task-id>` — the outside form
  ([host-worktree-flow.md](host-worktree-flow.md) flag 1). The inside form
  (`.sr-worktrees/<task-id>`) requires the parent checkout to ignore `.sr-worktrees/`.
- State/ledger keys use the raw id; `_sanitize`-style filesystem guards apply to slugs
  and paths, never to the id itself (an invalid id is refused, not scrubbed).

## 5. Worked example

`a3f9` + objective `Auth Refactor!!` → branch `sr/a3f9/auth-refactor`, worktree
`../.sr-worktrees/a3f9`. A second task mints (say) `24175da1` → `sr/24175da1/...` in
`../.sr-worktrees/24175da1`. Git itself refuses to check out one branch in two worktrees,
so distinct ids plus distinct branches make collision a host bug, not a git race — which
is what the dry-run harness (`tools/host_dry_run.py`) proves with two parallel workers.
