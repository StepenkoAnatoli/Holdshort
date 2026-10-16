#!/usr/bin/env python3
"""Tests for tools/task_crosscheck.py — persisted state vs. ledger reconciliation.

Covers the item-16 guarantee: a mid-restart crash that loses a state-store save
must surface as an explicit finding at close, never as silent under-report.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import task_crosscheck as tc  # noqa: E402

PRICES = json.loads((REPO / "tools" / "prices-2.json").read_text(encoding="utf-8"))


def ledger_entry(tid, pid, dec, in_t, out_t, cost):
    return {"ts": 0.0, "task_id": tid, "attempt_no": 1, "profile_id": pid,
            "input_tokens": in_t, "output_tokens": out_t, "cost_usd": cost,
            "decision": dec, "reason": "test"}


def state_doc(tid, attempts, spent):
    return {"task_id": tid, "attempts": attempts, "spent": spent,
            "started": 0.0, "repairs": 0, "last_profile": "cloud-C"}


class Crosscheck(unittest.TestCase):

    def authority_dispatcher(self, root):
        import live_dispatcher as ld
        def send(profile, request):
            return 1000, 100
        send.max_tokens = 4096
        send.count_tokens = lambda profile, request: 1000
        return ld.LiveDispatcher(PRICES, root / "ledger.jsonl", dispatch_fn=send, confirm_egress=True)

    def test_authority_without_optional_task_store_is_consistent_and_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dispatcher = self.authority_dispatcher(root)
            self.assertEqual(dispatcher.attempt("A", "cloud-C", "x", work_bound=.01, review_bound=0).decision, "dispatched")
            before = dispatcher.budget.path.read_bytes()
            rows = [json.loads(line) for line in dispatcher.ledger_path.read_text().splitlines()]
            result = tc.check(root / "absent-tasks", PRICES, rows, ledger_path=dispatcher.ledger_path)
            self.assertTrue(result["consistent"], result["findings"])
            self.assertEqual(result["source"], "sqlite-authority")
            self.assertEqual(dispatcher.budget.path.read_bytes(), before)
            self.assertFalse((root / "absent-tasks").exists())

    def test_authority_journal_lag_is_visible_even_without_task_mirrors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dispatcher = self.authority_dispatcher(root)
            mirror = dispatcher.budget._mirror
            def lag(doc):
                if doc["events"] and doc["events"][-1]["decision"] == "dispatched":
                    raise OSError("synthetic mirror failure")
                return mirror(doc)
            dispatcher.budget._mirror = lag
            dispatcher.attempt("A", "cloud-C", "x", work_bound=.01, review_bound=0)
            rows = [json.loads(line) for line in dispatcher.ledger_path.read_text().splitlines()]
            result = tc.check(root / "absent", PRICES, rows, ledger_path=dispatcher.ledger_path)
            self.assertFalse(result["consistent"])
            self.assertIn("mirror-lag", {row["kind"] for row in result["findings"]})

    def test_authority_checksum_failure_is_not_reported_as_consistent(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dispatcher = self.authority_dispatcher(root)
            dispatcher.attempt("A", "cloud-C", "x", work_bound=.01, review_bound=0)
            with closing(sqlite3.connect(dispatcher.budget.path)) as connection:
                with connection:
                    connection.execute("UPDATE authority SET payload = '{}' WHERE id=1")
            result = tc.check(root / "absent", PRICES, [], ledger_path=dispatcher.ledger_path)
            self.assertFalse(result["consistent"])
            self.assertEqual(result["findings"][0]["kind"], "authority-unreadable")

    def test_consistent_state_and_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "state"
            sd.mkdir()
            (sd / "T1.json").write_text(json.dumps(state_doc("T1", 2, 0.003)), encoding="utf-8")
            entries = [ledger_entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015),
                       ledger_entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]
            r = tc.check(sd, PRICES, entries)
            self.assertTrue(r["consistent"], r["findings"])
            self.assertEqual(r["findings"], [])

    def test_state_below_ledger_spend_flagged_as_crash_underreport(self):
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "state"
            sd.mkdir()
            # ledger saw 2 dispatches ($0.003); state only persisted 1 ($0.0015)
            (sd / "T1.json").write_text(json.dumps(state_doc("T1", 1, 0.0015)), encoding="utf-8")
            entries = [ledger_entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015),
                       ledger_entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]
            r = tc.check(sd, PRICES, entries)
            self.assertFalse(r["consistent"])
            kinds = {f["kind"] for f in r["findings"]}
            self.assertIn("spend-under-report", kinds)
            self.assertIn("attempts-under-report", kinds)

    def test_legacy_malformed_state_and_ledger_never_report_consistent(self):
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td)
            rows = [ledger_entry("A", "cloud-C", "dispatched", 10000, 1000, .0015)]
            for change in ({"spent": float("nan")}, {"task_id": []}, {"attempts": 1.5}):
                with self.subTest(change=change):
                    state = state_doc("A", 1, .0015)
                    state.update(change)
                    (sd / "A.json").write_text(json.dumps(state), encoding="utf-8")
                    self.assertFalse(tc.check(sd, PRICES, rows)["consistent"])
            (sd / "A.json").unlink()
            rows[0]["cost_usd"] = float("nan")
            result = tc.check(sd, PRICES, rows)
            self.assertFalse(result["consistent"])
            self.assertIn("accounting-gaps", {f["kind"] for f in result["findings"]})

    def test_missing_state_for_dispatched_task_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "state"
            sd.mkdir()
            entries = [ledger_entry("T9", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]
            r = tc.check(sd, PRICES, entries)
            self.assertFalse(r["consistent"])
            self.assertEqual(r["findings"][0]["kind"], "state-missing")

    def test_state_only_task_is_not_a_finding(self):
        # a blocked-only task exists in state but never reached the ledger with spend:
        # ledger records the block (attempts 0, spent 0) — legal, must NOT flag.
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "state"
            sd.mkdir()
            (sd / "T2.json").write_text(json.dumps(state_doc("T2", 0, 0.0)), encoding="utf-8")
            entries = [ledger_entry("T2", "cloud-C", "blocked-cost-cap", 0, 0, 0.0)]
            r = tc.check(sd, PRICES, entries)
            self.assertTrue(r["consistent"], r["findings"])

    def test_state_above_ledger_is_legal_no_finding(self):
        # blocked attempts live in state but produce no ledger cost line:
        with tempfile.TemporaryDirectory() as td:
            sd = Path(td) / "state"
            sd.mkdir()
            (sd / "T3.json").write_text(json.dumps(state_doc("T3", 3, 0.003)), encoding="utf-8")
            entries = [ledger_entry("T3", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]
            r = tc.check(sd, PRICES, entries)
            self.assertTrue(r["consistent"], r["findings"])

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sd = tmp / "state"
            sd.mkdir()
            led = tmp / "led.jsonl"
            led.write_text(json.dumps(ledger_entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)) + "\n",
                           encoding="utf-8")
            prices = str(REPO / "tools" / "prices-2.json")
            # finding -> exit 1
            self.assertEqual(tc.main(["--state-dir", str(sd), "--ledger", str(led), "--prices", prices]), 1)
            # consistent -> exit 0
            (sd / "T1.json").write_text(json.dumps(state_doc("T1", 1, 0.0015)), encoding="utf-8")
            self.assertEqual(tc.main(["--state-dir", str(sd), "--ledger", str(led), "--prices", prices]), 0)
            # missing ledger -> exit 2
            self.assertEqual(tc.main(["--state-dir", str(sd), "--ledger", str(tmp / "nope.jsonl"),
                                      "--prices", prices]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
