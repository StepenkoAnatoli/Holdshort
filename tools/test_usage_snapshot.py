import json
from pathlib import Path
import tempfile
import unittest

import usage_snapshot as usage


class UsageSnapshot(unittest.TestCase):
    def extract(self, events):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "session.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            return usage.snapshot(path)

    def test_unknown_usage_is_not_zero(self):
        result = self.extract([{"type": "event_msg", "payload": {"type": "token_count", "info": None}}])
        self.assertIsNone(result["cumulative_usage"])
        self.assertIsNone(result["provider_cost_usd"])
        self.assertEqual(result["usage_status"], "unknown")

    def test_latest_missing_usage_does_not_reuse_an_older_count(self):
        result = self.extract([
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10}}}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
        ])
        self.assertIsNone(result["cumulative_usage"])

    def test_cache_is_not_added_and_content_is_not_exported(self):
        result = self.extract([
            {"type": "turn_context", "payload": {"model": "model-a", "effort": "high", "instructions": "PRIVATE-CONTENT"}},
            {"type": "turn_context", "payload": {"model": "model-b"}},
            {"type": "response_item", "payload": {"text": "PRIVATE-CONTENT"}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "cached_input_tokens": 90, "output_tokens": 10, "total_tokens": 110}}}},
        ])
        self.assertEqual(result["cumulative_usage"]["total_tokens"], 110)
        self.assertEqual(result["models_observed"], ["model-a", "model-b"])
        self.assertNotIn("PRIVATE-CONTENT", json.dumps(result))
        self.assertFalse(result["is_final_bill"])

    def test_invalid_counters_fail(self):
        for value in ({"input_tokens": -1}, {"input_tokens": True},
                      {"input_tokens": 2, "cached_input_tokens": 3}):
            with self.assertRaises(ValueError):
                usage.counters(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
