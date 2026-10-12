#!/usr/bin/env python3
"""Gate wrapper for tests/docs_drift.py — the background-docs-to-spec-v2 pin.

  F0. the live skills/ tree is pinned (zero findings on the real docs)
  F1. an invented HumanGate value in a fixture doc is caught
  F2. a decision block missing §9 keys without an abbreviation note is caught
  F3. a branch example with a non-hex id is caught
  F4. a SMARTROUTER_BRIEF.json mention without the convention note is caught
  F5. template forms (`<a | b>`, `...` slugs) do NOT trip the check
Run as part of the regression gate (tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dd = _load("ddocs", REPO / "tests" / "docs_drift.py")


def fixture(root: Path, name: str, body: str) -> None:
    (root / name).write_text(body, encoding="utf-8")


class DocsDrift(unittest.TestCase):

    # F0 ----------------------------------------------------------------------
    def test_f0_live_tree_pinned(self):
        self.assertEqual(dd.check(), [], "the shipped docs must match spec-v2")

    # F1 ----------------------------------------------------------------------
    def test_f1_invented_humangate_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root, "a.md", "# t\n\n```\nDifficulty:  trivial\nRoute:       direct\n"
                    "Profile:     p\nIsolation:   none\nIsolationReason: x\nOwner: o\n"
                    "HumanGate:   auto-merge-whenever\nNestedAllowed: no\nMaxNestingDepth: 1\n"
                    "Reservations: 0\nCalls: 0/1\nDeadline: t\nUncertainty: []\n```\n")
            found = dd.check(root)
        self.assertTrue(any("HumanGate" in f for f in found), found)

    # F2 ----------------------------------------------------------------------
    def test_f2_abbreviated_block_without_note_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root, "b.md", "# t\n\n```\nDifficulty: trivial\nRoute: direct\n```\n")
            found = dd.check(root)
        self.assertTrue(any("missing" in f for f in found), found)

    # F3 ----------------------------------------------------------------------
    def test_f3_bad_branch_id_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root, "c.md", "# t\n\nbranch `sr/ZZZ/not-hex` here\n")
            found = dd.check(root)
        self.assertTrue(any("branch example" in f for f in found), found)

    # F4 ----------------------------------------------------------------------
    def test_f4_brief_filename_without_convention_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root, "d.md", "# t\n\nwrite SMARTROUTER_BRIEF.json there\n")
            found = dd.check(root)
        self.assertTrue(any("convention" in f for f in found), found)

    # F5 ----------------------------------------------------------------------
    def test_f5_templates_do_not_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root, "e.md", "# t\n\n```\nRoute: <direct | delegate>\n```\n\n"
                    "branch `sr/<task-id>/<slug>` and `sr/9d4e2f1a/...`\n")
            self.assertEqual(dd.check(root), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
