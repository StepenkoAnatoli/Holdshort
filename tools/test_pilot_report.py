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

    def test_invalid_usage_and_cost_never_report_intact(self):
        for change in ({"cost_usd": float('nan')}, {"cost_usd": float('inf')},
                       {"cost_usd": -1}, {"cost_usd": True}, {"input_tokens": 10000.9},
                       {"input_tokens": "10000"}, {"output_tokens": False},
                       {"task_id": []}, {"decision": {}}, {"reservation_id": []}):
            with self.subTest(change=change):
                e = entry("T1", "cloud-C", "dispatched", 10000, 1000, .0015)
                e.update(change)
                r = pr.build_report(PRICES, [e])
                self.assertEqual(r["accounting_status"], "GAPS_FOUND")
                self.assertFalse(r["pilot"]["total_spend_complete"])
                self.assertEqual(r["pilot"]["invalid_ledger_lines"], [1])
                json.dumps(r, allow_nan=False)

    def test_invalid_supersession_cannot_hide_pending_reservation(self):
        pending = entry("T1", "cloud-C", "dispatch-reserved", None, None, None)
        pending.update(reservation_id="synthetic", reserved_cost_usd=.1, known_cost_usd=0)
        bad = entry("T1", "cloud-C", "dispatched", 10000, 1000, float('nan'))
        bad["reservation_id"] = "synthetic"
        r = pr.build_report(PRICES, [pending, bad])
        self.assertFalse(r["pilot"]["total_spend_complete"])
        self.assertEqual(r["pilot"]["unknown_usage_dispatches"], 1)
        self.assertEqual(r["pilot"]["reserved_usd"], .1)

    def test_incomplete_reconciliation_preserves_uncertain_evidence(self):
        pending = entry("T1", "cloud-C", "dispatch-reserved", None, None, None)
        pending.update(reservation_id="synthetic", reserved_cost_usd=.1, known_cost_usd=0)
        uncertain = dict(pending, decision="dispatch-error")
        receipt = entry("T1", "cloud-C", "dispatch-reconciled", 10000, 1000, .0015)
        receipt["reservation_id"] = "synthetic"
        for prefix in ([pending], [pending, uncertain]):
            for field in ("input_tokens", "output_tokens", "cost_usd"):
                with self.subTest(prefix_length=len(prefix), field=field):
                    rows = prefix + [dict(receipt, **{field: None})]
                    report = pr.build_report(PRICES, rows)
                    self.assertEqual(report["accounting_status"], "GAPS_FOUND")
                    self.assertFalse(report["pilot"]["total_spend_complete"])
                    self.assertEqual(report["pilot"]["invalid_ledger_lines"], [len(rows)])
                    self.assertEqual(report["pilot"]["unknown_usage_dispatches"], 1)
                    self.assertEqual(report["pilot"]["reserved_usd"], .1)
                    self.assertEqual(list(pr.effective_entries(rows)), [(len(prefix), prefix[-1])])
                    json.dumps(report, allow_nan=False)

    def test_complete_receipt_reconciles_reserved_or_uncertain_dispatch(self):
        pending = entry("T1", "cloud-C", "dispatch-reserved", None, None, None)
        pending.update(reservation_id="synthetic", reserved_cost_usd=.1, known_cost_usd=0)
        uncertain = dict(pending, decision="dispatch-error", known_cost_usd=.001)
        receipt = entry("T1", "cloud-C", "dispatch-reconciled", 10000, 1000, .0015)
        receipt["reservation_id"] = "synthetic"
        for prefix in ([pending], [pending, uncertain]):
            with self.subTest(prefix_length=len(prefix)):
                rows = prefix + [receipt]
                report = pr.build_report(PRICES, rows)
                self.assertEqual(report["accounting_status"], "intact")
                self.assertTrue(report["pilot"]["total_spend_complete"])
                self.assertEqual(report["pilot"]["dispatches"], 1)
                self.assertEqual(report["pilot"]["total_spend_usd"], .0015)
                self.assertEqual(report["pilot"]["reserved_usd"], 0)
                self.assertEqual(list(pr.effective_entries(rows)), [(len(rows), receipt)])

    def test_reconciliation_preserves_known_charge_floor_and_identity(self):
        pending = entry("T1", "cloud-C", "dispatch-reserved", None, None, None)
        pending.update(reservation_id="synthetic", reserved_cost_usd=.1, known_cost_usd=.001)
        uncertain = dict(pending, decision="dispatch-error", known_cost_usd=0)
        receipt = entry("T1", "cloud-C", "dispatch-reconciled", 1000, 100, .00015)
        receipt["reservation_id"] = "synthetic"
        for prefix in ([pending], [pending, uncertain]):
            for replacement in (receipt, dict(receipt, task_id="T2"),
                                dict(receipt, profile_id="cloud-S"), dict(receipt, purpose="verification")):
                with self.subTest(prefix_length=len(prefix), replacement=replacement):
                    rows = prefix + [replacement]
                    self.assertIn(len(rows), pr.ledger_problems(rows))
                    self.assertEqual(pr.build_report(PRICES, rows)["accounting_status"], "GAPS_FOUND")

    def test_nonobject_record_is_reported_without_crashing(self):
        r = pr.build_report(PRICES, [None, []])
        self.assertEqual(r["pilot"]["invalid_ledger_lines"], [1, 2])
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")

    def test_invalid_caps_are_rejected(self):
        import copy
        for field, value in (("max_cost_per_task_usd", float('nan')), ("max_attempts_per_task", 1.5)):
            prices = copy.deepcopy(PRICES); prices["pilot_caps"][field] = value
            with self.assertRaises(ValueError):
                pr.build_report(prices, [])

    def test_reservation_identity_and_settlement_order_are_checked(self):
        pending = entry("T1", "cloud-C", "dispatch-reserved", None, None, None)
        pending.update(reservation_id="synthetic", reserved_cost_usd=.1, known_cost_usd=0)
        settled = entry("T1", "cloud-C", "dispatched", 10000, 1000, .0015)
        settled["reservation_id"] = "synthetic"
        self.assertEqual(pr.build_report(PRICES,[pending,settled])["accounting_status"], "intact")
        for rows in ([settled], [pending,dict(settled,task_id="T2")], [pending,settled,settled]):
            with self.subTest(rows=rows):
                self.assertEqual(pr.build_report(PRICES,rows)["accounting_status"], "GAPS_FOUND")

    def test_nonphysical_usage_and_false_settled_reservation_are_rejected(self):
        for decision in ("blocked-gate4", "verification-complete", "dispatch-cancelled", "dispatch-reserved"):
            row = entry("T1", "cloud-C", decision, 10000, 1000, .0015)
            self.assertEqual(pr.build_report(PRICES,[row])["accounting_status"], "GAPS_FOUND")

    def test_verification_cannot_complete_unknown_usage(self):
        pending = entry("T1", "cloud-C", "dispatch-reserved", None, None, None)
        verified = entry("T1", "cloud-C", "verification-complete",0,0,0)
        r = pr.build_report(PRICES,[pending,verified])
        self.assertEqual(r["per_task"][0]["outcome"], "usage-unknown")
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")

    def test_cost_mismatch_is_gapped(self):
        # recomputed = $0.0015; ledger claims $0.0020 → must flag
        entries = [entry("T1", "cloud-C", "dispatched", 10_000, 1_000, 0.002)]
        r = pr.build_report(PRICES, entries)
        self.assertEqual(r["accounting_status"], "GAPS_FOUND")
        self.assertTrue(any("cost mismatch" in p for p in r["problems"]))

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
