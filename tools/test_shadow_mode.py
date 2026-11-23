#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_dispatcher
from copy import deepcopy


class TestShadowMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prices = live_dispatcher.load_prices(Path(__file__).resolve().parent / "prices-2.json")
        self.calls = []
        self.clock = 1000.0

    def dispatcher(self, *, shadow=True, config=None, unknown=False):
        def send(profile, request):
            self.calls.append((profile, request))
            if unknown:
                raise live_dispatcher.DispatchFailure("synthetic unknown usage")
            return 100, 10
        send.max_tokens = 10
        send.count_tokens = lambda *args: 100
        return live_dispatcher.LiveDispatcher(
            config or self.prices, self.root / "ledger.jsonl", shadow=shadow,
            dispatch_fn=send, confirm_egress=True, now_fn=lambda: self.clock)

    def attempt(self, dispatcher, task="t", profile="cloud-C", **kwargs):
        return dispatcher.attempt(task, profile, "synthetic", work_bound=.01,
                                  review_bound=0, expected_in=100, expected_out=10, **kwargs)

    def test_terminal_stops_survive_a_restart_in_shadow_mode(self):
        for terminal, decision in (("abandon_task", "blocked-abandoned"),
                                   ("complete_verification", "blocked-verified")):
            with self.subTest(terminal=terminal):
                d = self.dispatcher()
                self.assertEqual(self.attempt(d, terminal).decision, "dispatched")
                getattr(d, terminal)(terminal, evidence_ref="synthetic-evidence")
                before = len(self.calls)
                result = self.attempt(self.dispatcher(), terminal)
                self.assertEqual(result.decision, decision)
                self.assertEqual(result.mode, "shadow")
                self.assertEqual(len(self.calls), before)

    def test_unknown_usage_stops_new_tasks_even_after_a_restart(self):
        self.assertEqual(self.attempt(self.dispatcher(unknown=True)).decision, "dispatch-error")
        result = self.attempt(self.dispatcher(), "another-task")
        self.assertEqual(result.decision, "blocked-uncertain")
        self.assertEqual(len(self.calls), 1)

    def test_attempt_repair_and_pilot_caps_still_block_before_transport(self):
        for cap, value, decision in (("max_attempts_per_task", 1, "blocked-attempt-cap"),
                                    ("same_profile_repairs_allowed_per_task", 0, "blocked-repair-cap"),
                                    ("max_cost_per_pilot_usd", .01, "blocked-pilot-cap")):
            with self.subTest(cap=cap), tempfile.TemporaryDirectory() as td:
                self.root = Path(td)
                self.calls.clear()
                config = deepcopy(self.prices)
                config["pilot_caps"][cap] = value
                d = self.dispatcher(config=config)
                self.assertEqual(self.attempt(d).decision, "dispatched")
                self.assertEqual(self.attempt(d).decision, decision)
                self.assertEqual(len(self.calls), 1)

    def test_verification_requires_an_owned_reservation(self):
        result = self.attempt(self.dispatcher(), purpose="verification", review_calls=0)
        self.assertEqual(result.decision, "blocked-gate4")
        self.assertEqual(self.calls, [])

    def test_expiry_and_clock_rollback_remain_stops(self):
        d = self.dispatcher()
        self.assertEqual(self.attempt(d).decision, "dispatched")
        self.clock += self.prices["pilot_caps"]["max_elapsed_seconds_per_task"]
        self.assertEqual(self.attempt(d).decision, "blocked-deadline")
        self.clock = 999
        self.assertEqual(self.attempt(d).decision, "blocked-deadline")
        self.assertEqual(len(self.calls), 1)

    def test_shadow_records_mode_for_an_allowed_dry_run(self):
        prices = live_dispatcher.load_prices(Path(__file__).resolve().parent / "prices-2.json")
        tmp = self.root
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
        tmp = self.root
        ledger = tmp / "enforce.jsonl"
        d = live_dispatcher.LiveDispatcher(prices, ledger)
        e = d.attempt("t1", "cloud-C", "probe", work_bound=0.01, review_bound=0.01,
                      expected_in=1000, expected_out=100)
        lines = ledger.read_text().strip().splitlines()
        rec = json.loads(lines[-1])
        self.assertEqual(rec.get("mode"), "enforce")


if __name__ == "__main__":
    unittest.main(verbosity=2)
