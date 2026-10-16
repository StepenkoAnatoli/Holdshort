#!/usr/bin/env python3
"""Tests for tools/pilot_report.py — no network, synthetic ledger fixtures only."""
from __future__ import annotations

import importlib.util
import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr

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

    def test_unsettled_return_cannot_be_appended_as_a_canonical_event(self):
        reserved = entry("A", "cloud-C", "dispatch-reserved", None, None, None)
        reserved.update(reservation_id="reservation", reserved_cost_usd=.01,
                        review_reserved_usd=.02, purpose="work", usage_status="unknown")
        returned = dict(reserved, decision="dispatch-unsettled", input_tokens=10000,
                        output_tokens=1000, cost_usd=.0015, settlement_status="unsettled")
        self.assertNotIn("dispatch-unsettled", pr.KNOWN_DECISIONS)
        self.assertTrue(any("return-only" in problem for problem in pr.entry_problems(returned)))
        report = pr.build_report(PRICES, [reserved, returned])
        self.assertEqual(report["accounting_status"], "GAPS_FOUND")
        self.assertFalse(report["pilot"]["total_spend_complete"])
        self.assertTrue(any("return-only" in problem for problem in report["problems"]))

    def _authority_fixture(self, directory):
        import live_dispatcher as ld
        ledger = Path(directory) / "ledger.jsonl"
        dispatcher = ld.LiveDispatcher(PRICES, ledger, now_fn=lambda: 1000)
        result = dispatcher.attempt("authority-task", "cloud-C", "synthetic", work_bound=.01,
                                    review_bound=.02, expected_in=10000, expected_out=1000)
        self.assertEqual(result.decision, "dispatched")
        return ledger

    def _report_cli(self, ledger):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = pr.main(["--ledger", str(ledger)])
        return status, json.loads(output.getvalue())

    def test_cli_reads_authority_without_optional_task_store_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            authority = ledger.with_name(ledger.name + ".budget.sqlite3")
            before = (ledger.read_bytes(), authority.read_bytes())
            status, report = self._report_cli(ledger)
            self.assertEqual(status, 0, report["problems"])
            self.assertEqual(report["accounting_source"], "sqlite-authority")
            self.assertEqual(report["pilot"]["total_spend_usd"], .0015)
            self.assertEqual(report["pilot"]["reserved_usd"], .02)
            self.assertEqual(report["pilot"]["authority_attempts"], 1)
            self.assertTrue(report["source_evidence"]["mirror_complete"])
            self.assertEqual(before, (ledger.read_bytes(), authority.read_bytes()))

    def test_cli_lagging_settlement_mirror_uses_committed_cost_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            authority = ledger.with_name(ledger.name + ".budget.sqlite3")
            ledger.write_text(ledger.read_text().splitlines()[0] + "\n", encoding="utf-8")
            before = (ledger.read_bytes(), authority.read_bytes())
            status, report = self._report_cli(ledger)
            self.assertEqual(status, 1)
            self.assertEqual(report["pilot"]["total_spend_usd"], .0015)
            self.assertEqual(report["pilot"]["reserved_usd"], .02)
            self.assertFalse(report["pilot"]["total_spend_complete"])
            self.assertTrue(any("lags" in problem for problem in report["problems"]))
            self.assertEqual(before, (ledger.read_bytes(), authority.read_bytes()))

    def test_cli_missing_or_empty_mirror_still_reports_authority(self):
        for missing in (True, False):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                ledger = self._authority_fixture(directory)
                authority = ledger.with_name(ledger.name + ".budget.sqlite3")
                if missing:
                    ledger.unlink()
                else:
                    ledger.write_text("", encoding="utf-8")
                before = authority.read_bytes()
                status, report = self._report_cli(ledger)
                self.assertEqual(status, 1)
                self.assertEqual(report["source_evidence"]["jsonl_events"], 0)
                self.assertEqual(report["pilot"]["total_spend_usd"], .0015)
                self.assertEqual(report["pilot"]["authority_attempts"], 1)
                self.assertEqual(authority.read_bytes(), before)
                self.assertEqual(ledger.exists(), not missing)

    def test_cli_corrupt_authority_never_certifies_complete_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            authority = ledger.with_name(ledger.name + ".budget.sqlite3")
            authority.write_bytes(b"synthetic corrupted authority")
            before = (ledger.read_bytes(), authority.read_bytes())
            status, report = self._report_cli(ledger)
            self.assertEqual(status, 1)
            self.assertEqual(report["accounting_source"], "sqlite-authority-unavailable")
            self.assertFalse(report["pilot"]["total_spend_complete"])
            self.assertFalse(report["pilot"]["reserved_complete"])
            self.assertTrue(report["pilot"]["halted"])
            self.assertEqual(report["per_task"][0]["outcome"], "accounting-unverified")
            self.assertEqual(before, (ledger.read_bytes(), authority.read_bytes()))

    def test_missing_mirror_preserves_authority_unknown_send_and_held_cash(self):
        import live_dispatcher as ld
        def unknown_send(*args):
            raise TimeoutError("synthetic timeout")
        unknown_send.max_tokens = 1
        unknown_send.count_tokens = lambda *args: 0
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            dispatcher = ld.LiveDispatcher(PRICES, ledger, now_fn=lambda: 1000,
                                           dispatch_fn=unknown_send, confirm_egress=True)
            dispatcher.attempt("unknown-task", "cloud-C", "synthetic", work_bound=.01, review_bound=.02)
            ledger.unlink()
            status, report = self._report_cli(ledger)
            self.assertEqual(status, 1)
            self.assertEqual(report["pilot"]["unknown_usage_dispatches"], 1)
            self.assertEqual(report["pilot"]["authority_attempts"], 1)
            self.assertEqual(report["pilot"]["reserved_usd"], .03)
            self.assertFalse(report["pilot"]["total_spend_complete"])
            self.assertEqual(report["per_task"][0]["outcome"], "usage-unknown")
            self.assertFalse(ledger.exists(), "reporting must not recover or replay the mirror")

    def test_cli_divergence_uses_authority_and_labels_legacy_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            rows = pr.load_jsonl(ledger)
            rows[-1]["cost_usd"] = 999
            ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            status, report = self._report_cli(ledger)
            self.assertEqual(status, 1)
            self.assertEqual(report["pilot"]["total_spend_usd"], .0015)
            self.assertTrue(any("diverges" in problem for problem in report["problems"]))
            legacy = Path(directory) / "legacy.jsonl"
            legacy.write_text(json.dumps(entry("legacy", "cloud-C", "dispatched", 10000, 1000, .0015)), encoding="utf-8")
            status, report = self._report_cli(legacy)
            self.assertEqual(status, 0)
            self.assertEqual(report["accounting_source"], "legacy-ledger")
            self.assertEqual(report["source_evidence"]["legacy_limit"], "no reservation authority checked")

    def test_refusals_preserve_unknown_and_verified_outcomes(self):
        unknown = entry("U", "cloud-C", "dispatch-error", None, None, None)
        unknown.update(reserved_cost_usd=.1, review_reserved_usd=.02)
        work = entry("V", "cloud-C", "dispatched", 10000, 1000, .0015)
        verified = entry("V", "cloud-C", "verification-complete", 0, 0, 0)
        rows = [unknown, entry("U", "cloud-C", "blocked-uncertain", 0, 0, 0),
                work, verified, entry("V", "cloud-C", "blocked-verified", 0, 0, 0)]
        report = pr.build_report(PRICES, rows)
        by_id = {r["task_id"]: r for r in report["per_task"]}
        self.assertEqual(by_id["U"]["outcome"], "usage-unknown")
        self.assertEqual(by_id["V"]["outcome"], "verified")
        self.assertEqual(by_id["V"]["last_refusal"]["decision"], "blocked-verified")
        self.assertFalse(by_id["U"]["spend_complete"])

    def test_reservation_overrun_is_a_problem_even_inside_caps(self):
        row = entry("O", "cloud-C", "dispatched", 10000, 1000, .0015)
        row["reserved_cost_usd"] = .001
        report = pr.build_report(PRICES, [row])
        self.assertEqual(report["accounting_status"], "GAPS_FOUND")
        self.assertTrue(report["pilot"]["halted"])
        self.assertEqual(report["pilot"]["reservation_overruns"], 1)

    def test_later_known_work_cannot_complete_an_unknown_verification_send(self):
        unknown = entry("A", "cloud-C", "dispatch-error", None, None, None)
        unknown.update(purpose="verification", review_reserved_usd=.1)
        known = entry("A", "cloud-C", "dispatched", 10000, 1000, .0015)
        known["usage_status"] = "observed"
        rows = [unknown, known, entry("A", "cloud-C", "verification-complete", 0, 0, 0)]
        report = pr.build_report(PRICES, rows)
        self.assertEqual(report["per_task"][0]["outcome"], "usage-unknown")
        self.assertFalse(report["per_task"][0]["spend_complete"])
        self.assertEqual(report["accounting_status"], "GAPS_FOUND")

    def test_abandonment_is_terminal_and_does_not_claim_acceptance(self):
        work = entry("A", "cloud-C", "dispatched", 10000, 1000, .0015)
        work.update(usage_status="observed", review_reserved_usd=.1)
        rows = [work, entry("A", "cloud-C", "task-abandoned", 0, 0, 0),
                entry("A", "cloud-C", "blocked-abandoned", 0, 0, 0)]
        report = pr.build_report(PRICES, rows)
        self.assertEqual(report["per_task"][0]["outcome"], "abandoned")
        self.assertEqual(report["pilot"]["reserved_usd"], 0)
        self.assertEqual(report["pilot"]["total_spend_usd"], .0015)

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
