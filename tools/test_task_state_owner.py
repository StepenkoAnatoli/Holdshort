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
import os
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
tcx = _load("task_crosscheck")  # shared finding vocabulary (Appendix B.2)

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

    def test_unknown_task_on_a_new_pilot_creates_no_authority(self):
        # A read must not bring the authority into existence: the old
        # transaction()-based read created it as a side effect.
        self.assertFalse(self.d.budget.path.exists())
        self.assertIsNone(self.owner.read("L-404"))
        self.assertFalse(self.d.budget.path.exists(),
                         "a read must not create the budget authority")

    def test_read_does_not_write_the_authority(self):
        # The old read path went through BudgetStore.transaction(), which
        # rewrote the authority row on every read. read_authority() is a
        # read-only snapshot: the file is untouched (ADR-0001 Appendix B.1).
        self.dispatch()
        path = self.d.budget.path
        before = os.stat(path).st_mtime_ns
        self.assertIsNotNone(self.owner.read("L-1"))
        self.assertEqual(os.stat(path).st_mtime_ns, before,
                         "owner.read must not rewrite the authority row")

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
        # shared vocabulary: the crosscheck's kind for this divergence
        finding = next(f for f in result["findings"]
                       if f["kind"] == "optional-mirror-stale")
        self.assertEqual(finding["task_id"], "L-1")  # crosscheck finding shape
        # ...but the read itself still reports the authority's number.
        self.assertEqual(result["authority"]["attempts"], 1)

    def test_lagging_mirror_is_a_finding_and_never_lowers_the_read(self):
        # The crosscheck reports ANY difference, including a lagging mirror;
        # sharing the vocabulary means the owner does too. It stays a report,
        # not a verdict: the read still returns the authority's numbers.
        self.dispatch()
        self.dispatch()
        store = tp.TaskStateStore(self.tmp / "task_state")
        doc = store.load("L-1")
        doc["attempts"] = 1
        doc["repairs"] = 0
        doc["spent"] = 0.0
        store.save(doc)
        result = self.owner.reconcile("L-1")
        self.assertIn("optional-mirror-stale",
                      [f["kind"] for f in result["findings"]])
        self.assertEqual(result["authority"]["attempts"], 2)  # authority wins
        self.assertEqual(result["mirror"]["attempts"], 1)     # mirror shown as-is

    def test_mirror_finding_kind_matches_the_crosscheck(self):
        # Appendix B.2: one name for one divergence, not two vocabularies.
        self.dispatch()
        store = tp.TaskStateStore(self.tmp / "task_state")
        doc = store.load("L-1")
        doc["attempts"] = 9
        doc["repairs"] = 0
        store.save(doc)
        owner_kinds = {f["kind"] for f in self.owner.reconcile("L-1")["findings"]}
        self.assertIn("optional-mirror-stale", owner_kinds)
        cross = tcx.check(self.tmp / "task_state", PRICES, [],
                          ledger_path=self.d.ledger_path)
        cross_kinds = {f["kind"] for f in cross["findings"]}
        self.assertIn("optional-mirror-stale", cross_kinds)

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


class TestWiring(OwnerCase):
    """Step two — the dispatcher's _task/_remember delegate to the owner.

    ADR-0001: the dispatcher's read path is the owner; creation stays in the
    dispatcher (a write). The corrupt-mirror G5 refusal and the
    counters-without-authority refusal are preserved exactly.
    """

    def authority_task(self, task_id: str) -> dict:
        with self.d.budget.transaction() as doc:
            return dict(doc["tasks"][task_id])

    def test_remember_uses_the_single_mapping(self):
        self.dispatch()
        st = self.d._task("L-1")
        self.assertEqual(st, tso.authority_view(self.authority_task("L-1")))
        self.assertEqual(st["spent"], float(db.money(st["charged"])))

    def test_read_matches_the_single_mapping(self):
        self.dispatch()
        self.assertEqual(self.owner.read("L-1"),
                         tso.authority_view(self.authority_task("L-1")))

    def test_task_creates_an_absent_task(self):
        # Creation stays in the dispatcher (owner v1 is read-only).
        st = self.d._task("L-NEW")
        self.assertEqual(st["attempts"], 0)
        self.assertEqual(st["spent"], 0.0)
        self.assertIsNotNone(self.owner.read("L-NEW"))

    def test_corrupt_mirror_still_refuses_through_task(self):  # G5
        self.dispatch()
        path = self.tmp / "task_state" / "L-1.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(tp.CorruptState):
            self.d._task("L-1")
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_mirror_counters_without_authority_still_refuse(self):
        self.dispatch()  # authority exists, so this is not a bare legacy ledger
        tp.TaskStateStore(self.tmp / "task_state").save({
            "task_id": "L-9", "attempts": 2, "spent": 1.0, "started": 1,
            "repairs": 0, "last_profile": "cloud-C"})
        with self.assertRaises(db.BudgetStateError):
            self.d._task("L-9")

    def test_task_and_remember_keep_the_mirror_current(self):
        self.dispatch()
        self.assertEqual(self.read_mirror_doc("L-1")["attempts"],
                         self.d._task("L-1")["attempts"])

    def test_task_read_does_not_write_the_authority(self):
        # The delegated read must inherit step-1's read-only guarantee.
        self.dispatch()
        path = self.d.budget.path
        before = os.stat(path).st_mtime_ns
        self.d._task("L-1")
        self.assertEqual(os.stat(path).st_mtime_ns, before,
                         "_task's read must not rewrite the authority row")

    def test_task_creation_never_overwrites_a_concurrently_created_task(self):
        # Deterministic interleaving of the check-then-create race: our read
        # (outside the lock) sees the task absent, then a concurrent creator
        # adds it with counters before our transaction opens. The existence
        # check must be repeated inside the transaction, or the winner's
        # attempts and charge are reset to zero.
        self.dispatch()
        self.dispatch()  # the concurrent winner: attempts 2, charged 2*COST
        real_read = self.d.owner.read
        calls = {"n": 0}

        def stale_read(task_id):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_read(task_id)

        self.d.owner.read = stale_read           # our pre-lock read saw nothing
        self.d.owner.read_mirror = lambda task_id: None
        try:
            st = self.d._task("L-1")
        finally:
            del self.d.owner.read
            del self.d.owner.read_mirror
        self.assertEqual(st["attempts"], 2,
                         "a concurrent creator's counters must survive")
        self.assertAlmostEqual(st["spent"], 2 * COST, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
