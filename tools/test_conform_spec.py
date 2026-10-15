#!/usr/bin/env python3
"""Tests for tools/conform_spec.py — the §10 conformance checker.

  K1. a complete Brief conforms; delegate-without-Brief is a VIOLATION (exit 1)
  K2. zero-check acceptance and invented isolation are VIOLATIONS (§12 evidence/lattice)
  K3. weaker-than-recommended isolation is a VIOLATION; equal/stronger conforms
  K4. SpeculativeSet requires candidates, shared-budget numbers, true winner-owns
  K5. Outcomes reuse the canonical §10.3 schema (bad outcome → VIOLATION)
  K6. NestedBrief without parent context is FAIL-CLOSED (exit 2), never assumed
  K7. NestedBrief wider than parent remaining allowance/deadline/effects/depth is
      a VIOLATION; a tighter one conforms
  K8. LedgerRecord enforces kind enum, seq floor, and repairs-used <= allowed
  K9. malformed JSON is FAIL-CLOSED, not a violation
Run as part of the regression gate (tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "conform_spec.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cs = _load("csp", TOOL)


def brief(**over) -> dict:
    doc = {"objective": "x", "acceptance": {"checks": [{"command": "pytest -q", "expect": "exit 0"}]},
           "sources": [], "permitted-effects": ["src/"], "non-goals": [],
           "isolation": "worktree+branch", "branch-hint": "sr/abc/test",
           "allowance": {"cash": 1.0, "calls": 4, "deadline": "2026-10-12T12:00:00Z"},
           "attempts": 1, "stop-triggers": [], "ownership": "worker",
           "nested-allowed": False, "max-nesting-depth": 1}
    doc.update(over)
    return doc


def write(tdp: Path, name: str, doc) -> Path:
    p = tdp / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def run(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *extra], capture_output=True,
                          text=True, timeout=60)


class Conform(unittest.TestCase):

    # K1 ----------------------------------------------------------------------
    def test_k1_brief_conforms_missing_is_violation(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            b = write(tdp, "b.json", brief())
            r = run("--route", "delegate", "--brief", str(b))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("CONFORMANT", r.stdout)
            r2 = run("--route", "delegate")
            self.assertEqual(r2.returncode, 1)
            self.assertIn("VIOLATION", r2.stderr)

    # K2 ----------------------------------------------------------------------
    def test_k2_empty_acceptance_and_invented_isolation(self):
        with self.assertRaises(cs.Violation):
            cs.check_brief(brief(acceptance={"checks": []}))
        with self.assertRaises(cs.Violation):
            cs.check_brief(brief(isolation="chroot-jail"))

    # K3 ----------------------------------------------------------------------
    def test_k3_weaker_isolation_violates(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            b = write(tdp, "b.json", brief(isolation="directory"))
            r = run("--route", "delegate", "--brief", str(b),
                    "--recommended-isolation", "worktree+branch")
            self.assertEqual(r.returncode, 1)
            self.assertIn("weaker", r.stderr)
            r2 = run("--route", "delegate", "--brief", str(b),
                     "--recommended-isolation", "directory")
            self.assertEqual(r2.returncode, 0)

    # K4 ----------------------------------------------------------------------
    def test_k4_speculative_set_rules(self):
        good = {"candidates": [{"profile": "p"}, {"profile": "q"}], "max-parallel": 2,
                "shared-budget": {"cash": 1.0, "calls": 4},
                "cancel-policy": "first-success", "winner-owns": True}
        cs.check_speculative(good)
        for bad in (dict(good, candidates=[]),
                    dict(good, **{"shared-budget": {"cash": -1.0, "calls": 4}}),
                    dict(good, **{"winner-owns": False}),
                    dict(good, **{"cancel-policy": "vibes"})):
            with self.assertRaises(cs.Violation):
                cs.check_speculative(bad)

    def test_nonfinite_allowance_and_typed_calls_are_refused(self):
        for cash in (float('nan'), float('inf'), -float('inf'), 10**1000):
            with self.subTest(cash_type=type(cash).__name__):
                with self.assertRaises(cs.Violation):
                    cs.check_brief(brief(allowance={"cash": cash, "calls": 2,
                                                  "deadline": "2030-01-01T00:00:00Z"}))
        for calls in (True, 1.5, -1):
            with self.assertRaises(cs.Violation):
                cs.check_brief(brief(allowance={"cash": 0.1, "calls": calls,
                                              "deadline": "2030-01-01T00:00:00Z"}))
        for allowance in (None, [], 1):
            with self.assertRaises(cs.Violation):
                cs.check_brief(brief(allowance=allowance))

    def test_speculation_requires_distinct_candidates_and_bounded_parallelism(self):
        good = {"candidates": [{"profile": "p"}, {"profile": "q"}], "max-parallel": 2,
                "shared-budget": {"cash": 0.4, "calls": 5},
                "cancel-policy": "first-success", "winner-owns": True}
        mutations = [{"candidates": [{"profile": "p"}]},
                     {"candidates": [{"profile": "p"}, {"profile": "p"}]},
                     {"candidates": [{"profile": ""}, {"profile": "q"}]},
                     {"candidates": [{"profile": "p", "weight": float('nan')},
                                     {"profile": "q"}]},
                     {"shared-budget": {"cash": float('nan'), "calls": 5}},
                     {"shared-budget": {"cash": 0.4, "calls": 1.5}}]
        mutations.extend({"max-parallel": p} for p in (None, True, 0, 1, 2.5, 3))
        for change in mutations:
            with self.subTest(change=change):
                with self.assertRaises(cs.Violation):
                    cs.check_speculative(dict(good, **change))

    def test_cli_rejects_nan_instead_of_claiming_conformance(self):
        with tempfile.TemporaryDirectory() as td:
            bad = brief(allowance={"cash": float('nan'), "calls": 2,
                                   "deadline": "2030-01-01T00:00:00Z"})
            result = run("--route", "delegate", "--brief", str(write(Path(td), "bad.json", bad)))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("VIOLATION", result.stderr)

    # K5 ----------------------------------------------------------------------
    def test_k5_outcome_uses_canonical_schema(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            good_out = {"task-id": "t", "outcome": "accepted",
                        "evidence": {"checks": [], "actual-spend": 0.0,
                                     "files-touched": [], "notes": ""},
                        "owner-profile": "worker"}
            r = run("--outcome", str(write(tdp, "o.json", good_out)))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            bad_out = dict(good_out, outcome="shipped")
            r2 = run("--outcome", str(write(tdp, "o2.json", bad_out)))
            self.assertEqual(r2.returncode, 1)
            self.assertIn("VIOLATION", r2.stderr)

    # K6 ----------------------------------------------------------------------
    def test_k6_nested_without_parent_fails_closed(self):
        nested = {"parent-task-id": "p", "parent-brief-fingerprint": "sha256:x",
                  "nesting-depth": 2, "max-nesting-depth": 2, "objective": "sub",
                  "acceptance": {"checks": [{"command": "t", "expect": "0"}]},
                  "permitted-effects": ["src/"], "non-goals": [],
                  "isolation": "worktree+branch",
                  "allowance": {"cash": 0.1, "calls": 1,
                                "deadline": "2026-10-12T11:00:00Z"},
                  "attempts": 1, "ownership": "parent-worker", "nested-allowed": False}
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            r = run("--nested", str(write(tdp, "n.json", nested)))
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("FAIL-CLOSED", r.stderr)

    # K7 ----------------------------------------------------------------------
    def _nested_ok(self) -> tuple[dict, dict, dict]:
        pb = brief(**{"nested-allowed": True, "max-nesting-depth": 2})
        nested = {"parent-task-id": "p", "parent-brief-fingerprint": "sha256:x",
                  "nesting-depth": 2, "max-nesting-depth": 2, "objective": "sub",
                  "acceptance": {"checks": [{"command": "t", "expect": "0"}]},
                  "permitted-effects": ["src/"], "non-goals": ["no nesting"],
                  "isolation": "worktree+branch",
                  "allowance": {"cash": 0.5, "calls": 2, "deadline": "2026-10-12T11:00:00Z"},
                  "attempts": 1, "ownership": "parent-worker", "nested-allowed": False}
        state = {"cash": 0.8, "calls": 3, "attempts": 1, "depth": 1}
        return nested, pb, state

    def test_k7_tighter_nest_conforms_wider_violates(self):
        nested, pb, state = self._nested_ok()
        cs.check_nested(nested, pb, state)  # must not raise
        for mutate in (lambda n: n["allowance"].update(cash=9.0),
                       lambda n: n["allowance"].update(deadline="2026-10-13T00:00:00Z"),
                       lambda n: n.update(**{"permitted-effects": ["/etc"]}),
                       lambda n: n.update(isolation="directory"),
                       lambda n: n.update(ownership="worker"),
                       lambda n: n.update(**{"nested-allowed": True})):
            bad = json.loads(json.dumps(nested))
            mutate(bad)
            with self.subTest(mutate=str(mutate)):
                with self.assertRaises(cs.Violation):
                    cs.check_nested(bad, pb, state)

    def test_brief_and_nested_share_typed_acceptance_validation(self):
        nested, pb, state = self._nested_ok()
        for acceptance in (None, [], {"checks": []}, {"checks": {}},
                           {"checks": [None]},
                           {"checks": [{"command": 3, "expect": "0"}]},
                           {"checks": [{"command": "t", "expect": False}]},
                           {"checks": [{"command": " ", "expect": "0"}]}):
            with self.subTest(acceptance=acceptance):
                with self.assertRaises(cs.Violation):
                    cs.check_brief(brief(acceptance=acceptance))
                with self.assertRaises(cs.Violation):
                    cs.check_nested(dict(nested, acceptance=acceptance), pb, state)

    def test_nested_rejects_malformed_allowance_and_exact_integer_fields(self):
        nested, pb, state = self._nested_ok()
        for key, values in (("cash", [-1, True, float('nan'), float('inf'), 10**1000]),
                            ("calls", [-1, True, 1.5])):
            for value in values:
                with self.subTest(key=key, value_type=type(value).__name__):
                    bad = copy.deepcopy(nested)
                    bad["allowance"][key] = value
                    with self.assertRaises(cs.Violation):
                        cs.check_nested(bad, pb, state)
        for allowance in (None, [], {}, {"cash": 0.1, "calls": 1}):
            with self.assertRaises(cs.Violation):
                cs.check_nested(dict(nested, allowance=allowance), pb, state)
        for key in ("attempts", "nesting-depth", "max-nesting-depth"):
            for value in (True, 1.5, -1, "2"):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(cs.Violation):
                        cs.check_nested(dict(nested, **{key: value}), pb, state)
        for key in ("permitted-effects", "non-goals"):
            for value in (None, "src/", [5]):
                with self.assertRaises(cs.Violation):
                    cs.check_nested(dict(nested, **{key: value}), pb, state)
        for key in ("parent-task-id", "parent-brief-fingerprint", "objective"):
            for value in (None, 5, " "):
                with self.assertRaises(cs.Violation):
                    cs.check_nested(dict(nested, **{key: value}), pb, state)

    def test_nested_deadline_compares_instants_and_requires_timezone(self):
        nested, pb, state = self._nested_ok()
        pb["allowance"]["deadline"] = "2030-01-01T10:00:00+00:00"
        # 09:30 at -02:00 is 11:30 UTC, despite sorting before the parent's text.
        nested["allowance"]["deadline"] = "2030-01-01T09:30:00-02:00"
        with self.assertRaisesRegex(cs.Violation, "deadline past"):
            cs.check_nested(nested, pb, state)
        # 11:00 at +02:00 is 09:00 UTC, despite sorting after the parent's text.
        nested["allowance"]["deadline"] = "2030-01-01T11:00:00+02:00"
        cs.check_nested(nested, pb, state)
        nested["allowance"]["deadline"] = "2030-01-01T10:00:00Z"
        cs.check_nested(nested, pb, state)  # equal instants are permitted
        for deadline in ("2030-01-01T09:00:00", "2030-01-01", None, "soon"):
            nested["allowance"]["deadline"] = deadline
            with self.assertRaises(cs.Violation):
                cs.check_nested(nested, pb, state)
        nested["allowance"]["deadline"] = "2030-01-01T09:00:00Z"
        pb["allowance"]["deadline"] = "2030-01-01T10:00:00"
        with self.assertRaisesRegex(cs.Violation, "timezone"):
            cs.check_nested(nested, pb, state)

    def test_nested_cannot_omit_parent_limits_or_permission(self):
        nested, pb, state = self._nested_ok()
        pb["non-goals"] = ["no database writes"]
        with self.assertRaisesRegex(cs.Violation, "non-goals"):
            cs.check_nested(nested, pb, state)
        nested["non-goals"].append("no database writes")
        cs.check_nested(nested, pb, state)
        for change in ({"nested-allowed": False}, {"max-nesting-depth": 1}):
            with self.assertRaises(cs.Violation):
                cs.check_nested(nested, dict(pb, **change), state)

    def test_nested_parent_remaining_state_is_required_and_validated(self):
        nested, pb, state = self._nested_ok()
        for key in ("cash", "calls", "attempts"):
            bad = dict(state)
            del bad[key]
            with self.assertRaises(cs.FailClosed):
                cs.check_nested(nested, pb, bad)
        for key, values in (("cash", [-1, True, float('nan'), float('inf'), 2.0]),
                            ("calls", [-1, True, 1.5, 5]),
                            ("attempts", [-1, True, 1.5, 2]),
                            ("depth", [-1, 0, True, 1.5])):
            for value in values:
                with self.subTest(key=key, value_type=type(value).__name__):
                    with self.assertRaises(cs.FailClosed):
                        cs.check_nested(nested, pb, dict(state, **{key: value}))
        for bad in ([], "state", 1):
            with self.assertRaises(cs.FailClosed):
                cs.check_nested(nested, pb, bad)
        for key in ("cash", "calls", "attempts"):
            with self.assertRaises(cs.Violation):
                cs.check_nested(nested, pb, dict(state, **{key: 0}))

    def test_nested_malformed_contract_exits_as_violation(self):
        nested, pb, state = self._nested_ok()
        nested["allowance"] = None
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            result = run("--nested", str(write(tdp, "nested.json", nested)),
                         "--parent-brief", str(write(tdp, "parent.json", pb)),
                         "--parent-state", str(write(tdp, "state.json", state)))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("VIOLATION", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    # K8 ----------------------------------------------------------------------
    def test_k8_ledger_record_bounds(self):
        rec = {"task-id": "t", "seq": 2, "kind": "dispatch", "ts": "2026-10-12T10:00:00Z",
               "profile": "(h, p, m@r, c)",
               "counters": {"calls-used": 1, "calls-limit": 4, "cash-spent": 0.02,
                            "cash-cap": 1.0, "repairs-used": 0, "repairs-allowed": 1},
               "deadline": "2026-10-12T12:00:00Z", "brief-fingerprint": "sha256:x",
               "detail": "attempt 1", "outcome-ref": None}
        cs.check_record(rec)
        for key, val in (("kind", "vibes"), ("seq", 0),
                         ("repairs-used", 2), ("ts", "soon")):
            bad = json.loads(json.dumps(rec))
            if key == "repairs-used":
                bad["counters"][key] = val
            else:
                bad[key] = val
            with self.subTest(**{key: val}):
                with self.assertRaises(cs.Violation):
                    cs.check_record(bad)

    def test_record_discrete_counters_are_exact_nonnegative_integers(self):
        rec = {"task-id": "t", "seq": 1, "kind": "spend", "ts": "2030-01-01T00:00:00Z",
               "counters": {"calls-used": 0, "calls-limit": 0, "cash-spent": 0.025,
                            "cash-cap": 1.5, "repairs-used": 0, "repairs-allowed": 0},
               "detail": ""}
        cs.check_record(rec)  # zero discrete counts and fractional money are valid
        for key in ("calls-used", "calls-limit", "repairs-used", "repairs-allowed"):
            for value in (True, False, 0.0, 0.5, -1, "1", None):
                bad = copy.deepcopy(rec)
                bad["counters"][key] = value
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(cs.Violation, "non-negative integer"):
                        cs.check_record(bad)
            bad = copy.deepcopy(rec)
            del bad["counters"][key]
            with self.assertRaises(cs.Violation):
                cs.check_record(bad)
        for key in ("cash-spent", "cash-cap"):
            for value in (True, -0.01, float('nan'), float('inf'), 10**1000):
                bad = copy.deepcopy(rec)
                bad["counters"][key] = value
                with self.subTest(key=key, value_type=type(value).__name__):
                    with self.assertRaisesRegex(cs.Violation, "finite non-negative"):
                        cs.check_record(bad)

    def test_record_malformed_shapes_exit_as_violations(self):
        rec = {"task-id": "t", "seq": 1, "kind": "spend", "ts": "2030-01-01T00:00:00Z",
               "counters": {"calls-used": 0, "calls-limit": 1, "cash-spent": 0,
                            "cash-cap": 1, "repairs-used": 0, "repairs-allowed": 1},
               "detail": "synthetic"}
        for key, values in (("counters", [None, [], "counts", 1]),
                            ("task-id", [None, [], 1, " "]),
                            ("detail", [None, {}, 1])):
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(cs.Violation):
                        cs.check_record(dict(rec, **{key: value}))
        for value in (None, [], "record"):
            with self.assertRaises(cs.Violation):
                cs.check_record(value)
        with tempfile.TemporaryDirectory() as td:
            bad = dict(rec, counters=None)
            result = run("--record", str(write(Path(td), "record.json", bad)))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("VIOLATION", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    # K9 ----------------------------------------------------------------------
    def test_k9_malformed_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "b.json"
            bad.write_text("{ not json", encoding="utf-8")
            r = run("--brief", str(bad))
            self.assertEqual(r.returncode, 2)
            self.assertIn("FAIL-CLOSED", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
