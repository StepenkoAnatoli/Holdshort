#!/usr/bin/env python3
"""Cursor host adapter skeleton."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"


def run_policy_check() -> int:
    return subprocess.call([sys.executable, str(TOOLS / "validate_skills.py"), "--strict"])


def main() -> int:
    print("Cursor host adapter skeleton. Implement model calls via Cursor's agent API.")
    return run_policy_check()


if __name__ == "__main__":
    raise SystemExit(main())
PY