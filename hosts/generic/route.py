#!/usr/bin/env python3
"""Generic host adapter skeleton — wiring example, not a production router.

Replace the model-call and billing sections with your host's implementation.
Keep the fail-closed posture: refuse on missing qualification, unknown usage,
or an exhausted budget.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"


def run_policy_check() -> int:
    return subprocess.call([sys.executable, str(TOOLS / "validate_skills.py"), "--strict"])


def supervise(command: list[str], task_id: str, state: Path, timeout: int = 30) -> int:
    return subprocess.call(
        [sys.executable, str(TOOLS / "host_watchdog.py"),
         "--task-id", task_id, "--state", str(state), "--timeout", str(timeout), "--", *command]
    )


def main(argv=None) -> int:
    print("Generic host adapter skeleton. Implement model calls and billing here.")
    return run_policy_check()


if __name__ == "__main__":
    raise SystemExit(main())
PY