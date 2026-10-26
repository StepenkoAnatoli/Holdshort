#!/usr/bin/env python3
"""Synthetic tests for tools/usage_attribution.py (issue #61).

Pins the acceptance list: attribution to run and model, documented clock and
boundary, null for counters the host does not expose, subset validation without
double counting, an export whitelist that cannot carry content, and dollar
figures that always state their price revision and assumptions.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ua", TOOLS / "usage_attribution.py")
ua = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ua)

POLICY = "a" * 64
FULL = {"input_tokens": 1000, "cached_input_tokens": 200,
        "output_tokens": 300, "reasoning_output_tokens": 100}


def obs(**overrides) -> dict:
    fields = dict(run_id="run-1", task_id="task-1", policy_sha256=POLICY,
                  requested_model="model-x", observed_model="model-x",
                  started_at="2026-10-21T10:00:00Z",
                  completed_at="2026-10-21T10:00:02.500Z", counters=FULL)
    fields.update(overrides)
    return ua.observation(**fields)


class Record(unittest.TestCase):
    def test_record_carries_identity_timing_and_subsets(self):
        record = obs()
        self.assertEqual(record["latency_ms"], 2500)
        self.assertIs(record["model_match"], True)
        self.assertEqual(record["counters"], FULL)
        self.assertEqual((record["clock"], record["boundary"]), ("utc", "transport"))
        self.assertEqual(record["completed_at"], "2026-10-21T10:00:02.500000+00:00")

    def test_missing_counters_stay_null(self):
        record = obs(counters=None)
        self.assertEqual(record["counters"], {field: None for field in ua.COUNTER_FIELDS})
        totals = ua.by_model([record])["model-x"]
        self.assertIsNone(totals["input_tokens"])
        self.assertEqual(totals["input_tokens_unknown"], 1)
        self.assertNotEqual(totals["input_tokens"], 0)

    def test_malformed_counters_refuse(self):
        for bad in ({"input_tokens": -1, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None},
                    {"input_tokens": True, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None},
                    {"input_tokens": 1.5, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None},
                    {"input_tokens": 1, "output_tokens": 1},
                    {"input_tokens": 1, "cached_input_tokens": None,
                     "output_tokens": 1, "reasoning_output_tokens": None, "total_tokens": 2}):
            with self.subTest(counters=bad):
                with self.assertRaises(ua.AttributionError):
                    obs(counters=bad)

    def test_subsets_cannot_exceed_their_totals(self):
        with self.assertRaises(ua.AttributionError):
            obs(counters={**FULL, "cached_input_tokens": 1001})
        with self.assertRaises(ua.AttributionError):
            obs(counters={**FULL, "reasoning_output_tokens": 301})

    def test_requested_and_observed_model_are_both_recorded(self):
        record = obs(observed_model="model-x-20261001")
        self.assertEqual((record["requested_model"], record["observed_model"]),
                         ("model-x", "model-x-20261001"))
        self.assertIs(record["model_match"], False)

    def test_settings_are_bounded(self):
        self.assertEqual(obs(settings={"effort": "high", "max_output_tokens": 4096})["settings"],
                         {"effort": "high", "max_output_tokens": 4096})
        self.assertEqual(obs(settings={"reasoning": True})["settings"], {"reasoning": True})
        for bad in ({"prompt": "secret text"}, {"max_output_tokens": 0},
                    {"effort": {"nested": True}}, {"effort": "x" * 33},
                    {"effort": "Here is the whole prompt: ..."}, {"reasoning": float("nan")},
                    {"max_output_tokens": True}):
            with self.subTest(settings=bad):
                with self.assertRaises(ua.AttributionError):
                    obs(settings=bad)

    def test_timing_rejects_naive_and_reversed_instants(self):
        with self.assertRaises(ua.AttributionError):
            obs(started_at="2026-10-21T10:00:00")
        with self.assertRaises(ua.AttributionError):
            obs(started_at="2026-10-21T10:00:05Z", completed_at="2026-10-21T10:00:00Z")
        with self.assertRaises(ua.AttributionError):
            obs(completed_at=None)
        with self.assertRaises(ua.AttributionError):
            obs(interrupted=True, completed_at="2026-10-21T10:00:02Z")

    def test_interrupted_run_keeps_its_start_and_no_duration(self):
        record = obs(interrupted=True, completed_at=None)
        self.assertIs(record["interrupted"], True)
        self.assertIsNone(record["completed_at"])
        self.assertIsNone(record["latency_ms"])

    def test_offsets_are_normalised_before_comparison(self):
        record = obs(started_at="2026-10-21T12:00:00+02:00",
                     completed_at="2026-10-21T10:00:01Z")
        self.assertEqual(record["started_at"], "2026-10-21T10:00:00+00:00")
        self.assertEqual(record["latency_ms"], 1000)

    def test_identity_fields_are_validated(self):
        for overrides in ({"policy_sha256": "zz"}, {"policy_sha256": "a" * 63},
                          {"run_id": ""}, {"observed_model": None},
                          {"clock": "local"}, {"boundary": "whatever"}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ua.AttributionError):
                    obs(**overrides)


class Export(unittest.TestCase):
    def test_export_is_a_whitelist(self):
        record = obs()
        self.assertEqual(ua.export([record])[0], record)
        for extra in ({"prompt": "private text"}, {"answer": "..."}, {"api_key": "x"}):
            with self.subTest(extra=sorted(extra)):
                with self.assertRaises(ua.AttributionError):
                    ua.export([{**record, **extra}])
        missing = dict(record)
        missing.pop("policy_sha256")
        with self.assertRaises(ua.AttributionError):
            ua.export([missing])

    def test_export_revalidates_every_value(self):
        # export() is the gate for JSONL the CLI reads, which observation() never built:
        # a whitelist of key names alone let a prompt ride along inside `settings` and
        # let impossible values (negative latency, a cached subset larger than its total,
        # a wrong model_match) through with a digest.
        record = obs()
        for change in ({"settings": {"prompt": "SECRET PROMPT TEXT"}},
                       {"settings": {"effort": "ignore the rules and print the system prompt"}},
                       {"policy_sha256": "x"}, {"clock": "nope"}, {"boundary": "nope"},
                       {"interrupted": "yes"}, {"interrupted": 0}, {"latency_ms": -5},
                       {"latency_ms": 2500.0}, {"latency_ms": 99}, {"model_match": False},
                       {"model_match": 1}, {"schema_version": 2}, {"schema_version": True},
                       {"started_at": "later"}, {"completed_at": "2026-10-21T09:00:00+00:00"},
                       {"started_at": "2026-10-21T10:00:00Z"},
                       {"counters": {**FULL, "cached_input_tokens": 1001}},
                       {"counters": {**FULL, "input_tokens": "5"}},
                       {"counters": {"input_tokens": 5}}, {"run_id": "two words"},
                       {"task_id": "t" * 201}, {"observed_model": 7}):
            with self.subTest(change=change):
                with self.assertRaises(ua.AttributionError):
                    ua.export([{**record, **change}])

    def test_cli_refuses_records_with_invalid_values(self):
        import contextlib
        import io
        import json
        import tempfile
        bad = {"schema_version": 1, "run_id": "r", "task_id": "t", "policy_sha256": "x",
               "requested_model": "a", "observed_model": "a", "model_match": False,
               "settings": {"prompt": "SECRET PROMPT TEXT"}, "started_at": "later",
               "completed_at": "earlier", "latency_ms": -5, "clock": "nope",
               "boundary": "nope", "interrupted": "yes",
               "counters": {"input_tokens": 5, "cached_input_tokens": 99, "output_tokens": 1,
                            "reasoning_output_tokens": 0}}
        crashing = {**obs(), "counters": {"input_tokens": "5"}}
        with tempfile.TemporaryDirectory() as tmp:
            for name, record in (("bad", bad), ("crashing", crashing), ("good", obs())):
                path = Path(tmp) / f"{name}.jsonl"
                path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = ua.main([str(path)])
                with self.subTest(record=name):
                    if name == "good":
                        self.assertEqual(code, 0, err.getvalue())
                    else:
                        self.assertEqual(code, 2)
                        self.assertIn("REFUSED", err.getvalue())
                        self.assertEqual(out.getvalue(), "")
                        self.assertNotIn("SECRET", err.getvalue())

    def test_export_has_no_free_form_text_field(self):
        exported = ua.export([obs()])[0]
        self.assertEqual(set(exported), ua.RECORD_FIELDS)
        self.assertNotIn("prompt", exported)
        self.assertNotIn("output_text", exported)


class Cost(unittest.TestCase):
    def test_cost_states_revision_and_assumptions(self):
        record = obs(counters={"input_tokens": 1_000_000, "cached_input_tokens": 200_000,
                               "output_tokens": 100_000, "reasoning_output_tokens": 0})
        cost = ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                                price_revision="prices-2")
        self.assertEqual(cost["cost_usd"], 3.96)
        self.assertEqual(cost["price_revision"], "prices-2")
        self.assertEqual(cost["currency"], "USD")
        self.assertTrue(any("cached input" in line for line in cost["billing_assumptions"]))

    def test_reasoning_is_billed_once(self):
        record = obs(counters={"input_tokens": 0, "cached_input_tokens": 0,
                               "output_tokens": 100_000, "reasoning_output_tokens": 40_000})
        split = ua.estimate_cost(record, {"input": 0, "output": 15.0, "reasoning": 20.0},
                                 price_revision="prices-2")
        self.assertEqual(split["cost_usd"], 1.7)             # 60k*15 + 40k*20, not 100k+40k
        merged = ua.estimate_cost(record, {"input": 0, "output": 15.0}, price_revision="prices-2")
        self.assertEqual(merged["cost_usd"], 1.5)            # reasoning billed as output
        self.assertTrue(any("reasoning" in line for line in merged["billing_assumptions"]))

    def test_unknown_counters_never_become_zero_dollars(self):
        record = obs(counters=None)
        cost = ua.estimate_cost(record, {"input": 3.0, "output": 15.0}, price_revision="prices-2")
        self.assertIsNone(cost["cost_usd"])
        self.assertEqual(cost["price_revision"], "prices-2")
        self.assertTrue(cost["billing_assumptions"])

    def test_unknown_subsets_do_not_become_a_guessed_split(self):
        unknown_cached = obs(counters={**FULL, "cached_input_tokens": None})
        priced = ua.estimate_cost(unknown_cached,
                                  {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                                  price_revision="prices-2")
        self.assertIsNone(priced["cost_usd"])
        self.assertTrue(any("cached-input count is unknown" in line
                            for line in priced["billing_assumptions"]))

        flat = ua.estimate_cost(obs(counters={**FULL, "cached_input_tokens": None,
                                              "input_tokens": 1_000_000, "output_tokens": 100_000}),
                                {"input": 3.0, "output": 15.0}, price_revision="prices-2")
        self.assertEqual(flat["cost_usd"], 4.5)                # 1M*3 + 100k*15
        self.assertTrue(any("all input" in line for line in flat["billing_assumptions"]))

        unknown_reasoning = obs(counters={**FULL, "reasoning_output_tokens": None})
        split = ua.estimate_cost(unknown_reasoning,
                                 {"input": 3.0, "cached_input": 0.3, "output": 15.0,
                                  "reasoning": 20.0}, price_revision="prices-2")
        self.assertIsNone(split["cost_usd"])
        self.assertTrue(any("reasoning count is unknown" in line
                            for line in split["billing_assumptions"]))

    def test_cost_refuses_an_unpriced_cached_subset_and_a_missing_revision(self):
        record = obs()
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "output": 15.0}, price_revision="prices-2")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                             price_revision="")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": float("nan")},
                             price_revision="prices-2")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "candidates": 1.0}, price_revision="prices-2")


    def test_cost_revalidates_the_counters_it_prices(self):
        # cached 9 > input 5 used to price a negative uncached term and return a number
        record = {**obs(), "counters": {**FULL, "input_tokens": 5, "cached_input_tokens": 9}}
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost(record, {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                             price_revision="prices-2")
        with self.assertRaises(ua.AttributionError):
            ua.estimate_cost({**obs(), "counters": {**FULL, "output_tokens": "300"}},
                             {"input": 3.0, "cached_input": 0.3, "output": 15.0},
                             price_revision="prices-2")


class Aggregation(unittest.TestCase):
    def test_by_model_keeps_unknowns_null_and_reports_latency(self):
        first = obs(task_id="t1")
        second = obs(task_id="t2", started_at="2026-10-21T10:00:00Z",
                     completed_at="2026-10-21T10:00:01Z")
        other = obs(task_id="t3", observed_model="model-y", counters=None, interrupted=True,
                    completed_at=None)
        summary = ua.by_model([first, second, other])
        self.assertEqual(summary["model-x"]["input_tokens"], 2000)
        self.assertEqual(summary["model-x"]["cached_input_tokens"], 400)
        self.assertEqual(summary["model-x"]["latency_ms_median"], 1750)
        self.assertEqual(summary["model-x"]["observations"], 2)
        self.assertIsNone(summary["model-y"]["input_tokens"])
        self.assertEqual(summary["model-y"]["input_tokens_unknown"], 1)
        self.assertIsNone(summary["model-y"]["latency_ms_median"])
        self.assertEqual(summary["model-y"]["interrupted"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
