#!/usr/bin/env python3
"""Host-side spawn_worker — create the worktree+branch, inject the Brief, clean up.

The companions describe this lifecycle in prose (host-worktree-flow/agents/registry/merge)
and `tools/host_dry_run.py` proved it twice-over in a throwaway repo, but no importable,
tested host primitive existed — every host retyped `git worktree add` by hand. This is
that primitive (library + CLI), stdlib only:

  * `spawn`: mint-or-take a task id (`tools/task_ids.py`: secrets entropy + live-scope
    uniqueness), `git worktree add -b sr/<id>/<slug>` in the OUTSIDE form, inject the
    EXACT Brief bytes (`SMARTROUTER_BRIEF.json`, untracked — never committed, so parallel
    merges cannot conflict on it), record task_id → {path, branch, profile} in the
    registry. Any step failing leaves no half-spawn (worktree removed, registry untouched).
  * Shared-surface plan (G7 — worktrees isolate git only, not ports/DBs/env):
    `spawn(..., shared=...)` records the per-task plan: `{"no_shared_surface": True}`
    for stateless file tasks, or `{"env_scope": ..., "ports": [...],
    "namespace": ...}` for stateful ones. Port overlap with a live registry
    worker REFUSES (parallel workers must never share a mutable service
    endpoint). `require_shared_plan=True` (or the CLI without either
    `--shared-plan`/`--no-shared-surface` under `--require-shared-plan`)
    refuses unattested spawns fail-closed.
  * `cleanup`: retract the injected Brief, `git worktree remove`, delete the branch —
    but only when merged into the base (default `main`); an unmerged branch refuses
    closed unless `--allow-unmerged` (abandonment still consumes its dispatches, and the
    branch is kept for forensics while the worktree is removed).

Registry (JSON): the host's `workers` mapping from host-worktree-registry.md, persisted
instead of in-memory so restarts keep it (spec-v2 §11 duty 8 is the full Outcome Ledger;
this registry is the spawn bookkeeping that feeds it). Duplicate task ids are refused,
never overwritten. All writes atomic (tmp + rename).

Exit codes: 0 done (spawn prints the record JSON); 1 usage/collision/refusal with reason;
2 fail-closed (git unreadable, registry corrupt, half-spawn rollback failed).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BRIEF_FILENAME = "SMARTROUTER_BRIEF.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ti = _load("tids_spawn", TOOLS / "task_ids.py")


class FailClosed(RuntimeError):
    pass


class Refused(RuntimeError):
    pass


def _git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=120)
    except OSError as e:
        raise FailClosed(f"git unavailable ({e})") from e


def _must(cwd: Path, *args: str, env: dict | None, what: str) -> str:
    proc = _git(cwd, *args, env=env)
    if proc.returncode != 0:
        raise FailClosed(f"{what} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def load_registry(path: Path) -> dict:
    if not path.is_file():
        return {"workers": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FailClosed(f"registry {path} unreadable ({e})") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("workers"), dict):
        raise FailClosed(f"registry {path} malformed (want {{'workers': {{...}}}})")
    return doc


def save_registry(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def brief_fingerprint(brief_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(brief_bytes).hexdigest()[:16]


def check_shared_plan(shared: dict | None, registry: dict) -> dict:
    """Validate a shared-surface plan, enforcing port exclusivity (G7).

    Returns the normalized record (`{"attested": False}` when no plan was
    supplied — auditable, not trusted). Raises Refused on port overlap with a
    live worker or on malformed plans.
    """
    if shared is None:
        return {"attested": False}
    if not isinstance(shared, dict):
        raise Refused("shared plan must be an object (or omit it for unattested)")
    if shared.get("no_shared_surface") is True:
        return {"attested": True, "no_shared_surface": True}
    ports = shared.get("ports", [])
    if not isinstance(ports, list) or any(not isinstance(x, int) for x in ports):
        raise Refused("shared plan 'ports' must be a list of ints")
    live_ports: dict[int, str] = {}
    for tid, rec in registry.get("workers", {}).items():
        for x in (rec.get("shared") or {}).get("ports", []):
            live_ports.setdefault(x, tid)
    clash = [x for x in ports if x in live_ports]
    if clash:
        raise Refused(f"port(s) {clash} already held by worker {live_ports[clash[0]]!r} — "
                      f"parallel workers must not share a mutable endpoint")
    plan = {"attested": True}
    for k in ("env_scope", "ports", "namespace", "note"):
        if k in shared:
            plan[k] = shared[k]
    return plan


def spawn(repo: Path, wt_root: Path, slug: str, brief: dict, profile: str,
          registry_path: Path, *, task_id: str | None = None,
          env: dict | None = None, shared: dict | None = None,
          require_shared_plan: bool = False) -> dict:
    """Full spawn. Returns the worker record. Raises Refused/FailClosed, never half-spawns."""
    if not isinstance(brief, dict) or not brief:
        raise Refused("brief must be a non-empty object (verbatim injection, no invention)")
    if not profile:
        raise Refused("profile must name the exact identity tuple for the worker")
    reg = load_registry(registry_path)
    if require_shared_plan and not (isinstance(shared, dict) and shared):
        raise Refused("shared-surface plan required (--require-shared-plan): pass "
                      "--no-shared-surface for stateless tasks or --shared-plan '{...}'")
    taken = set(reg["workers"]) | ti.collect_taken(repo)
    chosen = task_id or ti.ensure_unique(taken)
    if not ti.valid(chosen):
        raise Refused(f"task id {chosen!r} invalid (want {ti.TASK_ID_RE.pattern})")
    if chosen in reg["workers"] or chosen in taken:
        raise Refused(f"task id {chosen!r} already taken — refusing a shared checkout")
    branch = ti.branch_for(chosen, slug)
    path = wt_root / chosen
    if path.exists():
        raise Refused(f"worktree path {path} already exists")
    wt_root.mkdir(parents=True, exist_ok=True)
    _must(repo, "worktree", "add", "-b", branch, str(path), "main",
          env=env, what=f"worktree add {chosen}")
    try:
        raw = (json.dumps(brief, indent=2, sort_keys=True) + "\n").encode("utf-8")
        (path / BRIEF_FILENAME).write_bytes(raw)
        fp = brief_fingerprint(raw)
    except OSError as e:
        _git(repo, "worktree", "remove", "--force", str(path), env=env)
        raise FailClosed(f"brief injection failed, spawn rolled back ({e})") from e
    plan = check_shared_plan(shared, reg)
    reg["workers"][chosen] = {"path": str(path), "branch": branch, "profile": profile,
                              "brief_fingerprint": fp, "shared": plan}
    try:
        save_registry(registry_path, reg)
    except OSError as e:
        _git(repo, "worktree", "remove", "--force", str(path), env=env)
        raise FailClosed(f"registry write failed, spawn rolled back ({e})") from e
    return {"task_id": chosen, "path": str(path), "branch": branch,
            "profile": profile, "brief_fingerprint": fp, "shared": plan}


def cleanup(repo: Path, registry_path: Path, task_id: str, *,
            base: str = "main", allow_unmerged: bool = False,
            env: dict | None = None) -> dict:
    """Retract brief, remove worktree, delete branch iff merged. Returns what was done."""
    reg = load_registry(registry_path)
    rec = reg["workers"].get(task_id)
    if rec is None:
        raise Refused(f"no registry entry for {task_id!r} — refusing blind cleanup")
    path, branch = Path(rec["path"]), rec["branch"]
    (path / BRIEF_FILENAME).unlink(missing_ok=True)  # environment, never branch content
    # Never destroy evidence: after retracting an UNTRACKED brief a clean worktree is
    # empty-status. Anything else is uncommitted worker output (or a committed brief —
    # the harness bug host_dry_run documents) and refuses closed for the operator.
    dirt = _must(path, "status", "--porcelain", env=env, what="worktree status")
    if dirt.strip():
        raise FailClosed(f"worktree {path} has uncommitted content after brief retraction "
                         f"({dirt.strip()[:200]}) — commit or stash it before cleanup")
    _must(repo, "worktree", "remove", str(path), env=env, what=f"worktree remove {task_id}")
    merged = _must(repo, "branch", "--merged", base, env=env, what="merged list")
    is_merged = branch in [b.strip().lstrip("*+ ") for b in merged.splitlines()]
    branch_deleted = False
    if is_merged:
        _must(repo, "branch", "-d", branch, env=env, what=f"branch delete {branch}")
        branch_deleted = True
    elif not allow_unmerged:
        raise Refused(f"{branch} not merged into {base} — refusing branch delete "
                      f"(pass --allow-unmerged to abandon; dispatches stay consumed)")
    del reg["workers"][task_id]
    try:
        save_registry(registry_path, reg)
    except OSError as e:
        raise FailClosed(f"registry write failed ({e})") from e
    return {"task_id": task_id, "worktree_removed": True,
            "branch_deleted": branch_deleted, "abandoned": not is_merged}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Host worktree+branch worker lifecycle.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spawn", help="mint id, add worktree+branch, inject Brief, register")
    s.add_argument("--repo", type=Path, required=True)
    s.add_argument("--wt-root", type=Path, required=True)
    s.add_argument("--slug", required=True)
    s.add_argument("--brief", type=Path, required=True, help="Brief JSON file, injected verbatim")
    s.add_argument("--profile", required=True)
    s.add_argument("--registry", type=Path, required=True)
    s.add_argument("--task-id", default=None)
    s.add_argument("--shared-plan", default=None,
                   help="JSON object: shared-surface plan (env_scope/ports/namespace)")
    s.add_argument("--no-shared-surface", action="store_true",
                   help="attest the task uses no shared mutable surface (stateless files only)")
    s.add_argument("--require-shared-plan", action="store_true",
                   help="refuse the spawn unless a plan is attested (fail-closed)")
    c = sub.add_parser("cleanup", help="retract brief, remove worktree, delete merged branch")
    c.add_argument("--repo", type=Path, required=True)
    c.add_argument("--registry", type=Path, required=True)
    c.add_argument("--task-id", required=True)
    c.add_argument("--base", default="main")
    c.add_argument("--allow-unmerged", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "spawn":
            try:
                brief = json.loads(args.brief.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise FailClosed(f"brief {args.brief} unreadable ({e})") from e
            if args.shared_plan and args.no_shared_surface:
                raise Refused("--shared-plan and --no-shared-surface are exclusive")
            shared = {"no_shared_surface": True} if args.no_shared_surface else None
            if args.shared_plan:
                try:
                    shared = json.loads(args.shared_plan)
                except json.JSONDecodeError as e:
                    raise FailClosed(f"--shared-plan malformed ({e})") from e
            rec = spawn(args.repo, args.wt_root, args.slug, brief, args.profile,
                        args.registry, task_id=args.task_id, shared=shared,
                        require_shared_plan=args.require_shared_plan)
            print(json.dumps(rec, indent=2, sort_keys=True))
            return 0
        done = cleanup(args.repo, args.registry, args.task_id,
                       base=args.base, allow_unmerged=args.allow_unmerged)
        print(json.dumps(done, indent=2, sort_keys=True))
        return 0
    except Refused as e:
        print(f"spawn_worker: REFUSED — {e}", file=sys.stderr)
        return 1
    except (FailClosed, ti.ScopeUnreachable) as e:
        print(f"spawn_worker: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
