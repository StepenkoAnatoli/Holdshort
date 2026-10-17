#!/usr/bin/env python3
"""hosts/claude-code: the adapter's committed artifacts are well-formed and its Briefs conform to §10.1.

The adapter itself is Node (route.mjs, run with `node --test hosts/claude-code/route.test.mjs`); this
repository's gate has no Node step, so this check covers what Python can: the host policy parses and names
the blocks the README documents, every decision file carries a Brief that `tools/conform_spec.py` accepts,
and the ledger is one JSON object per line with the §10.5 keys and a strictly increasing `seq` per task.
Cash fields are allowed to be null here only because the adapter marks its accounting estimate-only (see
docs/proposals/usage-windows-gate4.md, Item 4); conform_spec's own record check is not relaxed.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "hosts" / "claude-code"
sys.path.insert(0, str(ROOT / "tools"))
import conform_spec  # noqa: E402

LEDGER_KEYS = {"task-id", "seq", "kind", "ts", "profile", "counters", "deadline", "brief-fingerprint", "detail", "outcome-ref"}
KINDS = {"decision", "dispatch", "outcome", "spend", "escalation"}
COUNTER_KEYS = {"calls-used", "calls-limit", "cash-spent", "cash-cap", "repairs-used", "repairs-allowed"}


class HostArtifacts(unittest.TestCase):
    def test_policy_parses_and_names_its_blocks(self):
        policy = json.loads((HOST / "host-policy.json").read_text(encoding="utf-8"))
        for key in ("policy-revision", "harness", "authorization", "isolation", "accounting", "prices", "categories", "profiles", "economics"):
            self.assertIn(key, policy, key)
        self.assertEqual(policy["accounting"]["mode"], "estimate-only")
        ids = [p["id"] for p in policy["profiles"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate profile id")
        self.assertIn(policy["economics"]["lead-direct-profile"], ids)

    def test_every_decision_brief_conforms(self):
        files = sorted((HOST / "trace" / "decisions").glob("*.json"))
        self.assertTrue(files, "no decision files")
        checked = 0
        for f in files:
            doc = json.loads(f.read_text(encoding="utf-8"))
            if "brief" not in doc or doc.get("decision", {}).get("route") not in ("delegate", "speculative"):
                continue
            conform_spec.check_brief(doc["brief"])  # raises on a §10.1 breach
            checked += 1
        self.assertGreater(checked, 0, "no delegate decision with a Brief")

    def test_ledger_lines_are_records_with_monotonic_seq(self):
        text = (HOST / "trace" / "ledger.jsonl").read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"), "ledger must end with a newline (the adapter refuses to append otherwise)")
        last = {}
        for n, line in enumerate(text.splitlines(), 1):
            rec = json.loads(line)
            self.assertTrue(LEDGER_KEYS <= set(rec), f"line {n}: missing {LEDGER_KEYS - set(rec)}")
            self.assertIn(rec["kind"], KINDS, f"line {n}")
            self.assertTrue(COUNTER_KEYS <= set(rec["counters"]), f"line {n}")
            self.assertIsInstance(rec["seq"], int)
            self.assertGreater(rec["seq"], last.get(rec["task-id"], 0), f"line {n}: seq not increasing for {rec['task-id']}")
            last[rec["task-id"]] = rec["seq"]
            for k in ("calls-used", "calls-limit", "repairs-used", "repairs-allowed"):
                self.assertIsInstance(rec["counters"][k], int, f"line {n}: {k}")
            for k in ("cash-spent", "cash-cap"):
                v = rec["counters"][k]
                self.assertTrue(v is None or (isinstance(v, (int, float)) and v >= 0), f"line {n}: {k}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
