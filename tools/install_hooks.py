#!/usr/bin/env python3
"""Wire the repo's pre-commit regression gate for this clone.

Every fresh clone must run this once (done automatically by
`bash tools/setup_machine.sh`, or directly: `python tools/install_hooks.py`).

What it does:
  1. Sets the REPO-LOCAL core.hooksPath to `.githooks` (the tracked, canonical
     hook: stashes worktree-only state, runs the full gate on HEAD+index,
     fail-closed). No global git config is touched.
  2. Verifies a conflicting GLOBAL core.hooksPath does not silently win —
     repo-local config always overrides global, but we still warn explicitly
     so the operator knows another toolchain's hooks exist.
  3. Syntax-checks the hook script and confirms `bash` exists to run it.

Fail-closed: any verification failure exits non-zero and leaves config
unchanged (or explicitly reported), never half-wired.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"


def git(args: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main() -> int:
    if not (REPO_ROOT / ".git").is_dir():
        print("install_hooks: not a git repository — nothing to wire", file=sys.stderr)
        return 2
    if not HOOK.is_file():
        print("install_hooks: .githooks/pre-commit missing — aborting (it is the tracked, "
              "fail-closed gate; refusing to install a weaker substitute)", file=sys.stderr)
        return 1

    # 1) Repo-local hooksPath (overrides any global value for this repo only).
    r = git(["config", "--local", "core.hooksPath", ".githooks"])
    if r.returncode != 0:
        print(f"install_hooks: could not set local core.hooksPath: {r.stderr}", file=sys.stderr)
        return 1

    configured = git(["config", "core.hooksPath"]).stdout.strip()
    if configured.replace("\\", "/").rstrip("/") != ".githooks":
        print(f"install_hooks: effective hooksPath is {configured!r}, not .githooks — "
              "refusing to claim success", file=sys.stderr)
        return 1

    # 2) Surface a conflicting global hooksPath (would apply to OTHER repos,
    #    but tells the operator where the machine's global hooks come from).
    g = git(["config", "--global", "core.hooksPath"], cwd=REPO_ROOT)
    if g.returncode == 0 and g.stdout.strip():
        print(f"install_hooks: NOTE — global core.hooksPath is {g.stdout.strip()!r}; "
              "this repo now overrides it with .githooks (repo-local wins).")

    # 3) Hook must be bash-parseable and bash must exist.
    probe = subprocess.run(["bash", "-n", str(HOOK)], capture_output=True, text=True)
    if probe.returncode != 0:
        print(f"install_hooks: hook script syntax check failed:\n{probe.stderr}", file=sys.stderr)
        return 1

    print("install_hooks: pre-commit gate wired (repo-local core.hooksPath=.githooks). "
          "Every commit now runs the full regression gate on this clone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
