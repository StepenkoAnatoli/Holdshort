#!/usr/bin/env python3
"""Smoke test for hosts/generic/route.py."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "hosts" / "generic" / "route.py"


class GenericHostSmoke(unittest.TestCase):
    def test_route_runs(self):
        proc = subprocess.run([sys.executable, str(ROUTE)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Generic host adapter skeleton", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
PY