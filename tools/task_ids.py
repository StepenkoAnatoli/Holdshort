#!/usr/bin/env python3
"""Task-ID semantics — minting, format, entropy, and uniqueness.

What the companions imply but never specify: every host-worktree example uses
`task_id = "a3f9"` (`sr/a3f9/auth-refactor`, `.sr-worktrees/a3f9`), yet no companion
says what a task id IS — how it is minted, which strings are valid, how much
entropy it carries, or what makes two ids different tasks. This module is that
specification, executable:

  * Format: `^[0-9a-f]{4,16}$` — lowercase hex, 4 to 16 chars. The companions'
    `a3f9` is a valid 4-hex short id (illustrative short form, fine at small
    scale with the uniqueness check below, not a minting default).
  * Minting: `secrets.token_hex`, never `random`. Default 8 hex chars (32 bits
    of entropy) — enough that accidental collision is negligible once the
    uniqueness check runs, cheap enough to read on a branch name.
  * Uniqueness: an id is unique only against the live scope — the host registry,
    `git worktree list` paths, `git branch --list 'sr/<id>/*'`, and known ledger
    task ids. `ensure_unique` retries minting (bounded, default 32 tries) and
    fails closed when the scope is exhausted or unreachable, instead of handing
    two workers the same checkout.
  * Derivation (fixed, so every host builds the same names from one id):
    branch `sr/<task-id>/<slug>` (slug sanitized, 1-64 chars, lowercase
    alnum-plus-dash), worktree path `../.sr-worktrees/<task-id>` (preferred
    outside form per host-worktree-flow flag 1; the inside form requires the
    parent checkout to ignore `.sr-worktrees/`).

Stdlib only. No network, no repo state touched — the repo scope is passed in.
"""
from __future__ import annotations

import argparse
import re
import secrets
import subprocess
import sys
from pathlib import Path

TASK_ID_RE = re.compile(r"^[0-9a-f]{4,16}$")
DEFAULT_HEX_CHARS = 8       # 32 bits per mint
DEFAULT_RETRIES = 32
MAX_SLUG = 64


def valid(task_id: str) -> bool:
    """True when `task_id` matches the specified format."""
    return bool(TASK_ID_RE.match(task_id or ""))


def mint(n_hex_chars: int = DEFAULT_HEX_CHARS) -> str:
    """Mint one candidate id with `secrets` entropy (4-16 hex chars)."""
    if not 4 <= n_hex_chars <= 16 or n_hex_chars % 2:
        raise ValueError(f"n_hex_chars must be an even number in 4..16, got {n_hex_chars}")
    return secrets.token_hex(n_hex_chars // 2)


def slugify(text: str) -> str:
    """Branch-slug form of an objective: lowercase alnum runs joined by one dash."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:MAX_SLUG] or "task"


def branch_for(task_id: str, slug: str) -> str:
    if not valid(task_id):
        raise ValueError(f"invalid task id {task_id!r}")
    s = slugify(slug)
    return f"sr/{task_id}/{s}"


def worktree_path_outside(main_root: Path, task_id: str) -> Path:
    """Preferred outside form: sibling of the main checkout (never nested content)."""
    if not valid(task_id):
        raise ValueError(f"invalid task id {task_id!r}")
    return main_root.parent / ".sr-worktrees" / task_id


class ScopeUnreachable(RuntimeError):
    """The uniqueness scope could not be read — fail closed, do not mint blind."""


def collect_taken(repo_root: Path, registry_ids: set[str] | None = None,
                  ledger_ids: set[str] | None = None) -> set[str]:
    """Task ids already in use: registry + ledger + live worktrees/branches.

    Worktree entries named exactly `<hex>` under `.sr-worktrees`, and branches
    under `sr/<hex>/`, count as taken. Anything unreadable raises
    ScopeUnreachable instead of returning a partial set.
    """
    taken: set[str] = set(registry_ids or set()) | set(ledger_ids or set())
    try:
        wt = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo_root,
                            capture_output=True, text=True, timeout=60)
        if wt.returncode != 0:
            raise ScopeUnreachable(f"git worktree list failed: {wt.stderr.strip()}")
        for line in wt.stdout.splitlines():
            if line.startswith("worktree "):
                name = Path(line.split(None, 1)[1]).name
                if valid(name):
                    taken.add(name)
        br = subprocess.run(["git", "branch", "--list", "sr/*/*"], cwd=repo_root,
                            capture_output=True, text=True, timeout=60)
        if br.returncode != 0:
            raise ScopeUnreachable(f"git branch --list failed: {br.stderr.strip()}")
        for line in br.stdout.splitlines():
            parts = line.strip().lstrip("* ").split("/")
            if len(parts) >= 3 and parts[0] == "sr" and valid(parts[1]):
                taken.add(parts[1])
    except OSError as e:
        raise ScopeUnreachable(f"git unavailable ({e})") from e
    return taken


def ensure_unique(taken: set[str], n_hex_chars: int = DEFAULT_HEX_CHARS,
                  retries: int = DEFAULT_RETRIES) -> str:
    """Mint an id absent from `taken`; fail closed after `retries` collisions."""
    for _ in range(max(retries, 1)):
        cand = mint(n_hex_chars)
        if cand not in taken:
            return cand
    raise ScopeUnreachable(f"could not mint a fresh id after {retries} tries "
                           f"({len(taken)} taken) — scope exhausted, refusing blind reuse")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mint and validate Holdshort host task ids.")
    ap.add_argument("--mint", action="store_true", help="print one fresh id (checked against --repo scope)")
    ap.add_argument("--validate", default=None, help="exit 0 iff the value is a valid task id")
    ap.add_argument("--branch", nargs=2, metavar=("TASK_ID", "SLUG"), help="print the branch name derivation")
    ap.add_argument("--n-chars", type=int, default=DEFAULT_HEX_CHARS)
    ap.add_argument("--repo", type=Path, default=None, help="repo root for the uniqueness scope")
    args = ap.parse_args(argv)
    if args.validate is not None:
        print("valid" if valid(args.validate) else "invalid")
        return 0 if valid(args.validate) else 1
    if args.branch is not None:
        try:
            print(branch_for(args.branch[0], args.branch[1]))
        except ValueError as e:
            print(f"task_ids: {e}", file=sys.stderr)
            return 2
        return 0
    if args.mint:
        try:
            taken = collect_taken(args.repo, set(), set()) if args.repo else set()
            print(ensure_unique(taken, args.n_chars))
        except (ScopeUnreachable, ValueError) as e:
            print(f"task_ids: FAIL-CLOSED — {e}", file=sys.stderr)
            return 2
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
