#!/usr/bin/env python3
"""Tests for tools/host_watchdog.py — HITL timeout / repair-cap / no-progress enforcement.

Invariants (each a real loop-prevention failure mode, HITL §6/§9 after the 2026-10-12
tightening to ONE repair total per original task, plan R01/R02/R03):
  H1. wall-clock timeout kills the session and escalates (exit 2 + package)
  H2. success exits 0 and is recorded
  H3. first failure exits 1 (repair consumed); second DISTINCT failure exits 2 with the
      repair-cap reason — there is no second cycle, CI or otherwise, without a fresh task
  H4. no-progress escalates even with the allowance free: same failing tests, repeated
      identical error, identical diff hash
  H5. counters survive restart: rerunning with the same --state never resets repairs_used
  H6. the escalation package is the HITL §6 package (brief, decision, history, diff/PR,
      action options)
  H7. pre-run ceilings and safety signals escalate without running the command
  H8. pure policy units: equality expires the deadline; allowance boundary; safety-first ordering

Hermetic and fast: sleeps are sub-second; no network; state files live in temp dirs.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "host_watchdog.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wd = _load("hdw", TOOL)
SLEEP5 = [sys.executable, "-c", "import time; time.sleep(5)"]


def run_watchdog(state: Path, task: str, *extra: str, cmd: list[str] | None = None,
                 cwd: Path | None = None, timeout: float = 30.0) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(TOOL), "--task-id", task, "--state", str(state), *extra]
    if cmd is not None:
        argv += ["--", *cmd]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          cwd=cwd or REPO)


class Watchdog(unittest.TestCase):

    # H8 (pure, fastest first) ------------------------------------------------
    def test_h8_timeout_equality_expires(self):
        self.assertTrue(wd.timed_out(started=0.0, now=10.0, limit_s=10.0))
        self.assertTrue(wd.timed_out(started=0.0, now=10.1, limit_s=10.0))
        self.assertFalse(wd.timed_out(started=0.0, now=9.9, limit_s=10.0))

    def test_h8_repair_allowance_boundary(self):
        self.assertTrue(wd.repair_allowed(repairs_used=0, allowance=1))
        self.assertFalse(wd.repair_allowed(repairs_used=1, allowance=1))

    def test_h8_safety_beats_free_repair(self):
        verdict, reason = wd.decide(repairs_used=0, allowance=1, prev=None,
                                    curr={"failing_tests": [], "diff_hash": "x", "error": "new"},
                                    calls_used=0, calls_limit=None, cash_spent=0.0,
                                    cash_cap=None, high_risk="privilege escalation signal")
        self.assertEqual(verdict, "needs-human")
        self.assertIn("high-risk", reason)

    def test_h8_no_progress_beats_free_repair(self):
        prev = {"failing_tests": ["t1"], "diff_hash": "aa", "error": "boom"}
        curr = {"failing_tests": ["t1"], "diff_hash": "bb", "error": "other"}
        verdict, reason = wd.decide(repairs_used=0, allowance=1, prev=prev, curr=curr,
                                    calls_used=0, calls_limit=None, cash_spent=0.0, cash_cap=None)
        self.assertEqual(verdict, "needs-human")
        self.assertIn("no progress", reason)

    # H2 ----------------------------------------------------------------------
    def test_h2_success_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            r = run_watchdog(tdp / "s.json", "h2", "--timeout", "10",
                             cmd=[sys.executable, "-c", "print('ok')"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            st = json.loads((tdp / "s.json").read_text())
            self.assertEqual(st["attempts"], 1)
            self.assertEqual(st["repairs_used"], 0)

    # H1 ----------------------------------------------------------------------
    def test_h1_timeout_kills_and_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            esc = tdp / "esc.json"
            r = run_watchdog(tdp / "s.json", "h1", "--timeout", "0.3",
                             "--escalation-out", str(esc), cmd=SLEEP5, timeout=30.0)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("needs-human", r.stderr)
            self.assertIn("timeout", r.stderr.lower())
            pkg = json.loads(esc.read_text())
            self.assertEqual(pkg["status"], "needs-human")
            self.assertIn("timeout", pkg["reason"].lower())

    # H3 ----------------------------------------------------------------------
    def test_h3_one_repair_total_then_cap(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            st = tdp / "s.json"
            first = run_watchdog(st, "h3", "--timeout", "10", "--diff-hash", "aaa",
                                 "--error", "first boom",
                                 "--escalation-out", str(tdp / "e1.json"),
                                 cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            mid = json.loads(st.read_text())
            self.assertEqual(mid["repairs_used"], 1)
            second = run_watchdog(st, "h3", "--timeout", "10", "--diff-hash", "bbb",
                                  "--error", "second boom",
                                  "--escalation-out", str(tdp / "e2.json"),
                                  cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
            self.assertIn("repair allowance exhausted", second.stderr)
            self.assertIn("R01/R02/R03", second.stderr)
            pkg = json.loads((tdp / "e2.json").read_text())
            self.assertIn("repair allowance exhausted", pkg["reason"])

    # H4 ----------------------------------------------------------------------
    def test_h4_same_failing_tests_escalate(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            st = tdp / "s.json"
            run_watchdog(st, "h4a", "--timeout", "10", "--failing-tests", "t1,t2",
                         "--diff-hash", "aa", "--error", "e1",
                         cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            r = run_watchdog(st, "h4a", "--timeout", "10", "--failing-tests", "t1,t2",
                             "--diff-hash", "zz", "--error", "e2",
                             "--escalation-out", str(tdp / "esc.json"),
                             cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("same failing tests", r.stderr)

    def test_h4_repeated_error_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            st = tdp / "s.json"
            run_watchdog(st, "h4b", "--timeout", "10", "--diff-hash", "aa", "--error", "boom-x",
                         cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            r = run_watchdog(st, "h4b", "--timeout", "10", "--diff-hash", "bb", "--error", "boom-x",
                             "--escalation-out", str(tdp / "esc.json"),
                             cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("repeated identical error", r.stderr)

    def test_h4_identical_diff_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            st = tdp / "s.json"
            run_watchdog(st, "h4c", "--timeout", "10", "--diff-hash", "same", "--error", "e1",
                         cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            r = run_watchdog(st, "h4c", "--timeout", "10", "--diff-hash", "same", "--error", "e2",
                             "--escalation-out", str(tdp / "esc.json"),
                             cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(r.returncode, 2)
            self.assertIn("no meaningful file changes", r.stderr)

    # H5 ----------------------------------------------------------------------
    def test_h5_counters_survive_restart(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            st = tdp / "s.json"
            run_watchdog(st, "h5", "--timeout", "10", "--diff-hash", "a", "--error", "e1",
                         cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            before = json.loads(st.read_text())
            # a fresh process with the same state file sees the consumed repair
            r = run_watchdog(st, "h5", "--timeout", "10", "--diff-hash", "b", "--error", "e2",
                             "--escalation-out", str(tdp / "esc.json"),
                             cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            after = json.loads(st.read_text())
            self.assertEqual(r.returncode, 2)
            self.assertEqual(before["repairs_used"], 1)
            self.assertEqual(after["repairs_used"], 1, "restart must never grant a fresh allowance")
            self.assertEqual(after["attempts"], 2)

    # H6 ----------------------------------------------------------------------
    def test_h6_escalation_package_has_hitl_fields(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            brief = tdp / "brief.json"
            brief.write_text(json.dumps({"objective": "fix t", "attempts": 1}))
            decision = tdp / "decision.json"
            decision.write_text(json.dumps({"Route": "delegate", "HumanGate": "none"}))
            st = tdp / "s.json"
            run_watchdog(st, "h6", "--timeout", "10", "--diff-hash", "a", "--error", "e1",
                         cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            esc = tdp / "pkg.json"
            r = run_watchdog(st, "h6", "--timeout", "10", "--brief", str(brief),
                             "--decision", str(decision), "--diff-hash", "b", "--error", "e2",
                             "--diff-ref", "abc123", "--pr-url", "https://example.test/pr/1",
                             "--escalation-out", str(esc),
                             cmd=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(r.returncode, 2)
            pkg = json.loads(esc.read_text())
            self.assertEqual(pkg["status"], "needs-human")
            self.assertEqual(pkg["task_id"], "h6")
            self.assertEqual(pkg["brief"]["objective"], "fix t")
            self.assertEqual(pkg["decision"]["HumanGate"], "none")
            self.assertTrue(pkg["attempt_history"], "complete attempt history required")
            self.assertEqual(pkg["diff_ref"], "abc123")
            self.assertIn("/pr/1", pkg["pr_url"])
            for action in ("Approve", "Guide", "Take over", "Abort"):
                self.assertIn(action, pkg["actions"])

    # H7 ----------------------------------------------------------------------
    def test_h7_ceilings_and_safety_escalate_without_running(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            marker = tdp / "ran.txt"
            # calls ceiling: the payload would create the marker if it ran
            r = run_watchdog(tdp / "s1.json", "h7a", "--timeout", "10",
                             "--calls-used", "4", "--calls-limit", "4",
                             "--escalation-out", str(tdp / "e1.json"),
                             cmd=[sys.executable, "-c",
                                  f"open({str(marker)!r}, 'w').write('ran')"])
            self.assertEqual(r.returncode, 2)
            self.assertFalse(marker.exists(), "ceiling must block before dispatch")
            # high-risk signal likewise
            r2 = run_watchdog(tdp / "s2.json", "h7b", "--timeout", "10",
                              "--high-risk", "data deletion signal",
                              "--escalation-out", str(tdp / "e2.json"),
                              cmd=[sys.executable, "-c", "print('should not run')"])
            self.assertEqual(r2.returncode, 2)
            self.assertIn("high-risk", r2.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
