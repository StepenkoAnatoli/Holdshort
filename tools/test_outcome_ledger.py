#!/usr/bin/env python3
"""Tests for tools/outcome_ledger.py — the canonical §10.3 Outcome store.

  O1. record writes a schema-valid line; get returns the latest entry for a task
  O2. unknown outcome / missing keys / mistyped evidence fail closed on write
  O3. verify passes a clean file and fails closed on a malformed line or a
      schema-violating line (never reads defects as "no outcomes")
  O4. list filters by outcome; get on an unknown task exits 1 (not fail-closed)
  O5. optional fingerprint/class survive the round trip; unknown keys preserved
  O6. superseding receipts: a second record for one task does not erase the first,
      and get returns the newest (plan: append, recompute, never rewrite history)
Run as part of the regression gate (tools/run_regression.py).
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
TOOL = REPO / "tools" / "outcome_ledger.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ol = _load("oll", TOOL)


def good(task: str = "t1", outcome: str = "accepted") -> dict:
    return {"task-id": task, "outcome": outcome,
            "evidence": {"checks": [{"command": "pytest -q", "exit-code": 0,
                                     "output-ref": "r1"}],
                         "actual-spend": 0.04, "files-touched": ["src/a.py"],
                         "notes": "done"},
            "owner-profile": "worker"}


class OutcomeLedger(unittest.TestCase):

    # O1 ----------------------------------------------------------------------
    def test_o1_record_then_get_latest(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            stored = ol.record(led, good("t1"))
            self.assertIn("recorded_at", stored)
            self.assertEqual(ol.latest_for(ol.read_all(led), "t1")["outcome"], "accepted")

    # O2 ----------------------------------------------------------------------
    def test_o2_bad_entries_fail_closed_on_write(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            bad_outcome = good()
            bad_outcome["outcome"] = "shipped-it"
            with self.assertRaises(ol.FailClosed):
                ol.record(led, bad_outcome)
            for drop in ("task-id", "outcome", "evidence", "owner-profile"):
                with self.subTest(drop=drop):
                    doc = good()
                    del doc[drop]
                    with self.assertRaises(ol.FailClosed):
                        ol.record(led, doc)
            mistyped = good()
            mistyped["evidence"]["actual-spend"] = "cheap"
            with self.assertRaises(ol.FailClosed):
                ol.record(led, mistyped)
            self.assertFalse(led.exists(), "refused writes must leave no file")

    # O3 ----------------------------------------------------------------------
    def test_o3_verify_fails_closed_on_defects(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            ol.record(led, good("t1"))
            self.assertEqual(len(ol.read_all(led)), 1)
            with led.open("a", encoding="utf-8") as fh:
                fh.write('{ not json\n')
            with self.assertRaises(ol.FailClosed):
                ol.read_all(led)
            led.write_text(json.dumps(good("t1")) + "\n" +
                           json.dumps({"task-id": "t2"}) + "\n", encoding="utf-8")
            with self.assertRaises(ol.FailClosed):
                ol.read_all(led)

    # O4 ----------------------------------------------------------------------
    def test_o4_list_filters_and_get_misses_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            ol.record(led, good("t1", "accepted"))
            ol.record(led, good("t2", "blocked"))
            r = subprocess.run([sys.executable, str(TOOL), "list", "--ledger", str(led),
                                "--outcome", "blocked"], capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 0)
            self.assertIn("t2", r.stdout)
            self.assertNotIn("t1", r.stdout)
            miss = subprocess.run([sys.executable, str(TOOL), "get", "--ledger", str(led),
                                   "--task-id", "nope"], capture_output=True, text=True,
                                  timeout=60)
            self.assertEqual(miss.returncode, 1, "unknown task is empty, not corrupt")
            self.assertNotIn("FAIL-CLOSED", miss.stderr)

    # O5 ----------------------------------------------------------------------
    def test_o5_optionals_and_unknown_keys_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            doc = good("t9")
            doc["original-brief-fingerprint"] = "abc123"
            doc["class"] = "auth"
            doc["future-field"] = {"nested": [1, 2]}
            stored = ol.record(led, doc)
            back = ol.latest_for(ol.read_all(led), "t9")
            self.assertEqual(back["original-brief-fingerprint"], "abc123")
            self.assertEqual(back["class"], "auth")
            self.assertEqual(back["future-field"], {"nested": [1, 2]})
            self.assertIn("recorded_at", stored)

    # O6 ----------------------------------------------------------------------
    def test_o6_superseding_receipt_appends(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            ol.record(led, good("t1", "verification-failed"))
            ol.record(led, good("t1", "accepted"))
            entries = ol.read_all(led)
            self.assertEqual(len(entries), 2, "history is appended, never rewritten")
            self.assertEqual(ol.latest_for(entries, "t1")["outcome"], "accepted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
