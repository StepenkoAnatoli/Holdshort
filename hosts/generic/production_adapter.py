#!/usr/bin/env python3
"""Production host adapter template — full integration pattern.

Shows how to wire Holdshort into a coding-agent host:
  1. Policy check (validate_skills)
  2. Dispatch with qualification (dispatch_adapter or config-driven)
  3. Supervised command execution (host_watchdog)
  4. Outcome recording (conform_spec)
  5. Shadow mode for evidence collection

Replace the model-call and billing sections with your host's implementation.
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
            qualification: str | None = None) -> tuple[int, dict]:
    tmp = Path(tempfile.mkdtemp())
    ledger = tmp / "ledger.jsonl"
    out = tmp / "dispatch.json"
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
    with open(out, "w") as f:
        rc = subprocess.call(cmd, stdout=f)
    result = json.loads(out.read_text()) if out.exists() else {}
    return rc, result


def supervise(command: list[str], task_id: str, state: Path, timeout: int = 30) -> int:
    return subprocess.call([
        sys.executable, str(TOOLS / "host_watchdog.py"),
        "--task-id", task_id, "--state", str(state), "--timeout", str(timeout),
        "--", *command,
    ])


def main() -> int:
    print("=== Production adapter (dry-run) ===")

    # 1. Policy check
    print("1. Policy check...")
    if policy_check() != 0:
        print("   FAIL")
        return 1
    print("   OK")

    # 2. Dispatch in shadow mode (collect evidence, don't enforce)
    print("2. Dispatch (shadow mode)...")
    rc, result = dispatch("cloud-C", "prod-demo", "probe", shadow=True)
    print(f"   rc={rc} decision={result.get('decision')}")
    if rc not in (0, 1):
        print("   FAIL")
        return 1

    # 3. Supervised command
    print("3. Supervised command...")
    tmp = Path(tempfile.mkdtemp())
    state = tmp / "state.json"
    rc = supervise([sys.executable, "-c", "print('ok')"], "prod-demo", state)
    print(f"   rc={rc}")
    if rc != 0:
        print("   FAIL")
        return 1

    print("=== Production adapter: DONE (dry-run) ===")
    print("Replace model calls and billing with your host's implementation.")
    print("Use --shadow for evidence collection before enforcing caps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY