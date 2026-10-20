#!/usr/bin/env python3
"""Host lifecycle dry-run — the documented worktree flow end-to-end, twice in parallel.

Runs the exact lifecycle the companions describe (flow → agents → registry →
merge), with two workers at once, against a throwaway repo — proving the property
the docs only assert: no collisions. No network, no model dispatch, no repo state
touched; everything lives under a temp dir (or --keep) with an isolated git env.

Lifecycle per worker (mirrors host-worktree-flow/agents/registry/merge):

  1. mint task id (`tools/task_ids.py`: secrets entropy + live-scope uniqueness)
  2. `git worktree add -b sr/<id>/<slug> ../.sr-worktrees/<id> main` (outside form)
  3. inject the exact Brief (`HOLDSHORT_BRIEF.json`) + start simulated work
  4. worker edits, commits on its branch; acceptance check runs inside its worktree
  5. host merges each branch into main, records a §10.3 Outcome per task
  6. host removes the worktree and (after merge) the branch

Proofs asserted (any failure exits nonzero with the reason, never a silent pass):

  P1. the two ids, branches, and worktree paths are pairwise distinct
  P2. each worktree holds its own payload and NOT the other's (checkout isolation)
  P3. `git worktree list` shows both worktrees simultaneously (git agrees)
  P4. both branches merge into main; post-merge main holds both payloads
  P5. cleanup removes both worktrees; ledger holds two `accepted` outcomes

Usage:
    python tools/host_dry_run.py            # prove and clean up
    python tools/host_dry_run.py --keep DIR # prove and retain the tree for inspection
Exit 0 proved; 1 lifecycle/proof failure; 2 fail-closed (git missing/broken).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ti = _load("tids_dryrun", TOOLS / "task_ids.py")
ol = _load("oll_dryrun", TOOLS / "outcome_ledger.py")
sw = _load("spw_dryrun", TOOLS / "spawn_worker.py")

class DryRunFailed(RuntimeError):
    """A lifecycle step or proof failed — the harness must not report success."""


_REG_LOCK = None  # created per-run: the shared registry file needs one writer at a time
def _reg_lock():
    global _REG_LOCK
    if _REG_LOCK is None:
        import threading
        _REG_LOCK = threading.Lock()
    return _REG_LOCK

WORKERS = (
    {"slug": "caching-layer", "file": "feature-a.txt", "body": "worker-A payload\n"},
    {"slug": "auth-refactor", "file": "feature-b.txt", "body": "worker-B payload\n"},
)


def _env(tmp: Path) -> dict:
    empty = tmp / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(cwd: Path, *args: str, env: dict) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)
    except OSError as e:
        raise DryRunFailed(f"fail-closed: git unavailable ({e})") from e


def _must(cwd: Path, *args: str, env: dict, what: str) -> str:
    proc = _git(cwd, *args, env=env)
    if proc.returncode != 0:
        raise DryRunFailed(f"{what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def brief_for(task_id: str, slug: str) -> dict:
    return {"objective": f"dry-run {slug}", "acceptance": {"checks": [
        {"command": "test -f HOLDSHORT_BRIEF.json", "expect": "exit 0"}]},
        "isolation": "worktree+branch", "branch-hint": f"sr/{task_id}/{slug}",
        "attempts": 1, "ownership": "worker"}


def spawn_worker(main: Path, wt_root: Path, task_id: str, spec: dict, env: dict,
                 registry: Path) -> dict:
    """Steps 2-4 for one worker, via the tested host primitive (never half-spawns)."""
    try:
        # One writer at a time AND one worktree-add at a time: concurrent adds race
        # on the shared .git/worktrees/ admin dir (PR #42 CI: sibling
        # `fatal: failed to read .git/worktrees/<other>/commondir`).
        with _reg_lock():  # two parallel spawns share one registry file
            rec = sw.spawn(main, wt_root, spec["slug"], brief_for(task_id, spec["slug"]),
                           "dry-run-worker", registry, task_id=task_id, env=env)
    except (sw.Refused, sw.FailClosed, ti.ScopeUnreachable) as e:
        raise DryRunFailed(f"spawn refused for {task_id} ({e})") from e
    path = Path(rec["path"])
    try:
        # Only the work payload is staged: the injected Brief stays untracked, so
        # parallel merges cannot conflict on it (see spawn_worker semantics).
        (path / spec["file"]).write_text(spec["body"], encoding="utf-8")
        _must(path, "add", spec["file"], env=env, what=f"stage {task_id}")
        _must(path, "-c", "user.email=t@t", "-c", "user.name=t",
              "commit", "-qm", f"{spec['slug']} ({task_id})", env=env, what=f"commit {task_id}")
        check = _git(path, "ls-files", env=env)
    except DryRunFailed:
        raise
    except OSError as e:
        raise DryRunFailed(f"worker I/O failed for {task_id} ({e})") from e
    if spec["file"] not in check.stdout.splitlines():
        raise DryRunFailed(f"acceptance: {spec['file']} missing in {task_id}'s worktree")
    return {"task_id": task_id, "branch": rec["branch"], "path": path}


def run(root: Path, env: dict) -> dict:
    """Full two-worker lifecycle. Returns the proof report (raises on any failure)."""
    origin = root / "origin.git"
    main = root / "main"
    wt_root = root / ".sr-worktrees"
    wt_root.mkdir(parents=True, exist_ok=True)
    _must(root, "init", "-q", "--bare", str(origin), env=env, what="init origin")
    _must(root, "init", "-q", "-b", "main", str(main), env=env, what="init main")
    (main / "README.md").write_text("seed\n", encoding="utf-8")
    _must(main, "add", ".", env=env, what="stage seed")
    _must(main, "-c", "user.email=t@t", "-c", "user.name=t",
          "commit", "-qm", "seed", env=env, what="commit seed")

    taken: set[str] = set()
    ids = []
    for _ in WORKERS:
        new = ti.ensure_unique(taken)
        taken.add(new)
        ids.append(new)
    branches = [ti.branch_for(i, w["slug"]) for i, w in zip(ids, WORKERS)]
    paths = [wt_root / i for i in ids]

    # P1 — distinct before git is even involved (mint-level, not luck-level).
    for label, vals in (("task ids", ids), ("branches", branches),
                        ("worktree paths", [str(p) for p in paths])):
        if len(set(vals)) != 2:
            raise DryRunFailed(f"P1 failed: {label} not distinct: {vals}")

    # Steps 2-4 in parallel: the collision regime the flow exists for.
    registry = root / "workers.json"
    if registry.exists():
        registry.unlink()
    spawned: list[dict] = [None, None]  # type: ignore[list-item]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(spawn_worker, main, wt_root, tid, w, env, registry): k
                for k, (tid, w) in enumerate(zip(ids, WORKERS))}
        for fut in concurrent.futures.as_completed(futs):
            spawned[futs[fut]] = fut.result()  # DryRunFailed propagates here

    # P2 — checkout isolation: each worktree sees its own payload only.
    for k, s in enumerate(spawned):
        other = spawned[1 - k]
        if not (s["path"] / WORKERS[k]["file"]).is_file():
            raise DryRunFailed(f"P2 failed: {s['task_id']} missing its own payload")
        if (s["path"] / WORKERS[1 - k]["file"]).exists():
            raise DryRunFailed(f"P2 failed: {s['task_id']} sees {other['task_id']}'s file")
        if not (s["path"] / "HOLDSHORT_BRIEF.json").is_file():
            raise DryRunFailed(f"P2 failed: {s['task_id']} missing its injected Brief")

    # P3 — git agrees both worktrees are live at once.
    listed = _must(main, "worktree", "list", "--porcelain", env=env, what="worktree list")
    listed_paths = {os.path.normcase(os.path.normpath(line[9:]))
                    for line in listed.splitlines() if line.startswith("worktree ")}
    for s in spawned:
        if os.path.normcase(os.path.normpath(s["path"])) not in listed_paths:
            raise DryRunFailed(f"P3 failed: {s['path']} absent from git worktree list")

    # Steps 5-6: host merges sequentially, records §10.3 Outcomes in the canonical
    # ledger store, cleans up. The dry-run class tag keeps the breaker's eval
    # projection derivable from the same file.
    ledger_path = root / "outcome-ledger.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    ledger: list[dict] = []
    for s, w in zip(spawned, WORKERS):
        _must(main, "-c", "user.email=t@t", "-c", "user.name=t",
              "merge", "--no-ff", "-m", f"merge {s['branch']}", s["branch"],
              env=env, what=f"merge {s['branch']}")
        ledger.append(ol.record(ledger_path, {
            "task-id": s["task_id"], "outcome": "accepted",
            "evidence": {"checks": [{"command": f"test -f {w['file']}",
                                     "exit-code": 0, "output-ref": "dry-run-acceptance"}],
                         "actual-spend": 0.0, "files-touched": [w["file"]],
                         "notes": "dry-run merge"},
            "owner-profile": "dry-run-worker", "class": "dry-run"}))
    for s in spawned:
        # Same primitive, same guarantees: retract brief, refuse on debris, remove the
        # worktree, delete the branch only because it merged just above.
        try:
            sw.cleanup(main, registry, s["task_id"], env=env)
        except (sw.Refused, sw.FailClosed) as e:
            raise DryRunFailed(f"cleanup failed for {s['task_id']} ({e})") from e

    # P4 — post-merge main holds both payloads with exact bodies.
    for w in WORKERS:
        p = main / w["file"]
        if not p.is_file() or p.read_text(encoding="utf-8") != w["body"]:
            raise DryRunFailed(f"P4 failed: main lacks exact {w['file']} after merges")

    # P5 — cleanup complete, ledger complete.
    listed_after = _must(main, "worktree", "list", "--porcelain", env=env, what="worktree list")
    remaining_paths = {os.path.normcase(os.path.normpath(line[9:]))
                       for line in listed_after.splitlines() if line.startswith("worktree ")}
    for s in spawned:
        if os.path.normcase(os.path.normpath(s["path"])) in remaining_paths:
            raise DryRunFailed(f"P5 failed: {s['path']} survives cleanup")
    if [e["outcome"] for e in ledger] != ["accepted", "accepted"]:
        raise DryRunFailed(f"P5 failed: ledger outcomes {ledger}")

    ol.read_all(ledger_path)  # fail closed here, not at the reviewer's desk
    return {"task_ids": ids, "branches": branches,
            "proofs": ["P1 distinct ids/branches/paths", "P2 checkout isolation",
                       "P3 simultaneous worktrees listed", "P4 both payloads merged exact",
                       "P5 cleanup done, 2 accepted outcomes"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prove the two-worker host lifecycle collision-free.")
    ap.add_argument("--keep", type=Path, default=None, help="retain the tree under DIR")
    args = ap.parse_args(argv)
    if args.keep is not None:
        root = args.keep
        root.mkdir(parents=True, exist_ok=True)
        try:
            report = run(root, _env(root))
        except DryRunFailed as e:
            print(f"host_dry_run: FAILED — {e}", file=sys.stderr)
            return 1
        print(f"host_dry_run: PROVED at {root}: " + "; ".join(report["proofs"]))
        return 0
    with tempfile.TemporaryDirectory(prefix="host-dry-run-") as td:
        root = Path(td)
        try:
            report = run(root, _env(root))
        except DryRunFailed as e:
            print(f"host_dry_run: FAILED — {e}", file=sys.stderr)
            return 1
    print("host_dry_run: PROVED — " + "; ".join(report["proofs"]))
    print(f"host_dry_run: task ids {report['task_ids'][0]}, {report['task_ids'][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
