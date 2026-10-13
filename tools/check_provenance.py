#!/usr/bin/env python3
"""Isolation-provenance check — does the delivered diff match its worktree+branch claim?

The reviewer's question (see skills/smart-router-review/references/isolation-provenance.md):
a worker that was supposed to own brief T in `sr/<id>/<slug>` must have produced a diff
that comes from THAT branch and touches ONLY permitted-effects paths. A diff that drifts
outside its provenance is either a scope violation (Gate 1 / Brief permitted-effects) or
evidence the work did not happen in the claimed isolation at all.

Checks, in order (first failure decides):
  1. task id valid (`tools/task_ids.py` format) and branch named exactly
     `sr/<task-id>/<slug>` with a non-empty slug
  2. branch exists in the repo (fail-closed when git is unreadable)
  3. the diff `merge-base(base, branch)..branch` touches only `--permitted` path
     prefixes (repeatable; empty = nothing may change); renaming the diff away
     with `--base` tricks is refused: base must be an ancestor of the branch
  4. when `--worktree` is given, it must still exist and `git worktree list` must
     show it on exactly this branch (a removed post-merge worktree is fine —
     pass `--worktree ""` after cleanup and the ledger merge commit is checked
     instead when `--merge-commit` is given)

Exit 0 proven; 1 provenance violation (names the offending files/branch);
2 fail-closed (missing branch, unreadable git, bad args).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ti = _load("tids_prov", TOOLS / "task_ids.py")


class FailClosed(RuntimeError):
    pass


class Violation(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, timeout=120)
    except OSError as e:
        raise FailClosed(f"git unavailable ({e})") from e


def _must(repo: Path, *args: str, what: str) -> str:
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise FailClosed(f"{what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def expected_branch(task_id: str, slug: str) -> str:
    return ti.branch_for(task_id, slug)  # ValueError on bad id/slug -> caller maps


def check(repo: Path, *, task_id: str, branch: str, permitted: list[str],
          base: str = "main", worktree: str = "", merge_commit: str = "") -> dict:
    """Run checks 1-4. Returns the proof report; raises Violation or FailClosed."""
    try:
        slug = branch.split("/", 2)[2] if branch.count("/") == 2 else ""
        want = expected_branch(task_id, slug or "x")
    except ValueError as e:
        raise Violation(f"task id invalid: {e}") from e
    if branch != want or not slug:
        raise Violation(f"branch {branch!r} is not sr/<task-id>/<slug> for task {task_id!r} "
                        f"(want sr/{task_id}/<slug>)")
    branches = _must(repo, "branch", "--list", branch, what="branch lookup")
    # `git branch` marks the current worktree's branch with `*` and any branch checked
    # out in a linked worktree with `+` — strip both markers before comparing.
    if branch not in [b.strip().lstrip("*+ ") for b in branches.splitlines()]:
        raise FailClosed(f"branch {branch!r} absent — nothing to prove provenance of")
    base_sha = _must(repo, "rev-parse", "--verify", base, what="base resolve").strip()
    tip = _must(repo, "rev-parse", "--verify", branch, what="branch resolve").strip()
    mb = _must(repo, "merge-base", base_sha, tip, what="merge-base").strip()
    if mb != base_sha:
        raise Violation(f"base {base!r} is not an ancestor of {branch!r} — "
                        f"re-homing the diff base hides provenance")
    diff = _must(repo, "diff", "--name-only", "-z", f"{mb}..{tip}", what="diff").split("\0")
    touched = sorted(f for f in (d.strip() for d in diff) if f)
    offenders = [f for f in touched
                 if not any(f == p or f.startswith(p.rstrip("/") + "/") for p in permitted)]
    if offenders:
        raise Violation(f"{len(offenders)} file(s) outside permitted-effects "
                        f"{permitted}: {offenders[:10]}")
    if worktree:
        listed = _must(repo, "worktree", "list", "--porcelain", "-z", what="worktree list")
        here = {}
        current = None
        for field in listed.split("\0"):
            if field.startswith("worktree "):
                current = os.path.normcase(os.path.normpath(field[9:]))
                here[current] = None
            elif field.startswith("branch ") and current is not None:
                here[current] = field[7:]
        claimed = os.path.normcase(os.path.normpath(worktree))
        if claimed not in here:
            raise Violation(f"worktree {worktree!r} not listed on this checkout")
        if here[claimed] != f"refs/heads/{branch}":
            raise Violation(f"worktree {worktree!r} is not on {branch!r}")
    if merge_commit:
        msg = _must(repo, "log", "-1", "--pretty=%H %s", merge_commit, what="merge lookup")
        if tip not in _must(repo, "log", "--pretty=%H", merge_commit, what="merge history"):
            raise Violation(f"merge commit {merge_commit!r} does not contain {branch!r}")
    return {"task_id": task_id, "branch": branch, "base": base,
            "files": touched, "worktree": worktree or None,
            "merge_commit": merge_commit or None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prove a diff matches its worktree+branch provenance.")
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--permitted", action="append", default=[], metavar="PATH-PREFIX")
    ap.add_argument("--base", default="main")
    ap.add_argument("--worktree", default="")
    ap.add_argument("--merge-commit", default="")
    args = ap.parse_args(argv)
    try:
        report = check(args.repo, task_id=args.task_id, branch=args.branch,
                       permitted=args.permitted, base=args.base,
                       worktree=args.worktree, merge_commit=args.merge_commit)
    except Violation as e:
        print(f"check_provenance: VIOLATION — {e}", file=sys.stderr)
        return 1
    except FailClosed as e:
        print(f"check_provenance: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2
    files = ", ".join(report["files"]) if report["files"] else "(no files changed)"
    print(f"check_provenance: PROVED {report['branch']} touches only {args.permitted}: {files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
