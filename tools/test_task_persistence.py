#!/usr/bin/env python3
"""Tests for per-task state persistence — counters survive process restarts.

The plan §7 structural rule under test: restart/rename never resets counters,
and the 300 s wall-clock deadline applies to the task's whole lifetime, not
per dispatcher process. All tests use synthetic now_fn values; no network.
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
spec = importlib.util.spec_from_file_location("tools.task_persistence", TOOLS / "task_persistence.py")
tp = importlib.util.module_from_spec(spec)
sys.modules["tools.task_persistence"] = tp  # register BEFORE exec: dataclasses resolves via sys.modules
spec.loader.exec_module(tp)

spec2 = importlib.util.spec_from_file_location("tools.live_dispatcher", TOOLS / "live_dispatcher.py")
ld = importlib.util.module_from_spec(spec2)
sys.modules["tools.live_dispatcher"] = ld
spec2.loader.exec_module(ld)

PRICES = json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8"))


def fresh_dispatcher(tmp: Path, now_fn) -> ld.LiveDispatcher:
    prices = json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8"))
    return ld.LiveDispatcher(prices, tmp / "ledger.jsonl", now_fn=now_fn,
                             task_store=tmp / "task_state")


class TaskPersistence(unittest.TestCase):

    def test_counters_survive_restart(self):
        # Process 1: 2 dispatches on the same task
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            now = 1_000_000.0
            d1 = fresh_dispatcher(tmp, lambda: now)
            # Counter-only fixture: required checks are local, with no model slots.
            for _ in range(2):
                e = d1.attempt("L-1", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                               expected_in=10_000, expected_out=1_000, review_calls=0)
                self.assertEqual(e.decision, "dispatched")
            # Process 2 (fresh dispatcher instance = simulated restart, same store):
            d2 = fresh_dispatcher(tmp, lambda: now)
            st = d2._task("L-1")
            self.assertEqual(st["attempts"], 2, "attempt counter must survive restart")
            self.assertAlmostEqual(st["spent"], 0.003, places=6)
            self.assertEqual(st["repairs"], 1)  # second dispatch was a same-profile repair
            # the repair allowance is spent (2nd dispatch was a same-profile repair);
            # a profile switch is escalation, NOT a repair, so continue on other profiles:
            for pid in ("cloud-S", "cloud-C-alt"):
                e = d2.attempt("L-1", pid, "req", work_bound=0.01, review_bound=0.01,
                               expected_in=10_000, expected_out=1_000, review_calls=0)
            self.assertEqual(d2._task("L-1")["attempts"], 4)
            # cap-enforcement point: 4 attempts are USED; the 5th fires attempt-cap first:
            e = d2.attempt("L-1", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                           expected_in=10_000, expected_out=1_000)
            self.assertEqual(e.decision, "blocked-attempt-cap", "cap must fire across restarts")

    def test_deadline_survives_restart(self):
        # task started at t0; restart at t0+250s still allowed, t0+300s blocked
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            t0 = 2_000_000.0
            d1 = fresh_dispatcher(tmp, lambda: t0)
            d1.attempt("L-2", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                       expected_in=1_000, expected_out=1_000)
            st = d1._task("L-2")
            self.assertEqual(st["started"], t0, "started anchor persisted")

            d2 = fresh_dispatcher(tmp, lambda: t0 + 250.0)  # restarted 250s later
            e = d2.attempt("L-2", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                           expected_in=1_000, expected_out=1_000)
            self.assertEqual(e.decision, "dispatched", "still within the 300s whole-task window")

            d3 = fresh_dispatcher(tmp, lambda: t0 + 300.0)  # restarted at equality
            e = d3.attempt("L-2", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                           expected_in=1_000, expected_out=1_000)
            self.assertEqual(e.decision, "blocked-deadline",
                             "equality expires across restarts too (strictly-before rule)")

    def test_store_survives_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = tp.TaskStateStore(tmp / "task_state")
            p = store.path_for("L-3")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{corrupt", encoding="utf-8")
            # G5 fail-closed: corrupt state raises (never auto-reinit to zeros);
            # the file is preserved for forensics and the dispatcher refuses.
            with self.assertRaises(tp.CorruptState):
                store.load("L-3")
            self.assertTrue(p.is_file(), "corrupt file preserved for forensics")
            d = fresh_dispatcher(tmp, lambda: 3_000_000.0)
            e = d.attempt("L-3", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                          expected_in=1_000, expected_out=1_000)
            self.assertEqual(e.decision, "blocked:state-corrupt",
                             "corrupt counters must refuse, never reset")
            self.assertEqual(p.read_text(encoding="utf-8"), "{corrupt")
            self.assertNotIn("L-3", d._tasks)
            self.assertIsNone(e.attempt_no, "unknown counters must not be reported as zero")

    def test_observed_clock_rollback_stays_terminal_across_restarts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            now = [1000.0]
            calls = []
            def send(*args):
                calls.append(args)
                return 1000, 1000
            send.max_tokens = 1000
            send.count_tokens = lambda pid, req: 0
            def dispatcher():
                return ld.LiveDispatcher(PRICES, tmp / "ledger.jsonl", now_fn=lambda: now[0],
                                         task_store=tmp / "task_state", confirm_egress=True,
                                         dispatch_fn=send)
            d1 = dispatcher()
            self.assertEqual(d1.attempt('clock', 'cloud-C', 'req', work_bound=.01,
                                       review_bound=.01, expected_in=1000).decision, 'dispatched')
            now[0] = 1200.0
            self.assertEqual(d1.attempt('clock', 'cloud-S', 'req', work_bound=.01,
                                       review_bound=.01, expected_in=1000).decision, 'dispatched')
            now[0] = 1190.0
            d2 = dispatcher()
            self.assertEqual(d2.attempt('clock', 'cloud-C-alt', 'req', work_bound=.01,
                                       review_bound=.01, expected_in=1000).decision, 'blocked-deadline')
            now[0] = 1210.0
            d3 = dispatcher()
            self.assertEqual(d3.attempt('clock', 'cloud-C-alt', 'req', work_bound=.01,
                                       review_bound=.01, expected_in=1000).decision, 'blocked-deadline')
            self.assertEqual(len(calls), 2, 'rollback must refuse before transport')
            self.assertEqual(d3._task('clock')['attempts'], 2)
            self.assertTrue(d3._task('clock')['clock_stopped'])

    def test_invalid_state_refuses_egress_and_preserves_original(self):
        base = {"task_id": "L-3", "attempts": 1, "spent": 0.2,
                "started": 1.0, "repairs": 0, "last_profile": "cloud-C"}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = tp.TaskStateStore(tmp / "task_state")
            p = store.path_for("L-3")
            p.parent.mkdir()
            for mutation in ({"spent": float("nan")}, {"spent": 10**1000},
                             {"started": 10**1000}, {"attempts": True},
                             {"started": "bad"}, {"task_id": "other"},
                             {"repairs": -1}, {"clock": "monotonic"},
                             {"last_observed": float('nan')}, {"clock_stopped": 'yes'}):
                original = json.dumps(dict(base, **mutation))
                p.write_text(original, encoding="utf-8")
                calls = []
                d = ld.LiveDispatcher(PRICES, tmp / "ledger.jsonl", task_store=p.parent,
                                      confirm_egress=True,
                                      dispatch_fn=lambda *args: calls.append(args))
                e = d.attempt("L-3", "cloud-C", "req", work_bound=.01, review_bound=.01)
                self.assertEqual(e.decision, "blocked:state-corrupt")
                self.assertEqual(calls, [])
                self.assertEqual(p.read_text(encoding="utf-8"), original)
            p.write_bytes(b"\xff")
            d = fresh_dispatcher(tmp, lambda: 1.0)
            self.assertEqual(d.attempt("L-3", "cloud-C", "req", work_bound=.01,
                                      review_bound=.01).decision, "blocked:state-corrupt")
            self.assertEqual(p.read_bytes(), b"\xff")

    def test_atomic_write_no_tmp_leftovers(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            store = tp.TaskStateStore(tmp / "task_state")
            store.save({"task_id": "L-4", "attempts": 1, "spent": 0.01,
                        "started": 0.0, "repairs": 0, "last_profile": "cloud-C"})
            leftovers = list((tmp / "task_state").glob("*.tmp"))
            self.assertEqual(leftovers, [], "atomic write must not leave tmp files")
            doc = json.loads(store.path_for("L-4").read_text(encoding="utf-8"))
            self.assertEqual(doc["attempts"], 1)

    def test_store_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            now = 1.0
            d = ld.LiveDispatcher(json.loads((TOOLS / "prices-2.json").read_text(encoding="utf-8")),
                                  tmp / "l.jsonl", now_fn=lambda: now, task_store=None)
            d.attempt("L-5", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                      expected_in=1_000, expected_out=1_000)
            self.assertFalse((tmp / "task_state").exists(), "no state dir when store is off")

    def test_store_directory_sanitizes_task_ids(self):
        with tempfile.TemporaryDirectory() as td:
            store = tp.TaskStateStore(Path(td) / "task_state")
            p = store.path_for("../../etc/passwd")
            self.assertFalse(str(p).replace("\\", "/").count(".."), "path traversal sanitized")


if __name__ == "__main__":
    unittest.main(verbosity=2)
