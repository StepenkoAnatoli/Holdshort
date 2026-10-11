#!/usr/bin/env python3
"""One-command regression gate — run every repo check in order, stop on first failure.

Checks (in order):
  0. tools/check_hook_wiring.py          — pre-commit gate is wired (Layer-1 self-check)
  1. tools/validate_skills.py            — packaging/authority validator
  2. tools/test_live_dispatcher.py       — §5 caps + Gate-4 suite (26 checks)
  3. tools/test_pilot_report.py          — ledger aggregation suite (10 tests)
  ...
  N. tools/check_secrets.py              — credential-shaped strings in tracked files

Each subprocess's exit status is preserved (no output filtering that can mask
failure). Exit 0 only when ALL pass; nonzero reports which check failed first.
Extra checks can be added to CHECKS; keep order cheap→expensive for fast
feedback.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent

CHECKS = [
    ("hook_wiring", [sys.executable, "tools/check_hook_wiring.py"]),
    ("validate_skills", [sys.executable, "tools/validate_skills.py"]),
    ("test_live_dispatcher", [sys.executable, "tools/test_live_dispatcher.py"]),
    ("test_dispatch_adapter", [sys.executable, "tools/test_dispatch_adapter.py"]),
    ("test_pilot_close", [sys.executable, "tools/test_pilot_close.py"]),
    ("test_task_persistence", [sys.executable, "tools/test_task_persistence.py"]),
    ("test_task_crosscheck", [sys.executable, "tools/test_task_crosscheck.py"]),
    ("test_install_hooks", [sys.executable, "tools/test_install_hooks.py"]),
    ("test_hook_wiring", [sys.executable, "tools/test_hook_wiring.py"]),
    ("test_strict_canary", [sys.executable, "tools/test_strict_canary.py"]),
    ("live_fill_sheet_integrity", [sys.executable, "tools/live_fill_tally.py", "--mode", "gate"]),
    ("test_pilot_report", [sys.executable, "tools/test_pilot_report.py"]),
    ("test_arm_matrix", [sys.executable, "tools/test_arm_matrix.py"]),
    ("test_secrets_env_guard", [sys.executable, "tools/test_secrets_env_guard.py"]),
    ("check_secrets", [sys.executable, "tools/check_secrets.py"]),
]


def main() -> int:
    failures = []
    for name, cmd in CHECKS:
        print(f"== {name} ==")
        proc = subprocess.run(cmd, cwd=REPO_ROOT)
        if proc.returncode == 0:
            print(f"   PASS (exit 0)")
        else:
            print(f"   FAIL (exit {proc.returncode})")
            failures.append((name, proc.returncode))
            break  # fail-fast: report the first failure, don't cascade noise

    if failures:
        print(f"\nREGRESSION GATE: {len(failures)} failure(s): {failures}")
        return 1
    print("\nREGRESSION GATE: all checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
