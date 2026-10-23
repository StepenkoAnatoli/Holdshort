#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_dispatcher


class TestShadowMode(unittest.TestCase):
    def test_shadow_records_mode_and_does_not_block(self):
        prices = live_dispatcher.load_prices(Path(__file__).resolve().parent / "prices-2.json")
        tmp = Path(tempfile.mkdtemp())
        ledger = tmp / "shadow.jsonl"
        d = live_dispatcher.LiveDispatcher(prices, ledger, shadow=True)
        e = d.attempt("t1", "cloud-C", "probe", work_bound=0.01, review_bound=0.01,
                      expected_in=1000, expected_out=100)
        self.assertEqual(e.decision, "dispatched")
        # mode recorded
        lines = ledger.read_text().strip().splitlines()
        self.assertTrue(lines)
        rec = json.loads(lines[-1])
        self.assertEqual(rec.get("mode"), "shadow")

    def test_enforce_mode_default(self):
        prices = live_dispatcher.load_prices(Path(__file__).resolve().parent / "prices-2.json")
        tmp = Path(tempfile.mkdtemp())
        ledger = tmp / "enforce.jsonl"
        d = live_dispatcher.LiveDispatcher(prices, ledger)
        e = d.attempt("t1", "cloud-C", "probe", work_bound=0.01, review_bound=0.01,
                      expected_in=1000, expected_out=100)
        lines = ledger.read_text().strip().splitlines()
        rec = json.loads(lines[-1])
        self.assertEqual(rec.get("mode"), "enforce")


if __name__ == "__main__":
    unittest.main(verbosity=2)
PY