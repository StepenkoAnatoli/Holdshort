#!/usr/bin/env python3
"""Reference full loop (dry-run): policy check -> supervised command -> dispatch dry-run -> close.

This is a template, not a production router. Replace model calls and billing
with your host's implementation. All steps here are network-free.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"


def step(name, fn):
    print(f"==> {name}")
    rc = fn()
    print(f"    rc={rc}")
    return rc


def run_demo(tmp: Path) -> int:
    # 1. Policy check
    def policy():
        return subprocess.call([sys.executable, str(TOOLS / "validate_skills.py"), "--strict"])
    if step("policy check", policy) != 0:
        return 1

    # 2. Supervised harmless command
    state = tmp / "state.json"
    def supervised():
        return subprocess.call([
            sys.executable, str(TOOLS / "host_watchdog.py"),
            "--task-id", "full-loop-demo", "--state", str(state), "--timeout", "10",
            "--", sys.executable, "-c", "print('ok')",
        ])
    if step("supervised command", supervised) != 0:
        return 1

    # 3. Dispatch dry-run (no network)
    ledger = tmp / "ledger.jsonl"
    out = tmp / "dispatch.json"
    def dispatch():
        with open(out, "w") as f:
            return subprocess.call([
                sys.executable, str(TOOLS / "live_dispatcher.py"),
                "--profile", "cloud-C", "--task-id", "full-loop-demo",
                "--request", "probe", "--work-bound", "0.01", "--review-bound", "0.01",
                "--expected-in-tokens", "1000", "--expected-out-tokens", "100",
                "--ledger", str(ledger),
            ], stdout=f)
    if step("dispatch dry-run", dispatch) != 0:
        return 1
    print("    ", json.loads(out.read_text())["decision"])

    # 4. Produce the session-close accounting report from this same ledger.
    if step("session-close report", lambda: subprocess.call([
            sys.executable, str(TOOLS / "pilot_close.py"), "--ledger", str(ledger)])) != 0:
        return 1

    print("full_loop: DONE (dry-run)")
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        return run_demo(Path(directory))


if __name__ == "__main__":
    raise SystemExit(main())
