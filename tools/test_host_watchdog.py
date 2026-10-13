#!/usr/bin/env python3
"""Tests for tools/host_watchdog.py — HITL §6/§9 supervision verdicts.

Pins the tightened repair cap (one same-profile corrective dispatch per
original task in total — implementation, CI and review-feedback corrections
share it; plan R01/R02/R03), §9.5 wall-clock timeout semantics (strictly
before; equality expires; the persisted `started` anchor survives restart),
§9.3 no-progress detection on OBSERVED signals only, and the §6 escalation
package — which must be redacted before it can reach a transcript.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import host_watchdog as hw  # noqa: E402
import check_secrets as cs  # noqa: E402
import check_app_db_secrets as appdb  # noqa: E402

REPO_ROOT = TOOLS.parent

# built by concatenation — never a literal token shape in this source file
TOKEN = "sk-ant-" + "fake0123456789" + "abcdef0123"


def attempt(n=1, kind="initial", phase="implementation", outcome="failed",
            checks=("t1",), digest="d1", error="boom", **over):
    a = {"n": n, "kind": kind, "phase": phase, "started": 100.0, "ended": 110.0,
         "outcome": outcome, "failing_checks": list(checks),
         "changed_files_digest": digest, "error": error,
         "log": f"attempt-{n} log tail"}
    a.update(over)
    return a


def state(**over):
    st = {
        "task_id": "T-007",
        "brief": {"objective": "fix the thing", "acceptance": ["pytest -q"]},
        "decision": {"route": "delegate", "reasons": ["cheaper all-in"]},
        "session": {"started": 100.0, "wall_clock_limit": 300, "status": "running"},
        "attempts": [attempt()],
        "budget": {"call_limit": 4, "used_calls": 1, "cash_cap": 1.0, "spent": 0.02},
        "repair_allowance": 1,
        "diff_or_pr_url": "https://example.invalid/pull/1",
        "stop_triggers": [],
        "now": 150.0,
    }
    st.update(over)
    return st


def scanner_hits(text: str) -> list:
    return [name for name, pat in cs.PATTERNS + appdb.PATTERNS if pat.search(text)]


class RepairAllowance(unittest.TestCase):
    """§9.1 — one same-profile corrective dispatch per original task, total."""

    def test_first_failure_allows_single_repair(self):
        v = hw.evaluate(state())
        self.assertEqual(v["action"], hw.ACTION_REPAIR)
        self.assertIn("corrective dispatch #1 authorized", v["reasons"][0])

    def test_second_failure_needs_human_one_repair_total(self):
        st = state(attempts=[
            attempt(1, checks=("t1",), digest="d1", error="e1"),
            attempt(2, kind="repair", checks=("t2",), digest="d2", error="e2"),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("repair-allowance-exhausted", v["reasons"][0])
        self.assertIn("in total", v["reasons"][0])

    def test_ci_phase_repair_shares_the_same_allowance(self):
        # the resolved repair-cap conflict: a CI-phase correction is NOT a
        # second budget (host-hil-policy §4 step 7 / §9.1)
        st = state(attempts=[
            attempt(1, checks=("t1",), digest="d1", error="e1"),
            attempt(2, kind="repair", phase="ci", checks=("t2",), digest="d2", error="e2"),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("repair-allowance-exhausted", v["reasons"][0])

    def test_review_feedback_correction_shares_allowance(self):
        st = state(attempts=[
            attempt(1, kind="repair", phase="review", outcome="succeeded",
                    checks=(), error=""),
            attempt(2, kind="initial", checks=("t9",), digest="d9", error="e9"),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)

    def test_repair_then_success_continues(self):
        st = state(attempts=[
            attempt(1, checks=("t1",), digest="d1", error="e1"),
            attempt(2, kind="repair", outcome="succeeded", checks=(), digest="d2",
                    error=""),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_CONTINUE)

    def test_counters_survive_restart(self):
        # a restarted session resumes its persisted attempts and anchor:
        # the repair already used still counts, and time is not renewed
        st = state(now=150.0, attempts=[
            attempt(1, checks=("t1",), digest="d1", error="e1"),
            attempt(2, kind="repair", checks=("t2",), digest="d2", error="e2"),
        ], session={"started": 100.0, "wall_clock_limit": 300,
                    "status": "running", "restarted": True})
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        v2 = hw.evaluate(state(now=450.0))  # anchor 100 + limit 300 expires at 400
        self.assertEqual(v2["action"], hw.ACTION_NEEDS_HUMAN)  # old anchor times out
        self.assertIn("wall-clock-timeout", v2["reasons"][0])


class NoProgress(unittest.TestCase):
    """§9.3 — observed lack of progress escalates instead of looping."""

    def test_same_failing_checks_escalate(self):
        st = state(attempts=[
            attempt(1, checks=("t1",), digest="d1", error="e1"),
            attempt(2, kind="repair", checks=("t1",), digest="d2", error="e2"),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("no-progress", v["reasons"][0])
        self.assertIn("same failing checks", v["reasons"][0])

    def test_unchanged_files_escalate(self):
        st = state(attempts=[
            attempt(1, checks=("t1",), digest="d1", error="e1"),
            attempt(2, kind="repair", checks=("t2",), digest="d1", error="e2"),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("no meaningful file changes", v["reasons"][0])

    def test_repeated_identical_error_escalates(self):
        st = state(attempts=[
            attempt(1, checks=("t1",), digest="d1", error="same boom"),
            attempt(2, kind="repair", checks=("t2",), digest="d2", error="same boom"),
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("repeated identical error", v["reasons"][0])

    def test_missing_evidence_is_not_claimed_as_no_progress(self):
        # absent digests are UNOBSERVED, not "no changes": the verdict must
        # fall through to the repair allowance, never invent a §9.3 signal
        st = state(attempts=[
            {"n": 1, "kind": "initial", "outcome": "failed",
             "failing_checks": ["t1"], "error": "e1"},
            {"n": 2, "kind": "repair", "outcome": "failed",
             "failing_checks": ["t2"], "error": "e2"},
        ])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("repair-allowance-exhausted", v["reasons"][0])
        self.assertNotIn("no-progress", v["reasons"][0])


class Timeouts(unittest.TestCase):
    """§9.5 — wall-clock limit on the persisted anchor; equality expires."""

    def test_equality_expires(self):
        v = hw.evaluate(state(now=400.0))  # started 100, limit 300
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("wall-clock-timeout", v["reasons"][0])

    def test_just_under_still_repairs(self):
        v = hw.evaluate(state(now=399.0))
        self.assertEqual(v["action"], hw.ACTION_REPAIR)

    def test_unresponsive_agent_is_killed_and_escalated(self):
        st = state(session={"started": 100.0, "wall_clock_limit": 300,
                            "status": "unresponsive"})
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("agent-unresponsive", v["reasons"][0])


class Budgets(unittest.TestCase):
    """§9.2 — hard ceilings block even with a free repair allowance."""

    def test_call_limit_exhausted(self):
        st = state(budget={"call_limit": 4, "used_calls": 4,
                           "cash_cap": 1.0, "spent": 0.02})
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("call-limit-exhausted", v["reasons"][0])

    def test_cash_cap_exhausted(self):
        st = state(budget={"call_limit": 4, "used_calls": 1,
                           "cash_cap": 1.0, "spent": 1.0})
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("budget-exhausted", v["reasons"][0])

    def test_stop_triggers_escalate(self):
        st = state(stop_triggers=["high-risk-signal: production config touched"])
        v = hw.evaluate(st)
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIn("stop-trigger", v["reasons"][0])

    def test_fresh_session_proceeds_initial_dispatch(self):
        v = hw.evaluate(state(attempts=[]))
        self.assertEqual(v["action"], hw.ACTION_CONTINUE)


class EscalationPackage(unittest.TestCase):
    """§6 — the package a human must receive, redacted before emission."""

    def _verdict(self):
        st = state(brief={"objective": "fix", "key": TOKEN},
                   attempts=[
                       attempt(1, checks=("t1",), digest="d1", error="e1", log=TOKEN),
                       attempt(2, kind="repair", checks=("t2",), digest="d2", error="e2"),
                   ])
        return hw.evaluate(st)

    def test_package_fields_complete(self):
        v = self._verdict()
        self.assertEqual(v["action"], hw.ACTION_NEEDS_HUMAN)
        pkg = v["escalation"]
        self.assertIsNotNone(pkg)
        self.assertEqual(pkg["original_brief"]["objective"], "fix")
        self.assertEqual(pkg["smart_router_decision"]["route"], "delegate")
        self.assertEqual(len(pkg["attempt_history"]), 2)
        self.assertIn("log", pkg["attempt_history"][0])
        self.assertEqual(pkg["diff_or_pr_url"], "https://example.invalid/pull/1")
        self.assertEqual(pkg["action_options"],
                         ["Approve", "Guide", "Take over", "Abort"])
        self.assertTrue(pkg["reasons"])

    def test_package_is_redacted(self):
        v = self._verdict()
        dumped = json.dumps(v)
        self.assertFalse(TOKEN in dumped, "credential-shaped value leaked")
        self.assertIn("[REDACTED:", dumped)
        self.assertEqual(scanner_hits(dumped), [])

    def test_markdown_rendering_is_redacted(self):
        v = self._verdict()
        v, _ = hw.redaction.redact_obj(v)
        md = hw.render_markdown(v)
        self.assertIn("Escalation package", md)
        self.assertIn("Approve", md)
        self.assertFalse(TOKEN in md, "credential-shaped value leaked")
        self.assertEqual(scanner_hits(md), [])


class CLI(unittest.TestCase):
    def _run(self, doc_text: str, extra=()):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(doc_text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "tools/host_watchdog.py", "--state", str(p)] + list(extra),
                cwd=REPO_ROOT, capture_output=True, timeout=60)

    def test_exit_zero_on_repair(self):
        r = self._run(json.dumps(state()))
        self.assertEqual(r.returncode, 0)
        verdict = json.loads(r.stdout)
        self.assertEqual(verdict["action"], hw.ACTION_REPAIR)

    def test_exit_one_on_needs_human(self):
        r = self._run(json.dumps(state(now=1000.0)))
        self.assertEqual(r.returncode, 1)
        verdict = json.loads(r.stdout)
        self.assertEqual(verdict["action"], hw.ACTION_NEEDS_HUMAN)
        self.assertIsNotNone(verdict["escalation"])

    def test_exit_two_on_malformed_state(self):
        r = self._run("not json at all")
        self.assertEqual(r.returncode, 2)
        self.assertIn(b"FAIL-CLOSED", r.stderr)

    def test_exit_two_on_incomplete_state(self):
        r = self._run(json.dumps({"task_id": "T-1"}))
        self.assertEqual(r.returncode, 2)

    def test_markdown_format(self):
        r = self._run(json.dumps(state(now=1000.0)), extra=("--format", "markdown"))
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"Escalation package", r.stdout)
        self.assertEqual(scanner_hits(r.stdout.decode("utf-8")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
