#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

sys_path = None
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapter_config


class TestAdapterConfig(unittest.TestCase):
    def test_load_anthropic(self):
        cfg = adapter_config.load(Path(__file__).resolve().parent / "profiles" / "anthropic.json")
        self.assertEqual(cfg["schema_version"], 1)
        self.assertEqual(cfg["provider"], "anthropic")
        self.assertIn("cloud-C", adapter_config.model_map(cfg))

    def test_missing_fields_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text(json.dumps({"provider": "x"}), encoding="utf-8")
            with self.assertRaises(adapter_config.AdapterConfigError):
                adapter_config.load(p)

    def test_profile_without_price_model_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text(json.dumps({
                "schema_version": 1, "provider": "x", "approved_endpoint": "https://e",
                "auth_env_var": "K", "model_for_profile": {"a": "m"},
                "price_model_for_profile": {}
            }), encoding="utf-8")
            with self.assertRaises(adapter_config.AdapterConfigError):
                adapter_config.load(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
PY