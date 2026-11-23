#!/usr/bin/env python3
"""Host integration template — dry-run wiring, not a production router.

Shows how to wire Holdshort into a coding-agent host:
  1. Policy check (validate_skills)
  2. Dispatch dry-run against a caller-owned, reusable ledger
  3. Supervised command execution (host_watchdog)
  4. Shadow mode for evidence collection

The host must implement authorized transport, qualification, acceptance checks,
and outcome recording before production use. Keep one ledger per pilot across
calls and restarts so reservations, counters, and terminal stops remain durable.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"


def policy_check() -> int:
    return subprocess.call([sys.executable, str(TOOLS / "validate_skills.py"), "--strict"])


def dispatch(profile: str, task_id: str, request: str, *, shadow: bool = False,
            ledger: Path,
            qualification: str | None = None) -> tuple[int, dict]:
    cmd = [
        sys.executable, str(TOOLS / "live_dispatcher.py"),
        "--profile", profile, "--task-id", task_id, "--request", request,
        "--work-bound", "0.01", "--review-bound", "0.01",
        "--expected-in-tokens", "1000", "--expected-out-tokens", "100",
        "--ledger", str(ledger),
    ]
    if shadow:
        cmd.append("--shadow")
    if qualification:
        cmd.extend(["--billing-qualification", qualification])
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    result = json.loads(completed.stdout) if completed.stdout.strip() else {}
    return completed.returncode, result


def supervise(command: list[str], task_id: str, state: Path, timeout: int = 30) -> int:
    return subprocess.call([
        sys.executable, str(TOOLS / "host_watchdog.py"),
        "--task-id", task_id, "--state", str(state), "--timeout", str(timeout),
        "--", *command,
    ])


def run_demo(tmp: Path) -> int:
    print("=== Host integration template (dry-run) ===")

    # 1. Policy check
    print("1. Policy check...")
    if policy_check() != 0:
        print("   FAIL")
        return 1
    print("   OK")

    # 2. Dispatch in shadow mode (label evidence, retaining every safeguard)
    print("2. Dispatch (shadow mode)...")
    rc, result = dispatch("cloud-C", "prod-demo", "probe", shadow=True,
                          ledger=tmp / "ledger.jsonl")
    print(f"   rc={rc} decision={result.get('decision')}")
    if rc not in (0, 1):
        print("   FAIL")
        return 1

    # 3. Supervised command
    print("3. Supervised command...")
    state = tmp / "state.json"
    rc = supervise([sys.executable, "-c", "print('ok')"], "prod-demo", state)
    print(f"   rc={rc}")
    if rc != 0:
        print("   FAIL")
        return 1

    print("=== Host integration template: DONE (dry-run) ===")
    print("Replace model calls and billing with your host's implementation.")
    print("Use --shadow to label evidence; caps and terminal stops remain enforced.")
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        return run_demo(Path(directory))


if __name__ == "__main__":
    raise SystemExit(main())
