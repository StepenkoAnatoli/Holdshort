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
  N+4. tools/test_redact_text.py           — the pre-write redaction filter reuses the
                                             app-DB pattern set; its hermetic test joins
                                             the gate so prevention cannot drift from
                                             detection.
  N+5. tools/test_host_watchdog.py         — the host loop-prevention enforcer (wall-clock
                                             timeout, one-repair-total cap per R01-R03,
                                             no-progress escalation, needs-human package);
                                             its hermetic test joins the gate so the HITL
                                             contract cannot rot unseen.
  N+6. tools/test_task_ids.py               — task-id mint/format/entropy/uniqueness
                                             semantics + live-scope collision checks.
  N+7. tools/test_host_dry_run.py            — two-parallel-worker lifecycle proof
                                             (throwaway repo, real git worktrees).
  N+8. tools/test_class_breaker.py           — breaker split: facts per task, class rates
                                             only under eval-prep authorization.
  N+9. tools/test_outcome_ledger.py          — canonical §10.3 Outcome store (record/get/
                                             list/verify, fail-closed schema).
  N+10. tools/test_check_provenance.py       — diff-vs-branch provenance for review
                                             (scope, naming, base, worktree binding).
  N+11. tools/test_spawn_worker.py           — host spawn primitive (worktree+branch,
                                             verbatim Brief, registry, merge-gated cleanup).
  N+12. tools/test_guard_launch.py           — pre-launch refusal outside the dedicated
                                             worktree (main checkout, bare dirs, wrong task).
  N+13. tools/test_docs_drift.py             — background-docs-to-spec-v2 pin (blocks,
                                             enums, branch naming, Brief filename note).
  N+14b. tools/test_skill_adherence.py        — G2 skill-text pin (normative sentences
                                             survive verbatim) + sample/score harness.
  N+14. tools/test_conform_spec.py           — §10 object conformance (Brief, SpeculativeSet,
                                             Outcome, NestedBrief bounds, LedgerRecord) with
                                             §12 violations failing the gate.
  N+9. tools/test_watch_app_db_secrets.py— the watcher that scans those stores on
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
    ("decision_fixtures", [sys.executable, "tests/holdshort_decisions.py"]),
    ("test_reservation_fixtures", [sys.executable, "tools/test_reservation_fixtures.py"]),
    ("test_live_dispatcher", [sys.executable, "tools/test_live_dispatcher.py"]),
    ("test_shadow_mode", [sys.executable, "tools/test_shadow_mode.py"]),
    ("test_dispatch_budget", [sys.executable, "tools/test_dispatch_budget.py"]),
    ("test_dispatch_adapter", [sys.executable, "tools/test_dispatch_adapter.py"]),
    ("test_adapter_config", [sys.executable, "tools/test_adapter_config.py"]),
    ("test_billing_qualification", [sys.executable, "tools/test_billing_qualification.py"]),
    ("test_offline_deepseek_adapter", [sys.executable, "tools/test_offline_deepseek_adapter.py"]),
    ("test_eval_pool", [sys.executable, "tools/test_eval_pool.py"]),
    ("test_pricing", [sys.executable, "tools/test_pricing.py"]),
    ("test_pilot_close", [sys.executable, "tools/test_pilot_close.py"]),
    ("test_task_persistence", [sys.executable, "tools/test_task_persistence.py"]),
    ("test_task_state_owner", [sys.executable, "tools/test_task_state_owner.py"]),
    ("test_task_crosscheck", [sys.executable, "tools/test_task_crosscheck.py"]),
    ("test_claude_code_host_artifacts", [sys.executable, "tools/test_claude_code_host_artifacts.py"]),
    ("test_calibration_kit", [sys.executable, "tools/test_calibration_kit.py"]),
    ("test_generic_host", [sys.executable, "tools/test_generic_host.py"]),
    ("test_check_calibration_evidence", [sys.executable, "tools/test_check_calibration_evidence.py"]),
    ("check_calibration_evidence", [sys.executable, "tools/check_calibration_evidence.py"]),
    ("test_qualification_table", [sys.executable, "tools/test_qualification_table.py"]),
    ("qualification_table", [sys.executable, "tools/qualification_table.py", "--check"]),
    ("test_install_hooks", [sys.executable, "tools/test_install_hooks.py"]),
    ("test_hook_wiring", [sys.executable, "tools/test_hook_wiring.py"]),
    ("test_strict_canary", [sys.executable, "tools/test_strict_canary.py"]),
    ("test_clone_freshness", [sys.executable, "tools/test_clone_freshness.py"]),
    ("live_fill_sheet_integrity", [sys.executable, "tools/live_fill_tally.py", "--mode", "gate"]),
    ("test_pilot_report", [sys.executable, "tools/test_pilot_report.py"]),
    ("test_live_fill_tally", [sys.executable, "tools/test_live_fill_tally.py"]),
    ("test_arm_matrix", [sys.executable, "tools/test_arm_matrix.py"]),
    ("test_secrets_env_guard", [sys.executable, "tools/test_secrets_env_guard.py"]),
    ("test_fixture_key_hygiene", [sys.executable, "tools/test_fixture_key_hygiene.py"]),
    ("test_redact_text", [sys.executable, "tools/test_redact_text.py"]),
    ("test_redaction", [sys.executable, "tools/test_redaction.py"]),
    ("test_message_schema", [sys.executable, "tools/test_message_schema.py"]),
    ("message_schema", [sys.executable, "tools/check_message_schema.py"]),
    ("check_secrets", [sys.executable, "tools/check_secrets.py"]),
    ("test_credential_hygiene", [sys.executable, "tools/test_credential_hygiene.py"]),
    ("credential_hygiene", [sys.executable, "tools/check_credential_hygiene.py"]),
    ("test_custody_acl", [sys.executable, "tools/test_custody_acl.py"]),
    ("custody_acl", [sys.executable, "tools/check_custody_acl.py"]),
    ("test_app_db_secrets", [sys.executable, "tools/test_app_db_secrets.py"]),
    ("app_db_secrets", [sys.executable, "tools/check_app_db_secrets.py"]),
    ("test_redact_text", [sys.executable, "tools/test_redact_text.py"]),
    ("test_host_watchdog", [sys.executable, "tools/test_host_watchdog.py"]),
    ("test_usage_snapshot", [sys.executable, "tools/test_usage_snapshot.py"]),
    ("test_project_scope", [sys.executable, "tools/test_project_scope.py"]),
    ("test_task_ids", [sys.executable, "tools/test_task_ids.py"]),
    ("test_host_dry_run", [sys.executable, "tools/test_host_dry_run.py"]),
    ("test_class_breaker", [sys.executable, "tools/test_class_breaker.py"]),
    ("test_outcome_ledger", [sys.executable, "tools/test_outcome_ledger.py"]),
    ("test_check_provenance", [sys.executable, "tools/test_check_provenance.py"]),
    ("test_spawn_worker", [sys.executable, "tools/test_spawn_worker.py"]),
    ("test_guard_launch", [sys.executable, "tools/test_guard_launch.py"]),
    ("test_docs_drift", [sys.executable, "tools/test_docs_drift.py"]),
    ("test_skill_adherence", [sys.executable, "tools/test_skill_adherence.py"]),
    ("test_conform_spec", [sys.executable, "tools/test_conform_spec.py"]),
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
