#!/usr/bin/env python3
"""Smoke test for hosts/generic/route.py."""
from __future__ import annotations

import subprocess
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "hosts" / "generic" / "route.py"


class GenericHostSmoke(unittest.TestCase):
    def test_templates_and_qualification_helper_import_without_running(self):
        paths = ("hosts/generic/route.py", "hosts/generic/full_loop.py",
                 "hosts/generic/production_adapter.py", "hosts/cursor/route.py",
                 "tools/qualify_billing.py")
        for path in paths:
            with self.subTest(path=path):
                spec = importlib.util.spec_from_file_location("host_template", ROOT / path)
                spec.loader.exec_module(importlib.util.module_from_spec(spec))

    def test_dry_run_examples_complete(self):
        for name in ("full_loop.py", "production_adapter.py"):
            with self.subTest(name=name):
                proc = subprocess.run([sys.executable, str(ROOT / "hosts" / "generic" / name)],
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("DONE (dry-run)", proc.stdout)

    def test_template_reuses_the_pilots_ledger_between_dispatches(self):
        spec = importlib.util.spec_from_file_location(
            "host_template", ROOT / "hosts/generic/production_adapter.py")
        template = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(template)
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.jsonl"
            results = [template.dispatch("cloud-C", "same-task", "probe",
                                         shadow=True, ledger=ledger) for _ in range(3)]
            self.assertEqual([rc for rc, result in results], [0, 0, 1])
            self.assertEqual(results[-1][1]["decision"], "blocked-repair-cap")

    def test_route_runs(self):
        proc = subprocess.run([sys.executable, str(ROUTE)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Generic host adapter skeleton", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
