#!/usr/bin/env python3
"""Pre-launch guard — refuse to start a worker outside its dedicated worktree.

The agent-focused companion states the key rule plainly ("The agent should never be
started in the main working directory when Holdshort requested `worktree+branch`"),
but prose never stopped a misconfigured launcher: a worker started in the main checkout
writes onto every other worker's files, and a worker started in an unrelated directory
has no branch, no Brief, and no provenance at all. This guard runs BEFORE the agent
process is created and refuses those starts:

  * isolation `worktree+branch` + launch dir == the main checkout → REFUSED (exit 1)
  * isolation `worktree+branch` + launch dir not inside ANY linked worktree of the
    repo → REFUSED (exit 1): bare directories, /tmp landings, sibling checkouts
  * git unreadable (missing repo, corrupt worktree metadata) → FAIL-CLOSED (exit 2)
  * any other isolation value → allowed (exit 0): `none` launches in place by design,
    and `directory`/`ephemeral-container` placement is the container runtime's job,
    not this git check's
  * optional `--task-id`/`--branch`: when given, the worktree must additionally sit
    on exactly `sr/<task-id>/<slug>` — a right worktree for the wrong task refuses

Usage (host launcher wraps the agent start):
    python tools/guard_launch.py --repo . --dir "$WORKTREE_PATH" --isolation worktree+branch \
        --task-id "$TASK_ID" --branch "$BRANCH" && launch-agent-here
"""
from __future__ import annotations

import argparse
import importlib.util
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


ti = _load("tids_guard", TOOLS / "task_ids.py")


class FailClosed(RuntimeError):
    pass


class Refused(RuntimeError):
    pass


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=120)
    except OSError as e:
        raise FailClosed(f"git unavailable ({e})") from e


def _must(cwd: Path, *args: str, what: str) -> str:
    proc = _git(cwd, *args)
    if proc.returncode != 0:
        raise FailClosed(f"{what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def _shared_attested(registry: Path | None, task_id: str, branch: str, launch_dir: Path) -> bool:
    """True when the registry record carries an attested shared-surface plan (G7)."""
    if registry is None or not task_id:
        return False
    try:
        import json as _json
        doc = _json.loads(registry.read_text(encoding="utf-8"))
        rec = doc.get("workers", {}).get(task_id, {})
        shared = rec.get("shared")
        if (not branch or rec.get("branch") != branch
                or Path(rec["path"]).resolve() != launch_dir
                or not isinstance(shared, dict) or shared.get("attested") is not True):
            return False
        # Use the spawn validator rather than trusting a truthy attestation.
        validator = _load("shared_guard", TOOLS / "spawn_worker.py")
        validator.check_shared_plan(shared, {"workers": {}})
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return False


def check(repo: Path, launch_dir: Path, isolation: str, *,
          task_id: str = "", branch: str = "",
          registry: Path | None = None,
          require_shared_plan: bool = False) -> dict:
    """Approve one launch. Returns the proof; raises Refused/FailClosed."""
    if isolation != "worktree+branch":
        return {"launch": "allowed", "reason": f"isolation {isolation!r} launches in place by design"}
    try:
        launch_resolved = launch_dir.resolve()
        repo_top = Path(_must(repo, "rev-parse", "--show-toplevel",
                              what="repo top-level").strip()).resolve()
    except FailClosed as e:
        raise FailClosed(f"repo unreadable ({e})") from e
    try:
        dir_git = _must(launch_resolved, "rev-parse", "--absolute-git-dir",
                        what="launch-dir git dir").strip()
    except FailClosed:
        raise Refused(f"launch dir {launch_dir} is inside no git worktree — refusing to "
                      f"start an isolated worker with no branch and no provenance")
    if launch_resolved == repo_top:
        raise Refused(f"launch dir IS the main checkout ({repo_top}) — refusing: an isolated "
                      f"worker must start inside its dedicated linked worktree, never main")
    # A linked worktree's gitdir lives under <repo>/.git/worktrees/<name>; the main
    # checkout's is <repo>/.git itself. Anything else (submodule, foreign repo) refuses.
    main_git = Path(_must(repo, "rev-parse", "--absolute-git-dir",
                          what="repo git dir").strip()).resolve()
    git_path = Path(dir_git).resolve()
    try:
        git_path.relative_to(main_git / "worktrees")
    except ValueError:
        raise Refused(f"launch dir's git metadata ({git_path}) is not a linked worktree of "
                      f"{repo_top} — refusing (submodule? foreign checkout?)") from None
    listed = _must(repo, "worktree", "list", "--porcelain", what="worktree list")
    here = [ln.split(None, 1)[1] for ln in listed.splitlines() if ln.startswith("worktree ")]
    if str(launch_resolved) not in [str(Path(h).resolve()) for h in here]:
        raise Refused(f"launch dir {launch_resolved} not in this repo's worktree list — "
                      f"stale or foreign checkout, refusing")
    if task_id or branch:
        if not task_id or not branch:
            raise Refused("task-id and branch must be given together")
        try:
            slug = branch.split("/", 2)[2] if branch.count("/") == 2 else ""
            want = ti.branch_for(task_id, slug or "x")
        except ValueError as e:
            raise Refused(f"task id invalid: {e}") from e
        if branch != want or not slug:
            raise Refused(f"branch {branch!r} is not sr/<task-id>/<slug> for {task_id!r}")
        current = _must(launch_resolved, "branch", "--show-current",
                        what="worktree branch").strip()
        if current != branch:
            raise Refused(f"worktree is on {current!r}, not the worker's {branch!r} — "
                          f"right worktree area, wrong task")
    if require_shared_plan and isolation == "worktree+branch":
        if not _shared_attested(registry, task_id, branch, launch_resolved):
            raise Refused("no attested shared-surface plan for this task "
                          "(--require-shared-plan: spawn with --no-shared-surface or --shared-plan first)")
    return {"launch": "allowed", "dir": str(launch_resolved), "branch": branch or None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse isolated-worker starts outside their worktree.")
    ap.add_argument("--repo", type=Path, required=True, help="main checkout of the repo")
    ap.add_argument("--dir", type=Path, required=True, help="proposed agent launch directory")
    ap.add_argument("--isolation", required=True)
    ap.add_argument("--task-id", default="")
    ap.add_argument("--branch", default="")
    ap.add_argument("--registry", type=Path, default=None,
                    help="worker registry holding shared-surface attestations (G7)")
    ap.add_argument("--require-shared-plan", action="store_true",
                    help="refuse worktree+branch starts without an attested plan")
    args = ap.parse_args(argv)
    try:
        report = check(args.repo, args.dir, args.isolation,
                       task_id=args.task_id, branch=args.branch,
                       registry=args.registry,
                       require_shared_plan=args.require_shared_plan)
    except Refused as e:
        print(f"guard_launch: REFUSED — {e}", file=sys.stderr)
        return 1
    except FailClosed as e:
        print(f"guard_launch: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2
    print(f"guard_launch: ALLOWED — {report['reason'] if 'reason' in report else report['dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
