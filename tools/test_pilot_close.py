#!/usr/bin/env python3
"""Tests for tools/pilot_close.py — synthetic ledgers, no network."""
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
spec = importlib.util.spec_from_file_location("pc", TOOLS / "pilot_close.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)

spec2 = importlib.util.spec_from_file_location("pr", TOOLS / "pilot_report.py")
pr = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(pr)

PRICES = json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8"))


def e(tid, pid, dec, in_t, out_t, cost):
    return {"ts": 0.0, "task_id": tid, "attempt_no": 1, "profile_id": pid,
            "input_tokens": in_t, "output_tokens": out_t, "cost_usd": cost,
            "decision": dec, "reason": "test"}


def entries_completed_one_task():
    # cloud-C 10k in / 1k out = $0.0015 per dispatch
    return [e("L-001", "cloud-C", "dispatched", 10_000, 1_000, 0.0015),
            e("L-001", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]


class PilotCloseSheetMode(unittest.TestCase):
    """Session-close --with-sheet: regenerate, tally, embed; idempotent."""

    def test_with_sheet_embeds_fill_status_and_is_idempotent(self):
        sheet = Path(self.td.name) / "sheet.json"
        assign = {"L-001": {"arm": "B", "cell": "T-01"}}
        entries = pr.load_jsonl(Path(self.td.name) / "led.jsonl")
        s1 = pc.build_sheet_section(entries, assign, sheet)
        self.assertEqual(s1["sheet_action"], "generated-skeleton")
        self.assertEqual(s1["ledger_lines_placed"], 2)
        self.assertEqual(s1["per_cell"]["B|T-01"]["recorded"], 2)
        self.assertTrue(s1["integrity_ok"])
        s2 = pc.build_sheet_section(entries, assign, sheet)
        self.assertEqual(s2["sheet_action"], "loaded-existing")
        self.assertEqual(s2["ledger_lines_placed"], 0)
        self.assertEqual(s2["observations_recorded"], s1["observations_recorded"])

    def test_with_sheet_discloses_unplaced_lines(self):
        entries = pr.load_jsonl(Path(self.td.name) / "led.jsonl") + [
            e("L-404", "cloud-C", "dispatched", 10_000, 1_000, 0.0015)]
        s = pc.build_sheet_section(entries, {}, Path(self.td.name) / "sheet2.json")
        self.assertEqual(len(s["ledger_lines_unplaced"]), 3)
        self.assertTrue(all(m["kind"] == "unassigned" for m in s["ledger_lines_unplaced"]))
        md = pc.embed_sheet_markdown(s)
        self.assertIn("Unplaced ledger lines", md)

    def test_existing_sheet_imports_appended_evidence(self):
        sheet = Path(self.td.name)/"append.json"
        assign = {"L-001":{"arm":"B","cell":"T-01"}}
        entries = entries_completed_one_task()
        first = pc.build_sheet_section(entries[:1],assign,sheet)
        second = pc.build_sheet_section(entries,assign,sheet)
        self.assertEqual(first["observations_recorded"],1)
        self.assertEqual(second["observations_recorded"],2)
        self.assertEqual(second["ledger_lines_placed"],1)
        self.assertEqual(second["ledger_lines_unplaced"],[])

    def test_markdown_renders_string_integrity_findings(self):
        sheet = Path(self.td.name)/"bad.json"
        sheet.write_text("{}",encoding="utf-8")
        summary = pc.build_sheet_section(entries_completed_one_task(),{},sheet)
        self.assertFalse(summary["integrity_ok"])
        self.assertIn("integrity violations",pc.embed_sheet_markdown(summary))

    def test_unplaced_findings_fail_session_close(self):
        root=Path(self.td.name); mapping=root/"map.json"
        mapping.write_text("{}",encoding="utf-8")
        rc=pc.main(["--ledger",str(root/"led.jsonl"),"--with-sheet","--sheet",str(root/"unplaced.json"),"--assignments",str(mapping)])
        self.assertEqual(rc,1)

    def setUp(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        led = Path(self.td.name) / "led.jsonl"
        led.write_text(chr(10).join(json.dumps(x) for x in entries_completed_one_task()),
                       encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()


class PilotClose(unittest.TestCase):

    def _authority_fixture(self, directory):
        import live_dispatcher as ld
        ledger = Path(directory) / "ledger.jsonl"
        dispatcher = ld.LiveDispatcher(PRICES, ledger, now_fn=lambda: 1000)
        result = dispatcher.attempt("authority-task", "cloud-C", "synthetic", work_bound=.01,
                                    review_bound=.02, expected_in=10000, expected_out=1000)
        self.assertEqual(result.decision, "dispatched")
        return ledger

    def _close_cli(self, ledger, *extra):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = pc.main(["--ledger", str(ledger), *extra])
        return status, json.loads(output.getvalue())

    def test_cli_uses_authority_without_optional_store(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            authority = ledger.with_name(ledger.name + ".budget.sqlite3")
            before = (ledger.read_bytes(), authority.read_bytes())
            status, closed = self._close_cli(ledger)
            self.assertEqual(status, 0, closed["pilot_totals"]["problems"])
            self.assertEqual(closed["pilot_totals"]["accounting_source"], "sqlite-authority")
            self.assertEqual(closed["pilot_totals"]["total_spend_usd"], .0015)
            self.assertEqual(closed["closures"][0]["disposition"], "awaiting-verification")
            self.assertEqual(before, (ledger.read_bytes(), authority.read_bytes()))

    def test_cli_lagging_mirror_does_not_invent_sheet_source_records(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            ledger.write_text(ledger.read_text().splitlines()[0] + "\n", encoding="utf-8")
            mapping = Path(directory) / "assignments.json"
            mapping.write_text(json.dumps({"authority-task": {"arm": "B", "cell": "T-01"}}), encoding="utf-8")
            status, closed = self._close_cli(ledger, "--with-sheet", "--sheet", str(Path(directory) / "sheet.json"),
                                            "--assignments", str(mapping))
            self.assertEqual(status, 1)
            self.assertEqual(closed["pilot_totals"]["total_spend_usd"], .0015)
            self.assertFalse(closed["pilot_totals"]["total_spend_complete"])
            self.assertEqual(closed["live_fill_sheet"]["observations_recorded"], 0)
            self.assertTrue(any(finding["kind"] == "unknown-usage" for finding in
                                closed["live_fill_sheet"]["ledger_lines_unplaced"]))
            self.assertEqual(len(ledger.read_text().splitlines()), 1)

    def test_cli_missing_mirror_reports_known_authority_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            ledger.unlink()
            status, closed = self._close_cli(ledger)
            self.assertEqual(status, 1)
            self.assertEqual(closed["pilot_totals"]["total_spend_usd"], .0015)
            self.assertFalse(closed["pilot_totals"]["total_spend_complete"])
            self.assertEqual(closed["pilot_totals"]["source_evidence"]["jsonl_events"], 0)
            self.assertFalse(ledger.exists())

    def test_cli_corrupt_authority_makes_headroom_and_completion_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = self._authority_fixture(directory)
            authority = ledger.with_name(ledger.name + ".budget.sqlite3")
            authority.write_bytes(b"synthetic corrupt authority")
            before = (ledger.read_bytes(), authority.read_bytes())
            status, closed = self._close_cli(ledger)
            self.assertEqual(status, 1)
            self.assertIsNone(closed["pilot_totals"]["headroom_usd"])
            self.assertIsNone(closed["pilot_totals"]["within_pilot_cap"])
            self.assertEqual(closed["closures"][0]["disposition"], "accounting-unverified")
            self.assertIn("headroom unknown", pc.markdown(closed))
            self.assertEqual(before, (ledger.read_bytes(), authority.read_bytes()))

    def test_unknown_spend_is_explicit_in_json_and_markdown(self):
        row = e("U", "cloud-C", "dispatch-error", None, None, None)
        row.update(reserved_cost_usd=.1, review_reserved_usd=.02, known_cost_usd=.001)
        closure = pc.close_ledger(PRICES, [row, e("U", "cloud-C", "blocked-uncertain", 0, 0, 0)])
        task = closure["closures"][0]
        self.assertEqual(task["disposition"], "usage-unknown")
        self.assertFalse(task["spend_complete"])
        self.assertIsNone(task["within_cost_cap"])
        self.assertIsNone(closure["pilot_totals"]["within_pilot_cap"])
        md = pc.markdown(closure)
        self.assertIn("known 0.001000; incomplete", md)
        self.assertIn("UNKNOWN", md)
        self.assertIn("reserved", md)

    def test_verified_task_stays_completed_after_refused_retry(self):
        rows = entries_completed_one_task()[:1]
        rows += [e("L-001", "cloud-C", "verification-complete", 0, 0, 0),
                 e("L-001", "cloud-C", "blocked-verified", 0, 0, 0)]
        closure = pc.close_ledger(PRICES, rows)
        self.assertEqual(closure["pilot_totals"]["completed"], 1)
        self.assertEqual(closure["closures"][0]["disposition"], "completed")

    def test_completed_task_closure(self):
        r = pc.close_ledger(PRICES, entries_completed_one_task())
        c = r["closures"][0]
        self.assertEqual(c["task_id"], "L-001")
        self.assertEqual(c["attempts"], 2)
        self.assertAlmostEqual(c["spend_usd"], 0.003, places=6)
        self.assertEqual(c["disposition"], "completed")
        self.assertTrue(c["within_attempt_cap"] and c["within_cost_cap"])
        self.assertFalse(c["accounting_gap"])

    def test_blocked_task_disposition(self):
        entries = [e("L-002", "cloud-C", "blocked-cost-cap", 0, 0, 0.0)]
        r = pc.close_ledger(PRICES, entries)
        self.assertEqual(r["closures"][0]["disposition"], "blocked:cap")
        self.assertEqual(r["pilot_totals"]["blocked"], 1)
        self.assertEqual(r["pilot_totals"]["completed"], 0)

    def test_mixed_outcome_task(self):
        entries = [e("L-003", "cloud-C", "dispatched", 10_000, 1_000, 0.0015),
                   e("L-003", "cloud-C", "blocked-gate4", 0, 0, 0.0)]
        r = pc.close_ledger(PRICES, entries)
        self.assertEqual(r["closures"][0]["disposition"], "blocked:gate")
        self.assertEqual(r["closures"][0]["attempts"], 1)

    def test_totals_math(self):
        entries = entries_completed_one_task()
        entries += [e("L-002", "cloud-C", "blocked-cost-cap", 0, 0, 0.0)]
        r = pc.close_ledger(PRICES, entries)
        p = r["pilot_totals"]
        self.assertEqual(p["tasks_closed"], 2)
        self.assertEqual(p["completed"], 1)
        self.assertEqual(p["blocked"], 1)
        self.assertEqual(p["dispatches"], 2)
        self.assertAlmostEqual(p["total_spend_usd"], 0.003, places=6)
        self.assertAlmostEqual(p["headroom_usd"], 19.997, places=6)
        self.assertTrue(p["within_pilot_cap"])

    def test_gap_ledger_flags_and_exit_code_1(self):
        # cost mismatch → accounting gap; closure still produced but flagged
        entries = [e("L-009", "cloud-C", "dispatched", 10_000, 1_000, 0.099)]  # wrong on purpose
        r = pc.close_ledger(PRICES, entries)
        self.assertTrue(r["closures"][0]["accounting_gap"])
        self.assertEqual(r["pilot_totals"]["accounting_status"], "GAPS_FOUND")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in entries), encoding="utf-8")
            rc = pc.main(["--ledger", str(p)])
            self.assertEqual(rc, 1)

    def test_markdown_block_shape(self):
        r = pc.close_ledger(PRICES, entries_completed_one_task())
        md = pc.markdown(r)
        self.assertIn("| Task | Attempts | Spend (USD) | Reserved (USD) | Disposition | Caps OK |", md)
        self.assertIn("| L-001 | 2 | 0.003000", md)
        self.assertIn("Pilot totals", md)
        self.assertIn("No section-7 decision", md)

    def test_main_markdown_roundtrip_exit_0(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in entries_completed_one_task()), encoding="utf-8")
            rc = pc.main(["--ledger", str(p), "--markdown"])
            self.assertEqual(rc, 0)

    def test_main_empty_ledger_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            self.assertEqual(pc.main(["--ledger", str(p)]), 2)

    def test_decision_neutrality_note(self):
        r = pc.close_ledger(PRICES, entries_completed_one_task())
        self.assertIn("No §7 decision", r["decision_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
