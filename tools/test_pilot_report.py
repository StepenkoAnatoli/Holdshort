#!/usr/bin/env python3
"""Tests for tools/pilot_report.py — no network, synthetic ledger fixtures only."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pr", TOOLS / "pilot_report.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

PRICES = json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8"))


def entry(tid, pid, dec, in_t, out_t, cost):
    return {"ts": 0.0, "task_id": tid, "attempt_no": 1, "profile_id": pid,
            "input_tokens": in_t, "output_tokens": out_t, "cost_usd": cost,
            "decision": dec, "reason": "test"}


class PilotReport(unittest.TestCase):

    def test_clean_ledger_aggregates(self):
        # cloud-C: $0.10/MTok in, $0.50/MTok out → 10_000 in / 1_000 out = $0.0015
        entries = [entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015),
                   entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "intact")
        self.assertEqual(r["pilot"]["dispatches"], 2)
        self.assertAlmostEqual(r["pilot"]["total_spend_usd"], 0.003, places=6)
        self.assertAlmostEqual(r["per_profile"]["cloud-C"]["spend_usd"], 0.003, places=6)
        self.assertEqual(r["problems"], [])

    def test_cost_mismatch_is_gapped(self):
        # recomputed = $0.0015; ledger claims $0.0020 → must flag
        entries = [entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.002)]
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("cost mismatch" in p for p in r["problems"]))

    def test_usage_unknown_dispatch_is_gapped(self):
        # a reservation charged for unreadable usage matches the rates but is not a
        # measurement: it is counted, and the ledger never reads as intact
        charged = dict(entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015),
                       usage_unknown=True)
        r = pr.build_report(PRICES, [charged])
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("usage unknown" in p for p in r["problems"]))
        self.assertAlmostEqual(r["pilot"]["total_spend_usd"], 0.0015, places=6)
        for flag in (None, 1, "true", "false"):  # anything but false is not a measurement
            r = pr.build_report(PRICES, [dict(charged, usage_unknown=flag)])
            self.assertEqual(r["accounting_status"], "GAPS_FOUND", repr(flag))
        for measured in (dict(charged, usage_unknown=False),
                         entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)):
            self.assertEqual(pr.build_report(PRICES, [measured])["accounting_status"], "intact")

    def test_attempt_cap_violation_detected(self):
        # 5 dispatches on one task > cap 4
        entries = [entry("T1", "cloud-C", "dispatched", 10, 10, 0.0000012)] * 5
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("attempt cap" in p for p in r["problems"]))

    def test_pilot_cap_violation_detected(self):
        # cloud-S 2.00 in / 10.00 out; 1_000_000 in + 10_000 out = $2.10 each
        # 10 dispatches on 10 distinct tasks = $21 > $20 pilot cap
        entries = [entry(f"P{i}", "cloud-S", "dispatched", 1_000_000, 10_000, 2.10)
                   for i in range(10)]
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("above cap" in p for p in r["problems"]))

    def test_unpriced_profile_dispatch_flagged(self):
        entries = [entry("T1", "cloud-XYZ", "dispatched", 100, 100, 0.0)]
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("unpriced profile" in p for p in r["problems"]))

    def test_repair_overuse_flagged(self):
        # 3 same-profile dispatches = 2 repairs credited > allowance 1
        entries = [entry("T1", "cloud-C", "dispatched", 10, 10, 1.2e-6)] * 3
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("repairs credited" in p for p in r["problems"]))

    def test_blocked_outcomes_recorded(self):
        entries = [entry("T1", "cloud-C", "blocked-cost-cap", 0, 0, 0.0),
                   entry("T2", "cloud-C", "blocked-gate4", 0, 0, 0.0)]
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "intact")
        outcomes = {t["task_id"]: t["outcome"] for t in r["per_task"]}
        self.assertEqual(outcomes["T1"], "blocked:cap")
        self.assertEqual(outcomes["T2"], "blocked:gate")

    def test_decision_neutrality_note_present(self):
        entries = [entry("T1", "cloud-C", "dispatched", 10, 10, 1.2e-6)]
        r = pr.build_report(PRICES, entries)
        self.assertIn("NOT made here", r["_note"])

    def test_empty_ledger_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            rc = pr.main(["--ledger", str(p)])
            self.assertEqual(rc, 2)

    def test_corrupt_line_exits_with_message(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.jsonl"
            p.write_text('{"task_id": "x", "decision"\n', encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                pr.main(["--ledger", str(p)])
            self.assertIn("corrupt ledger line 1", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
