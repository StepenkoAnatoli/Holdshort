#!/usr/bin/env python3
"""Tests for the task-state owner (ADR-0001, migration step 1).

The ADR-0001 rules under test: the authority wins every read; a valid stale
mirror never lowers it; a corrupt mirror still refuses the task (G5, fail
loud, file preserved); the repairs/repairs_used vocabulary mapping lives in
the owner and nowhere else; reconcile() reports disagreement as findings, not
verdicts; reads observe no state change a later reader could notice. Hermetic:
temp dirs, synthetic now_fn, no network.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(TOOLS))

import dataclasses as _dc  # noqa: F401 — ensure module present before exec


def _load(name: str):
    """Load a module under its PLAIN name, registered before exec, so every
    dependent module shares one instance (exception identity matters here)."""
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tp = _load("task_persistence")
db = _load("dispatch_budget")
hw = _load("host_watchdog")
ld = _load("live_dispatcher")
tso = _load("task_state_owner")

PRICES = json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8"))

IN = [{"tokens": 10000, "cache_read": 0, "cache_write": 0}]
OUT = [{"tokens": 1000, "cache_write": 0}]
_C = PRICES["profiles"]["cloud-C"]
COST = 10000 / 1e6 * _C["input_rate_per_mtok"] + \
    1000 / 1e6 * _C["output_rate_per_mtok"]


class OwnerCase(unittest.TestCase):
    clock: list = []
    tmp: Path
    d: ld.LiveDispatcher
    owner: tso.TaskStateOwner
    wd: Path

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="owner-"))
        self.clock = [1760000000.0]
        self.d = ld.LiveDispatcher(
            PRICES, self.tmp / "ledger.jsonl",
            now_fn=lambda: self.clock[0],
            task_store=self.tmp / "task_state")
        self.wd = self.tmp / "watchdog.json"
        self.owner = tso.TaskStateOwner(
            self.d.budget,
            mirror=tp.TaskStateStore(self.tmp / "task_state"),
            watchdog_state_path=self.wd)

    def dispatch(self, task_id: str = "L-1", profile: str = "cloud-C") -> object:
        # Counter-only fixture: required checks are local, with no model slots
        # (the same shape tools/test_task_persistence.py uses).
        e = self.d.attempt(task_id, profile, "req", work_bound=0.01,
                           review_bound=0.01, expected_in=10000,
                           expected_out=1000, review_calls=0)
        self.assertEqual(e.decision, "dispatched")
        self.clock[0] += 1.0
        return e

    def read_mirror_doc(self, task_id: str) -> dict:
        return json.loads(
            (self.tmp / "task_state" / f"{task_id}.json").read_text(encoding="utf-8"))


class TestRead(OwnerCase):
    def test_unknown_task_is_none(self):
        self.assertIsNone(self.owner.read("L-404"))

    def test_read_returns_the_authority_record(self):
        self.dispatch()
        view = self.owner.read("L-1")
        self.assertIsNotNone(view)
        self.assertEqual(view["task_id"], "L-1")
        self.assertEqual(view["attempts"], 1)
        self.assertEqual(view["repairs"], 0)
        self.assertEqual(view["last_profile"], "cloud-C")
        self.assertFalse(view["verified"])
        self.assertAlmostEqual(view["spent"], COST, places=9)

    def test_read_maps_charged_to_spent_like_the_mirror(self):
        # The mapping must reproduce byte-for-byte what the dispatcher already
        # persists: owner read spent == on-disk mirror spent.
        self.dispatch()
        view = self.owner.read("L-1")
        mirror = self.owner.read_mirror("L-1")
        self.assertEqual(view["spent"], mirror["spent"])
        self.assertEqual(view["spent"], float(db.money(view["charged"])))

    def test_invalid_task_id_refused(self):
        for bad in ("", "   ", None, 7):
            with self.assertRaises(ValueError):
                self.owner.read(bad)

    def test_optional_stores_absent_is_fine(self):
        self.dispatch()
        bare = tso.TaskStateOwner(self.d.budget)
        view = bare.read("L-1")
        self.assertEqual(view["attempts"], 1)
        self.assertIsNone(bare.read_mirror("L-1"))
        self.assertIsNone(bare.read_watchdog("L-1"))

    def test_corrupt_mirror_refuses_read_and_is_preserved(self):  # G5
        self.dispatch()
        path = self.tmp / "task_state" / "L-1.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(tp.CorruptState):
            self.owner.read("L-1")
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_stale_mirror_never_lowers_the_authority(self):
        self.dispatch()
        self.dispatch()
        # Valid-but-old mirror: attempts/repairs pass the validator's checks.
        store = tp.TaskStateStore(self.tmp / "task_state")
        doc = store.load("L-1")
        doc["attempts"] = 1
        doc["repairs"] = 0
        doc["spent"] = 0.0
        store.save(doc)
        view = self.owner.read("L-1")
        self.assertEqual(view["attempts"], 2)  # authority wins
        self.assertAlmostEqual(view["spent"], 2 * COST, places=9)


class TestReconcile(OwnerCase):
    def test_consistent_stores_yield_no_findings(self):
        self.dispatch()
        hw.save_state(self.wd, {
            "task_id": "L-1", "attempts": 1, "repairs_used": 0,
            "history": [{"outcome": "success", "ts": 1.0, "elapsed_s": 1.0,
                         "log_tail": ""}]})
        result = self.owner.reconcile("L-1")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["authority"]["attempts"], 1)
        self.assertEqual(result["mirror"]["attempts"], 1)
        self.assertEqual(result["watchdog"]["repairs"], 0)  # mapped
        self.assertNotIn("repairs_used", result["watchdog"])  # one vocabulary

    def test_mirror_ahead_is_a_finding(self):
        self.dispatch()
        store = tp.TaskStateStore(self.tmp / "task_state")
        doc = store.load("L-1")
        doc["attempts"] = 9
        doc["repairs"] = 0
        store.save(doc)
        result = self.owner.reconcile("L-1")
        self.assertIn("mirror-ahead-of-authority",
                      [f["kind"] for f in result["findings"]])
        # ...but the read itself still reports the authority's number.
        self.assertEqual(result["authority"]["attempts"], 1)

    def test_mirror_without_authority_is_a_finding(self):
        # The drift scenario from issue #81: an authority exists (here for
        # L-1) but the mirror carries counters for a task it never saw.
        self.dispatch()  # create the authority so it is not a bare legacy ledger
        tp.TaskStateStore(self.tmp / "task_state").save({
            "task_id": "L-9", "attempts": 2, "spent": 1.0, "started": 1,
            "repairs": 0, "last_profile": "cloud-C"})
        result = self.owner.reconcile("L-9")
        self.assertIsNone(result["authority"])
        self.assertIn("mirror-without-authority",
                      [f["kind"] for f in result["findings"]])

    def test_bare_mirror_without_any_authority_fails_closed(self):
        # #72's rule, upstream of the owner: a legacy mirror with counters and
        # no authority is unreconciled — the authority refuses before reads.
        tp.TaskStateStore(self.tmp / "task_state").save({
            "task_id": "L-9", "attempts": 2, "spent": 1.0, "started": 1,
            "repairs": 0, "last_profile": "cloud-C"})
        with self.assertRaises(db.BudgetStateError):
            self.owner.read("L-9")

    def test_watchdog_ahead_is_informational_not_an_error(self):
        # Watchdog counts host launches, authority counts dispatches: they can
        # legitimately differ, so this is a finding, never an exception.
        self.dispatch()
        # A valid on-disk watchdog state (host_watchdog enforces attempts ==
        # len(history) and repairs_used <= the single-repair allowance): two
        # failed launches, one repair consumed — ahead of the authority's one
        # dispatch / zero repairs, which is a finding, not an error.
        hw.save_state(self.wd, {
            "task_id": "L-1", "attempts": 2, "repairs_used": 1,
            "history": [
                {"outcome": "failed", "ts": 1.0, "elapsed_s": 1.0, "log_tail": "",
                 "failing_tests": ["t_a"], "diff_hash": "h1", "error": "boom-1"},
                {"outcome": "failed", "ts": 2.0, "elapsed_s": 1.0, "log_tail": "",
                 "failing_tests": ["t_b"], "diff_hash": "h2", "error": "boom-2"},
            ]})
        result = self.owner.reconcile("L-1")
        kinds = [f["kind"] for f in result["findings"]]
        self.assertIn("watchdog-attempts-ahead", kinds)
        self.assertIn("watchdog-repairs-ahead", kinds)
        self.assertTrue(any("may be legitimate" in f["detail"]
                            for f in result["findings"]))

    def test_unreadable_watchdog_fails_loud_and_is_preserved(self):
        self.dispatch()
        self.wd.write_text("{broken", encoding="utf-8")
        with self.assertRaises(tso.WatchdogStateUnreadable):
            self.owner.read_watchdog("L-1")
        with self.assertRaises(tso.WatchdogStateUnreadable):
            self.owner.reconcile("L-1")
        self.assertEqual(self.wd.read_text(encoding="utf-8"), "{broken")

    def test_reads_observe_no_state_change(self):
        self.dispatch()
        ledger = (self.tmp / "ledger.jsonl").read_text(encoding="utf-8")
        mirror = (self.tmp / "task_state" / "L-1.json").read_text(encoding="utf-8")
        first = self.owner.reconcile("L-1")
        second = self.owner.reconcile("L-1")
        self.assertEqual(first, second)
        self.assertEqual((self.tmp / "ledger.jsonl").read_text(encoding="utf-8"),
                         ledger)
        self.assertEqual(
            (self.tmp / "task_state" / "L-1.json").read_text(encoding="utf-8"),
            mirror)


if __name__ == "__main__":
    unittest.main(verbosity=2)
