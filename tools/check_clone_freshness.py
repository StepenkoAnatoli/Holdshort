#!/usr/bin/env python3
"""Clone-freshness report — is this clone exactly origin/main, right now?

Why this exists: a stale `origin/main` remote-tracking ref is silent. In one
real session `git diff origin/main...HEAD` reported 15 changed files where the
branch's own change touched 2, because this clone's `origin/main` still pointed
at a commit from the previous day — only `git fetch origin main` revealed the
real tip. Nothing had said "your local view of main is out of date". This tool
says it, in one command, using the remote itself as the authority: the live tip
is read with `git ls-remote` (read-only), never taken from the local
remote-tracking ref, which is exactly the reference under suspicion.

The runbook §0 precondition asks whether this clone is on the pushed tree; the
three questions it implies each print a finding when the answer is not "yes":

  * HEAD vs the LIVE origin/main tip — identical, ahead (local-only commits),
    behind, or diverged; when the remote moved and this clone has not fetched,
    the tip object is not in this clone at all and the report says exactly
    that instead of inventing counts;
  * the local origin/main tracking ref vs that same live tip — a stale ref
    means this clone's local view of main is not main (the bug above);
  * the worktree — tracked changes and untracked files (`git status -z`, so a
    path with spaces cannot smear the report), plus commits reachable from a
    local branch but from NO remote at all: work that exists only here.

Read-only by design: never fetches, never writes a ref, never touches the
worktree. A freshness checker that mutates the clone it measures would make
its own two runs disagree.

Exit codes:
  0  this clone IS origin/main exactly — HEAD identical to the live tip, no
     local-only commits, worktree clean.
  1  not exact; every reason prints as a finding.
  2  FAIL-CLOSED: the live tip could not be determined (`git ls-remote` failed
     — no network, bad remote, not a git repository). This is NOT a pass and
     not a drift report: the question was not answered. `--offline` opts into a
     deliberately weaker comparison against the last-fetched origin/main, which
     the output discloses and which cannot detect that the remote moved.

Deliberately NOT wired into run_regression.py / the pre-commit hook: the gate
runs on every commit and must work offline, while this check cannot answer at
all without the remote. Its test (tools/test_clone_freshness.py) is hermetic
and does run in the gate; this tool's caller is the operator — runbook §0.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE = "origin"
BRANCH = "main"
MAX_LISTED = 5


def _git(root: Path, *args: str, timeout: int = 60):
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, errors="replace", timeout=timeout)


def live_tip(root: Path) -> tuple[str | None, str]:
    """(sha the remote's refs/heads/main points at NOW, error text). None = cannot tell."""
    out = _git(root, "ls-remote", REMOTE, f"refs/heads/{BRANCH}")
    if out.returncode != 0:
        first = next((l for l in out.stderr.strip().splitlines() if l.strip()),
                     "git ls-remote failed")
        return None, first
    line = out.stdout.strip()
    if not line:
        return None, f"the remote has no refs/heads/{BRANCH}"
    return line.split()[0], ""


def _rev(root: Path, ref: str) -> str | None:
    out = _git(root, "rev-parse", "--verify", "--quiet", ref)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def _object_exists(root: Path, sha: str) -> bool:
    return _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def _count(root: Path, rng: str) -> int | None:
    out = _git(root, "rev-list", "--count", rng)
    return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def _log_list(root: Path, *args: str) -> list[str] | None:
    """`git log --no-decorate --format='%h %s'` over args, or None on failure."""
    out = _git(root, "log", "--no-decorate", "--format=%h %s", *args)
    if out.returncode != 0:
        return None
    return [l for l in out.stdout.splitlines() if l.strip()]


def worktree_changes(root: Path) -> tuple[list[str] | None, list[str] | None]:
    """([tracked changes], [untracked files]) parsed from `git status -z`.

    NUL-separated so a path containing a space or a quote arrives intact; a
    rename's original path (a second field) is skipped rather than reported.
    """
    out = _git(root, "status", "--porcelain", "-z")
    if out.returncode != 0:
        return None, None
    tracked: list[str] = []
    untracked: list[str] = []
    entries = out.stdout.split("\x00")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in ("R", "C"):
            i += 1  # the rename/copy source field
        (untracked if code == "??" else tracked).append(f"{code} {path}")
    return tracked, untracked


@dataclass
class Report:
    root: Path
    head: str | None = None
    branch: str = "detached"
    tip: str | None = None            # the tip the verdict used
    tip_source: str = "live"          # "live" | "offline (last fetch)"
    tracking: str | None = None       # refs/remotes/<REMOTE>/<BRANCH>
    ahead: int | None = None
    behind: int | None = None
    local_only: list = field(default_factory=list)    # commits not on the tip
    dirty_tracked: list = field(default_factory=list)
    dirty_untracked: list = field(default_factory=list)
    never_pushed: list = field(default_factory=list)  # on no remote at all
    problems: list = field(default_factory=list)
    cannot_determine: str = ""


def _bullets(lead: str, items: list[str]) -> str:
    shown = items[:MAX_LISTED]
    lines = [lead] + [f"  {x}" for x in shown]
    if len(items) > MAX_LISTED:
        lines.append(f"  ... and {len(items) - MAX_LISTED} more")
    return "\n".join(lines)


def inspect(root: Path, *, offline: bool = False) -> Report:
    """Everything the report needs about `root`; never mutates it."""
    r = Report(root=root)
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        r.cannot_determine = f"{root} is not inside a git repository"
        return r

    ref = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    r.branch = "detached" if not ref or ref == "HEAD" else ref
    r.head = _rev(root, "HEAD")
    r.tracking = _rev(root, f"refs/remotes/{REMOTE}/{BRANCH}")

    if offline:
        r.tip_source = "offline (last fetch)"
        r.tip = r.tracking
        if r.tip is None:
            r.cannot_determine = (
                f"offline: refs/remotes/{REMOTE}/{BRANCH} does not exist, "
                "so there is nothing to compare against")
            return r
    else:
        tip, err = live_tip(root)
        if tip is None:
            r.cannot_determine = err
            return r
        r.tip = tip

    if r.head is None:
        r.problems.append(f"HEAD is unborn — branch '{r.branch}' has no commits yet")
    elif r.head != r.tip:
        if not _object_exists(root, r.tip):
            # The remote moved and this clone never fetched: the tip is not an
            # object here, so ahead/behind cannot be counted -- say that,
            # rather than reporting a wrong number. Never fetch: read-only.
            r.problems.append(
                f"HEAD {r.head[:10]} on '{r.branch}' is NOT {REMOTE}/{BRANCH} {r.tip[:10]} "
                f"-- the live tip is not present in this clone "
                f"(run `git fetch {REMOTE}` to compare)")
        else:
            r.ahead = _count(root, f"{r.tip}..HEAD")
            r.behind = _count(root, f"HEAD..{r.tip}")
            if r.ahead and r.behind:
                shape = f"diverged — ahead {r.ahead}, behind {r.behind}"
            elif r.ahead:
                shape = f"ahead {r.ahead}"
            elif r.behind:
                shape = f"behind {r.behind}"
            else:
                shape = "different commits"
            r.problems.append(
                f"HEAD {r.head[:10]} on '{r.branch}' is NOT {REMOTE}/{BRANCH} "
                f"{r.tip[:10]} ({shape})")
            if r.ahead:
                r.local_only = _log_list(root, f"{r.tip}..HEAD") or []
                r.problems.append(_bullets(
                    f"{r.ahead} local-only commit(s) -- not on {REMOTE}/{BRANCH}:", r.local_only))

    if r.tip_source == "live" and r.tracking and r.tracking != r.tip:
        r.problems.append(
            f"{REMOTE}/{BRANCH} tracking ref is STALE: local {r.tracking[:10]} != live "
            f"{r.tip[:10]} — this clone's view of main is out of date; run "
            f"`git fetch {REMOTE}`")

    tracked, untracked = worktree_changes(root)
    if tracked is None:
        r.cannot_determine = "git status failed — worktree state unknown"
        return r
    r.dirty_tracked, r.dirty_untracked = tracked, untracked
    if tracked or untracked:
        parts = []
        if tracked:
            parts.append(f"{len(tracked)} tracked change(s)")
        if untracked:
            parts.append(f"{len(untracked)} untracked file(s)")
        r.problems.append(_bullets(
            f"worktree is not clean: {', '.join(parts)}:", tracked + untracked))

    never = _log_list(root, "--branches", "--not", "--remotes")
    if never:
        r.never_pushed = never
        r.problems.append(_bullets(
            f"{len(never)} commit(s) exist on no remote at all — local-only work "
            "that this clone would take with it:", never))

    return r


def main(root: Path | None = None, offline: bool = False) -> int:
    r = inspect(root or REPO_ROOT, offline=offline)
    if r.cannot_determine:
        print(f"clone_freshness: FAIL-CLOSED — {r.cannot_determine}", file=sys.stderr)
        if not offline:
            print(f"  the question 'is this clone exactly {REMOTE}/{BRANCH}?' was not "
                  "answered; `--offline` compares against the last-fetched ref "
                  "(weaker: it cannot see the remote move)", file=sys.stderr)
        return 2
    if r.problems:
        print(f"clone_freshness: FAIL — this clone is not exactly {REMOTE}/{BRANCH}:")
        for problem in r.problems:
            lines = problem.splitlines()
            print(f"  - {lines[0]}")
            for extra in lines[1:]:
                print(f"    {extra}")
        print("  fix: git fetch origin && git status   "
              "(or work from a clean clone of the pushed tree)")
        if r.tip_source != "live":
            print(f"  note: remote tip NOT verified (--offline) -- compared against the "
                  f"last-fetched {REMOTE}/{BRANCH} {(r.tip or '')[:10]}")
        return 1
    if r.tip_source != "live":
        print(f"clone_freshness: OK-LOCAL — HEAD {(r.head or '')[:10]} == last-fetched "
              f"{REMOTE}/{BRANCH}, worktree clean, no local-only commits")
        print(f"  remote tip NOT verified (--offline): this clone's view of {REMOTE}/{BRANCH} "
              "is only as fresh as the last fetch; re-run without --offline before a live "
              "session")
        return 0
    print(f"clone_freshness: OK — HEAD {(r.head or '')[:10]} == {REMOTE}/{BRANCH} "
          f"(live tip), branch '{r.branch}', worktree clean, no local-only commits")
    return 0


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="Report whether this clone is exactly origin/main (read-only; never fetches).")
    ap.add_argument("--root", type=Path, default=None,
                    help="repo root to inspect (default: the clone containing this tool)")
    ap.add_argument("--offline", action="store_true",
                    help="compare against the last-fetched origin/main instead of asking the "
                         "remote; the output discloses that the remote tip is unverified")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(main(args.root, args.offline))
