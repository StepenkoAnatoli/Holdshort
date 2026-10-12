#!/usr/bin/env python3
"""One-command regression gate — run every repo check in order, stop on first failure.

Checks (in order):
  0. tools/check_hook_wiring.py          — pre-commit gate is wired (Layer-1 self-check)
  1. tools/validate_skills.py            — packaging/authority validator
  2. tools/test_live_dispatcher.py       — §5 caps + Gate-4 suite (26 checks)
  3. tools/test_clone_freshness.py       — clone-parity contract (temp-repo fixture)
  4. tools/test_pilot_report.py          — ledger aggregation suite (10 tests)
  ...
  N. tools/check_secrets.py              — credential-shaped strings in tracked files
  N+1. tools/test_credential_hygiene.py  — orphaned gh keyring tokens / stale stored
                                           credentials (baseline-triaged)
  N+2. tools/test_custody_acl.py         — the credential custody tree's ACL stays
                                           locked to the user alone (N/A off-machine)
  N+3. tools/test_app_db_secrets.py      — token-shaped strings in the Freebuff
                                           Desktop app stores (desktop-v2.db*),
                                           baseline-allowlisted after triage
  N+4. tools/test_watch_app_db_secrets.py— the watcher that scans those stores on
                                             change runs OUTSIDE the gate (it is a
                                             long-lived process, started by the
                                             operator); its hermetic test joins the
                                             gate so the watcher cannot rot unseen.
                                             Last because it is the slowest suite
                                             here (~11s: it starts real watchers).

Each subprocess's exit status is preserved (no output filtering that can mask
failure). Exit 0 only when ALL pass; nonzero reports which check failed first.
Extra checks can be added to CHECKS; keep order cheap→expensive for fast
feedback.

Note: tools/check_clone_freshness.py itself is deliberately NOT a gate step —
it can only answer with the remote reachable, and this gate must run offline
(on every commit). Its hermetic test above is what joins this list; the
checker itself is the operator's runbook §0 precondition.
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
    ("test_clone_freshness", [sys.executable, "tools/test_clone_freshness.py"]),
    ("live_fill_sheet_integrity", [sys.executable, "tools/live_fill_tally.py", "--mode", "gate"]),
    ("test_pilot_report", [sys.executable, "tools/test_pilot_report.py"]),
    ("test_arm_matrix", [sys.executable, "tools/test_arm_matrix.py"]),
    ("test_secrets_env_guard", [sys.executable, "tools/test_secrets_env_guard.py"]),
    ("test_fixture_key_hygiene", [sys.executable, "tools/test_fixture_key_hygiene.py"]),
    ("check_secrets", [sys.executable, "tools/check_secrets.py"]),
    ("test_credential_hygiene", [sys.executable, "tools/test_credential_hygiene.py"]),
    ("credential_hygiene", [sys.executable, "tools/check_credential_hygiene.py"]),
    ("test_custody_acl", [sys.executable, "tools/test_custody_acl.py"]),
    ("custody_acl", [sys.executable, "tools/check_custody_acl.py"]),
    ("test_app_db_secrets", [sys.executable, "tools/test_app_db_secrets.py"]),
    ("app_db_secrets", [sys.executable, "tools/check_app_db_secrets.py"]),
    ("test_watch_app_db_secrets", [sys.executable, "tools/test_watch_app_db_secrets.py"]),
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
