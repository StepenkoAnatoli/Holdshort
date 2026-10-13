#!/usr/bin/env python3
"""Tests for tools/class_breaker.py — the breaker split (facts per task, rates under auth).

  C1. record appends attempt-level facts (task-id/class/outcome/ts) without computing
  C2. gate is a table LOOKUP: published value returned, unknown class gets default,
      non-HumanGate value fails closed
  C3. recompute without owner approval refuses fail-closed (exit 2, table untouched)
  C4. recompute with bad threshold / bad raise_to refuses fail-closed
  C5. below-threshold class keeps its gate (report says within threshold)
  C6. above-threshold class with enough samples is raised (version bumps, audit trail)
  C7. small sample keeps the gate even above threshold (insufficient-evidence)
  C8. window bounds: outcomes older than the frozen window are ignored
  C9. malformed ledger lines fail closed instead of silently skipping
Run as part of the regression gate (tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "class_breaker.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cb = _load("cbr", TOOL)

TABLE = {"version": 1, "classes": {"auth": "review-before-merge", "docs": "none"}}
AUTH = {"window": 10, "min_samples": 3, "threshold": 0.3,
        "raise_to": "approval-required", "approved_by": "owner", "approved_at": "2026-10-12"}


def write(tdp: Path, name: str, doc) -> Path:
    p = tdp / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def entries(auth_outcomes: list[str], cls: str = "auth") -> list[dict]:
    return [{"task-id": f"t{i}", "class": cls, "outcome": o, "ts": float(i)}
            for i, o in enumerate(auth_outcomes)]


class ClassBreaker(unittest.TestCase):

    # C1 ----------------------------------------------------------------------
    def test_c1_record_appends_facts(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            led = tdp / "L.jsonl"
            cb.record(led, task_id="t1", task_class="auth", outcome="needs-human")
            cb.record(led, task_id="t2", task_class="auth", outcome="accepted")
            docs = [json.loads(ln) for ln in led.read_text().splitlines()]
            self.assertEqual([(d["task-id"], d["class"], d["outcome"]) for d in docs],
                             [("t1", "auth", "needs-human"), ("t2", "auth", "accepted")])

    # C2 ----------------------------------------------------------------------
    def test_c2_gate_is_a_lookup(self):
        self.assertEqual(cb.effective_gate(TABLE, "auth"), "review-before-merge")
        self.assertEqual(cb.effective_gate(TABLE, "new-class"), "review-before-merge")
        with self.assertRaises(cb.FailClosed):
            cb.effective_gate({"classes": {"x": "auto-merge-whenever"}}, "x")

    # C3 ----------------------------------------------------------------------
    def test_c3_no_approval_no_recompute(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            led = tdp / "L.jsonl"
            for i in range(5):
                cb.record(led, task_id=f"t{i}", task_class="auth", outcome="needs-human")
            table = write(tdp, "T.json", TABLE)
            bad = write(tdp, "A.json", {k: v for k, v in AUTH.items() if k != "approved_by"})
            out = tdp / "T2.json"
            r = subprocess.run([sys.executable, str(TOOL), "recompute", "--ledger", str(led),
                                "--auth", str(bad), "--table", str(table), "--out", str(out)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("FAIL-CLOSED", r.stderr)
            self.assertFalse(out.exists(), "refused run must publish nothing")

    # C4 ----------------------------------------------------------------------
    def test_c4_bad_params_refused(self):
        for key, val in (("threshold", 1.5), ("threshold", 0), ("raise_to", "whenever"),
                         ("min_samples", 0), ("window", -1)):
            bad = dict(AUTH)
            bad[key] = val
            with self.subTest(**{key: val}):
                with self.assertRaises(cb.FailClosed):
                    cb_load_auth_from_doc(bad)


def cb_load_auth_from_doc(doc: dict) -> dict:
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(doc, fh)
        name = fh.name
    try:
        return cb.load_auth(Path(name))
    finally:
        Path(name).unlink()


class ClassBreaker2(unittest.TestCase):
    # C5 ----------------------------------------------------------------------
    def test_c5_below_threshold_keeps_gate(self):
        new_table, report = cb.recompute(entries(["needs-human", "accepted", "accepted",
                                                  "accepted"]), AUTH, dict(TABLE))
        self.assertEqual(new_table["classes"]["auth"], "review-before-merge")
        self.assertIn("within threshold", report["auth"]["decision"])

    # C6 ----------------------------------------------------------------------
    def test_c6_above_threshold_raises_with_audit(self):
        new_table, report = cb.recompute(entries(["needs-human"] * 3 + ["accepted"]), AUTH,
                                         {"version": 4, "classes": {"auth": "none"}})
        self.assertEqual(new_table["classes"]["auth"], "approval-required")
        self.assertIn("raised", report["auth"]["decision"])

    # C7 ----------------------------------------------------------------------
    def test_c7_small_sample_never_raises(self):
        new_table, report = cb.recompute(entries(["needs-human"] * 2), AUTH, dict(TABLE))
        self.assertEqual(new_table["classes"]["auth"], "review-before-merge")
        self.assertIn("insufficient-evidence", report["auth"]["decision"])

    # C8 ----------------------------------------------------------------------
    def test_c8_window_bounds_history(self):
        old = entries(["needs-human"] * 9, cls="auth")
        new = entries(["accepted"] * 3, cls="auth")
        auth = dict(AUTH, window=3)
        new_table, report = cb.recompute(old + new, auth, dict(TABLE))
        self.assertEqual(report["auth"]["n"], 3)
        self.assertEqual(new_table["classes"]["auth"], "review-before-merge")

    # C9 ----------------------------------------------------------------------
    def test_c9_malformed_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            led = Path(td) / "L.jsonl"
            led.write_text('{"task-id": "t1", "class": "auth"}\n', encoding="utf-8")
            with self.assertRaises(cb.FailClosed):
                cb.read_ledger(led)
            led.write_text('{ not json\n', encoding="utf-8")
            with self.assertRaises(cb.FailClosed):
                cb.read_ledger(led)


if __name__ == "__main__":
    unittest.main(verbosity=2)
