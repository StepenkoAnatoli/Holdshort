#!/usr/bin/env python3
"""Tests for tools/pricing.py — prompt-length-tiered rates (Haiku 5.5)."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import pricing  # noqa: E402
import pilot_report as pr  # noqa: E402

spec = importlib.util.spec_from_file_location("ld", TOOLS / "live_dispatcher.py")
ld = importlib.util.module_from_spec(spec)
sys.modules["ld"] = ld
spec.loader.exec_module(ld)

PRICES = json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8"))
HAIKU = PRICES["profiles"]["cloud-C"]


class TieredRates(unittest.TestCase):

    def test_at_threshold_uses_base_rate(self):
        # "over 100,000" — exactly 100,000 is still the base tier
        self.assertAlmostEqual(pricing.token_cost(HAIKU, 100_000, 1_000),
                               (100_000 * 0.10 + 1_000 * 0.50) / 1e6, places=12)

    def test_over_threshold_reprices_input_and_output(self):
        self.assertAlmostEqual(pricing.token_cost(HAIKU, 100_001, 1_000),
                               (100_001 * 0.50 + 1_000 * 2.50) / 1e6, places=12)

    def test_150k_matches_pricing_page(self):
        self.assertAlmostEqual(pricing.token_cost(HAIKU, 150_000, 1_000), 0.0775, places=12)

    def test_flat_profiles_unchanged(self):
        for pid, (i, o) in {"cloud-S": (2, 10), "cloud-O": (4, 20), "cloud-F": (10, 50)}.items():
            p = PRICES["profiles"][pid]
            self.assertAlmostEqual(pricing.token_cost(p, 500_000, 1_000),
                                   (500_000 * i + 1_000 * o) / 1e6, places=12)

    def test_report_recompute_matches_dispatcher(self):
        # the audit must not flag correctly-priced long-context spend
        for n in (10_000, 100_000, 100_001, 900_000):
            self.assertEqual(pr.recompute_cost(PRICES, "cloud-C", n, 2_000),
                             ld.LiveDispatcher._cost(HAIKU, n, 2_000))


class FailClosed(unittest.TestCase):

    def test_condition_without_long_context_is_unpriceable(self):
        bad = copy.deepcopy(HAIKU)
        del bad["long_context"]
        with self.assertRaises(pricing.UnpriceableProfile):
            pricing.validate_profile(bad)

    def test_malformed_long_context_is_unpriceable(self):
        for mutate in (lambda lc: lc.update(threshold_input_tokens=0),
                       lambda lc: lc.update(threshold_input_tokens=1.5),
                       lambda lc: lc.update(input_rate_per_mtok=float("nan")),
                       lambda lc: lc.update(output_rate_per_mtok=-1),
                       lambda lc: lc.pop("output_rate_per_mtok")):
            bad = copy.deepcopy(HAIKU)
            mutate(bad["long_context"])
            with self.assertRaises(pricing.UnpriceableProfile):
                pricing.validate_profile(bad)

    def test_dispatcher_blocks_unpriceable_row_before_spend(self):
        bad_prices = copy.deepcopy(PRICES)
        del bad_prices["profiles"]["cloud-C"]["long_context"]
        with tempfile.TemporaryDirectory() as td:
            d = ld.LiveDispatcher(bad_prices, Path(td) / "l.jsonl",
                                  task_store=Path(td) / "ts")
            e = d.attempt("T", "cloud-C", "x", work_bound=0.1, review_bound=0.1,
                          expected_in=150_000, expected_out=1_000)
        self.assertEqual(e.decision, "blocked-gate4")
        self.assertEqual(e.cost_usd, 0.0)

    def test_dispatcher_records_long_context_cost(self):
        with tempfile.TemporaryDirectory() as td:
            d = ld.LiveDispatcher(PRICES, Path(td) / "l.jsonl",
                                  task_store=Path(td) / "ts")
            e = d.attempt("T", "cloud-C", "x", work_bound=0.1, review_bound=0.1,
                          expected_in=150_000, expected_out=1_000)
        self.assertEqual(e.decision, "dispatched")
        self.assertAlmostEqual(e.cost_usd, 0.0775, places=12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
