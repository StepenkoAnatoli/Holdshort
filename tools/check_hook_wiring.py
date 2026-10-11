#!/usr/bin/env python3
"""Check that the pre-commit gate is actually wired on this checkout.

Fails the gate (exit 1) when the hook cannot fire, i.e. when Layer 1 is
silently bypassable locally:

  * repo-local core.hooksPath != `.githooks` (unset, wrong, or global-only —
    the same stale-copy failure that motivated 97a7e83),
  * `.githooks/pre-commit` missing from the worktree or not a plain file,
  * hook lost its executable bit (the real failure 967a179 shipped once),
  * tracked mode in git is not 100755 (a future commit could ship an
    un-runnable hook that looks fine on Windows checkouts).

CI awareness: on GitHub Actions (GITHUB_ACTIONS set, overridable per-call)
there is no local checkout wiring to verify — CI IS layer 2 — so only the
tracked-mode assertion runs. No env-var escape hatch on a dev checkout:
the operator cannot sneak past the check by setting a variable, only by
actually wiring (`python tools/install_hooks.py`).

Designed to sit FIRST in run_regression.py CHECKS: a gate that cannot be
triggered by commits must not itself pretend to be green.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
EXPECTED_MODE = "100755"


def _on_ci(env: dict | None = None) -> bool:
    return (env if env is not None else os.environ).get("GITHUB_ACTIONS") == "true"


def tracked_mode(root: Path) -> str | None:
    """Mode git has for the hook in `root`, or None if untracked/unreadable."""
    out = subprocess.run(["git", "ls-files", "-s", "--", ".githooks/pre-commit"],
                         cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    line = out.stdout.strip()
    return line.split(" ", 1)[0] if line else None


def local_config_value(key: str, root: Path) -> str | None:
    """Repo-local config only (a global value must never count as wiring)."""
    out = subprocess.run(["git", "config", "--local", "--get", key],
                         cwd=root, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def wiring_problems_for(root: Path, ci: bool = False) -> list[str]:
    """All Layer-1 wiring problems in `root`'s checkout (empty = wired)."""
    problems: list[str] = []

    mode = tracked_mode(root)
    if mode is None:
        problems.append(".githooks/pre-commit is not tracked by git — the tracked, "
                        "canonical hook is gone from the index")
    elif mode != EXPECTED_MODE:
        problems.append(f".githooks/pre-commit is tracked as mode {mode}, expected "
                        f"{EXPECTED_MODE} (executable bit lost — hook will not fire on Linux)")

    if ci:
        # Only the tracked-side assertion applies here; return early so a
        # bare CI checkout's unset config does not fail the mirror view.
        return problems

    hook = root / ".githooks" / "pre-commit"

    configured = local_config_value("core.hooksPath", root)
    normalized = configured.replace("\\", "/").rstrip("/") if configured else None
    if normalized is None:
        problems.append("repo-local core.hooksPath is unset — run `python tools/install_hooks.py` "
                        "to wire the pre-commit gate")
    elif normalized != ".githooks":
        problems.append(f"repo-local core.hooksPath is {configured!r}, expected '.githooks'")

    if not hook.exists():
        problems.append(f"{hook} missing from the worktree (deleted after wiring?)")
    elif not hook.is_file():
        problems.append(f"{hook} is not a plain file")
    elif sys.platform != "win32" and not os.stat(hook).st_mode & stat.S_IXUSR:
        problems.append(f"{hook} exists but is not executable "
                        "(exec bit lost — hook is silently skipped by git)")

    return problems


def wiring_problems(root: Path | None = None) -> list[str]:
    """Convenience wrapper used by run_regression.py and the CLI."""
    r = root or REPO_ROOT
    return wiring_problems_for(r, ci=_on_ci())


def parse_args(argv: list[str] | None = None):
    import argparse
    ap = argparse.ArgumentParser(description="Verify the pre-commit gate is wired on this checkout.")
    ap.add_argument("--root", type=Path, default=None,
                    help="repo root to check (default: the checkout containing this tool)")
    return ap.parse_args(argv)


def main(root: Path | None = None) -> int:
    problems = wiring_problems(root)
    if problems:
        print("hook_wiring: FAIL — pre-commit gate is NOT enforcing on this checkout:")
        for p in problems:
            print(f"  - {p}")
        print("  fix: python tools/install_hooks.py   (repo-local core.hooksPath=.githooks)")
        return 1
    cfg = ON_CI_SCOPE if _on_ci() else LOCAL_SCOPE
    print(f"hook_wiring: OK ({cfg} verified)")
    return 0


ON_CI_SCOPE = "tracked mode"
LOCAL_SCOPE = "hooksPath + hook file + exec bit + tracked mode"

if __name__ == "__main__":
    args = parse_args()
    sys.exit(main(args.root))
