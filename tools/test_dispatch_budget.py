"""Reservation, process concurrency and crash tests. No provider requests."""
from copy import deepcopy
import json
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

import live_dispatcher as ld
from dispatch_budget import BudgetStateError
import dispatch_adapter as adapter
import pilot_report
import pilot_close
import live_fill_tally


def prices():
    return {"revision": "synthetic", "profiles": {"p": {"input_rate_per_mtok": 1,
            "output_rate_per_mtok": 0}}, "pilot_caps": {"max_attempts_per_task": 8,
            "max_cost_per_task_usd": 1, "max_cost_per_pilot_usd": 1,
            "max_elapsed_seconds_per_task": 300, "same_profile_repairs_allowed_per_task": 3}}


def dispatcher(folder, send=None, config=None, store=True):
    root = Path(folder)
    return ld.LiveDispatcher(config or prices(), root / "ledger.jsonl", now_fn=lambda: 1000,
        dispatch_fn=send, confirm_egress=send is not None,
        task_store=root / "tasks" if store else None)


def transport(tokens=750_000):
    calls = []
    def send(profile, request):
        calls.append((profile, request))
        return tokens, 0
    send.max_tokens = 1
    send.count_tokens = lambda *args: 0
    return send, calls


def concurrent_writer(folder, task, barrier, entered, release, results):
    send, _ = transport()
    def count(*args):
        barrier.wait(timeout=15)
        return 0
    def physical_send(*args):
        (Path(folder) / (task + ".marker")).write_text("transport entered")
        entered.put(task)
        if not release.wait(15):
            raise TimeoutError("test transport was not released")
        return 750_000, 0
    physical_send.max_tokens = 1
    physical_send.count_tokens = count
    entry = dispatcher(folder, physical_send).attempt(task, "p", "synthetic",
                                                     work_bound=.75, review_bound=0)
    results.put(entry.decision)


def crash_writer(folder):
    def send(*args):
        (Path(folder) / "crash.marker").write_text("send entered; no usage returned")
        os._exit(17)
    send.max_tokens = 1
    send.count_tokens = lambda *args: 0
    dispatcher(folder, send).attempt("crash", "p", "synthetic", work_bound=.75, review_bound=.1)


class DispatchBudget(unittest.TestCase):
    def test_honest_full_bound_blocks_second_send_across_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport(1_000_000)
            first = dispatcher(folder, send)
            self.assertEqual(first.attempt("task", "p", "one", work_bound=1, review_bound=0).decision, "dispatched")
            second = dispatcher(folder, send)
            blocked = second.attempt("task", "p", "two", work_bound=1, review_bound=0)
            self.assertEqual(blocked.decision, "blocked-cost-cap")
            self.assertEqual(len(calls), 1)
            self.assertEqual(second._task("task")["attempts"], 1)
            self.assertEqual(second.pilot_spent, 1)

    def test_review_headroom_retained_and_only_verification_can_use_it(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport(600_000)
            d = dispatcher(folder, send)
            self.assertEqual(d.attempt("task", "p", "work", work_bound=.6, review_bound=.4).decision, "dispatched")
            self.assertEqual(d.pilot_spent, .6)
            self.assertEqual(d.pilot_reserved, .4)
            restarted = dispatcher(folder, send)
            self.assertEqual(restarted.attempt("task", "p", "more", work_bound=.01, review_bound=0).decision,
                             "blocked-cost-cap")
            self.assertEqual(restarted.attempt("other", "p", "other", work_bound=.01, review_bound=0).decision,
                             "blocked-pilot-cap")
            verify, _ = transport(250_000)
            verifier = dispatcher(folder, verify)
            result = verifier.attempt("task", "p", "checks", work_bound=.25, review_bound=0, purpose="verification")
            self.assertEqual(result.decision, "dispatched")
            self.assertEqual(verifier.pilot_spent, .85)
            self.assertEqual(verifier.pilot_reserved, .15)
            self.assertEqual(len(calls), 1)
            with self.assertRaises(ValueError):
                verifier.complete_verification("task", evidence_ref="")
            verifier.complete_verification("task", evidence_ref="fixture://passed-acceptance")
            self.assertEqual(verifier.pilot_reserved, 0)
            self.assertEqual(verifier._task("task")["attempts"], 2)
            self.assertEqual(verifier.attempt("task", "p", "reuse", work_bound=0, review_bound=0).decision,
                             "blocked-verified")

    def test_verification_reservation_cannot_be_double_used_or_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport(0)
            d = dispatcher(folder, send)
            result = d.attempt("task", "p", "checks", work_bound=.01, review_bound=0, purpose="verification")
            self.assertEqual(result.decision, "blocked-gate4")
            self.assertEqual(calls, [])

    def test_mandatory_verification_call_slots_survive_restart_and_cannot_be_stolen(self):
        with tempfile.TemporaryDirectory() as folder:
            config = prices()
            config["pilot_caps"]["max_attempts_per_task"] = 3
            send, calls = transport(0)
            d = dispatcher(folder, send, config)
            self.assertEqual(d.attempt("task", "p", "work", work_bound=0, review_bound=0,
                                      review_calls=2).decision, "dispatched")
            restarted = dispatcher(folder, send, config)
            self.assertEqual(restarted._task("task")["review_calls_reserved"], 2)
            self.assertEqual(restarted.attempt("task", "p", "steal", work_bound=0,
                                               review_bound=0).decision, "blocked-attempt-cap")
            for expected_reserved in (1, 0):
                result = restarted.attempt("task", "p", "check", work_bound=0, review_bound=0,
                                           purpose="verification")
                self.assertEqual(result.decision, "dispatched")
                self.assertEqual(result.review_calls_reserved, expected_reserved)
            self.assertEqual(len(calls), 3)
            self.assertEqual(restarted._task("task")["attempts"], 3)

    def test_independent_instance_reads_shared_spend_without_task_store(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport()
            a, b = dispatcher(folder, send, store=False), dispatcher(folder, send, store=False)
            self.assertEqual(a.attempt("one", "p", "one", work_bound=.75, review_bound=0).decision, "dispatched")
            self.assertEqual(b.pilot_spent, .75)
            self.assertEqual(b.attempt("two", "p", "two", work_bound=.75, review_bound=0).decision, "blocked-pilot-cap")
            self.assertEqual(len(calls), 1)

    def test_two_processes_compete_at_actual_send_boundary(self):
        context = mp.get_context("spawn")
        with tempfile.TemporaryDirectory() as folder:
            barrier = context.Barrier(2)
            entered, results = context.Queue(), context.Queue()
            release = context.Event()
            children = [context.Process(target=concurrent_writer,
                args=(folder, name, barrier, entered, release, results)) for name in ("one", "two")]
            try:
                for child in children:
                    child.start()
                entered.get(timeout=20)
                self.assertEqual(results.get(timeout=20), "blocked-pilot-cap")
                self.assertEqual(len(list(Path(folder).glob("*.marker"))), 1)
                observer = dispatcher(folder)
                self.assertEqual(observer.pilot_spent, 0)
                self.assertEqual(observer.pilot_reserved, .75)
                release.set()
                self.assertEqual(results.get(timeout=20), "dispatched")
                for child in children:
                    child.join(timeout=10)
                    self.assertEqual(child.exitcode, 0)
                self.assertEqual(observer.pilot_spent, .75)
                self.assertEqual(observer.pilot_reserved, 0)
            finally:
                release.set()
                for child in children:
                    if child.is_alive():
                        child.terminate()
                    child.join(timeout=5)

    def test_process_crash_retains_attempt_cash_and_review_until_receipt(self):
        context = mp.get_context("spawn")
        with tempfile.TemporaryDirectory() as folder:
            child = context.Process(target=crash_writer, args=(folder,))
            child.start()
            child.join(timeout=15)
            if child.is_alive():
                child.terminate()
                child.join()
                self.fail("crash fixture hung")
            self.assertEqual(child.exitcode, 17)
            send, calls = transport(200_000)
            d = dispatcher(folder, send)
            task = d._task("crash")
            self.assertEqual(task["attempts"], 1)
            self.assertEqual(task["spent"], 0)
            self.assertEqual(d.pilot_reserved, .85)
            events = [json.loads(line) for line in d.ledger_path.read_text().splitlines()]
            self.assertIsNone(events[0]["cost_usd"])
            self.assertEqual(events[0]["usage_status"], "unknown")
            self.assertEqual(d.attempt("crash", "p", "again", work_bound=.01, review_bound=0).decision,
                             "blocked-uncertain")
            self.assertEqual(d.attempt("other", "p", "other", work_bound=.2, review_bound=0).decision,
                             "blocked-pilot-cap")
            self.assertEqual(calls, [])
            identifier = task["pending"]["id"]
            with self.assertRaises(ValueError):
                d.reconcile_dispatch("crash", identifier, input_tokens=600_000, output_tokens=0,
                                     evidence_ref="fixture://receipt")
            with self.assertRaises(BudgetStateError):
                d.reconcile_dispatch("crash", "wrong-id", input_tokens=600_000, output_tokens=0,
                                     evidence_ref="fixture://receipt", transport_finished=True)
            reconciled = d.reconcile_dispatch("crash", identifier, input_tokens=600_000, output_tokens=0,
                                              evidence_ref="fixture://receipt", transport_finished=True)
            self.assertEqual(reconciled.cost_usd, .6)
            self.assertEqual(d.pilot_reserved, .1)
            self.assertEqual(d._task("crash")["attempts"], 1)
            with self.assertRaises(BudgetStateError):
                d.reconcile_dispatch("crash", identifier, input_tokens=600_000, output_tokens=0,
                                     evidence_ref="fixture://receipt", transport_finished=True)

    def test_unknown_failure_stops_pilot_and_does_not_export_error_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            def send(*args):
                raise TimeoutError("PRIVATE_TRANSPORT_ERROR")
            send.max_tokens = 1
            send.count_tokens = lambda *args: 0
            d = dispatcher(folder, send)
            error = d.attempt("task", "p", "PRIVATE_REQUEST", work_bound=.75, review_bound=.1)
            self.assertEqual(error.decision, "dispatch-error")
            self.assertIsNone(error.cost_usd)
            self.assertEqual(d._task("task")["attempts"], 1)
            self.assertEqual(d.pilot_reserved, .85)
            self.assertEqual(dispatcher(folder, send).attempt("other", "p", "new", work_bound=.01,
                                                            review_bound=0).decision, "blocked-uncertain")
            text = d.ledger_path.read_text()
            self.assertNotIn("PRIVATE_TRANSPORT_ERROR", text)
            self.assertNotIn("PRIVATE_REQUEST", text)
            with self.assertRaises(BudgetStateError):
                d.complete_verification("task", evidence_ref="fixture://cannot-release-unknown")

    def test_known_failure_and_overrun_are_settled(self):
        for overrun in (False, True):
            with self.subTest(overrun=overrun), tempfile.TemporaryDirectory() as folder:
                actual = 1_200_000 if overrun else 750_000
                def send(*args):
                    raise ld.DispatchFailure("PRIVATE_ERROR", input_tokens=actual, output_tokens=0)
                send.max_tokens = 1
                send.count_tokens = lambda *args: 0
                d = dispatcher(folder, send)
                result = d.attempt("task", "p", "req", work_bound=.75, review_bound=.1)
                self.assertEqual(result.decision, "dispatch-error")
                self.assertEqual(result.cost_usd, actual / 1_000_000)
                self.assertEqual(d.pilot_spent, actual / 1_000_000)
                self.assertEqual(d._task("task")["attempts"], 1)
                self.assertIsNone(d._task("task")["pending"])
                self.assertEqual(d.pilot_reserved, .1)

    def test_missing_and_invalid_usage_never_becomes_zero(self):
        for usage in ((None, None), (True, 0), (-1, 0), (1,), (1.5, 0)):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as folder:
                def send(*args):
                    return usage
                send.max_tokens = 1
                send.count_tokens = lambda *args: 0
                d = dispatcher(folder, send)
                result = d.attempt("task", "p", "req", work_bound=.75, review_bound=0)
                self.assertIsNone(result.cost_usd)
                self.assertEqual(result.usage_status, "unknown")
                self.assertEqual(d.pilot_reserved, .75)

    def test_partial_known_usage_is_preserved_and_not_double_counted_on_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            def send(*args):
                raise ld.DispatchFailure("synthetic partial receipt", input_tokens=600_000)
            send.max_tokens = 1
            send.count_tokens = lambda *args: 0
            d = dispatcher(folder, send)
            result = d.attempt("task", "p", "req", work_bound=.75, review_bound=.1)
            self.assertEqual(result.input_tokens, 600_000)
            self.assertIsNone(result.output_tokens)
            self.assertIsNone(result.cost_usd)
            self.assertEqual(result.known_cost_usd, .6)
            self.assertEqual(d.pilot_spent, .6)
            self.assertEqual(d.pilot_reserved, .25)
            task = d._task("task")
            d.reconcile_dispatch("task", task["pending"]["id"], input_tokens=700_000, output_tokens=0,
                                 evidence_ref="fixture://complete-receipt", transport_finished=True)
            self.assertEqual(d.pilot_spent, .7)
            self.assertEqual(d.pilot_reserved, .1)
            self.assertEqual(d._task("task")["attempts"], 1)

    def test_count_error_and_unknown_bounds_never_consume_send(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport()
            d = dispatcher(folder, send)
            for value in (None, float("nan"), float("inf"), -1, True):
                self.assertEqual(d.attempt("task", "p", "req", work_bound=value, review_bound=0).decision,
                                 "blocked-gate4")
            def bad_count(*args):
                raise OSError("PRIVATE_COUNT_ERROR")
            send.count_tokens = bad_count
            with self.assertRaises(OSError):
                d.attempt("task", "p", "req", work_bound=.75, review_bound=0)
            self.assertEqual(calls, [])
            self.assertEqual(d._task("task")["attempts"], 0)
            self.assertEqual(d.pilot_reserved, 0)

    def test_invalid_identity_cannot_initialize_or_poison_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport()
            d = dispatcher(folder, send)
            for value in (None, 1, [], "", " "):
                result = d.attempt(value, "p", "req", work_bound=.75, review_bound=0)
                self.assertEqual(result.decision, "blocked-gate4")
                result = d.attempt("valid", value, "req", work_bound=.75, review_bound=0)
                self.assertEqual(result.decision, "blocked-gate4")
            self.assertEqual(calls, [])
            self.assertFalse(d.budget.path.exists())
            self.assertEqual(d.attempt("valid", "p", "req", work_bound=.75, review_bound=0).decision, "dispatched")

    def test_committed_journal_recovers_after_mirror_failure(self):
        for phase in ("dispatch-reserved", "dispatched"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as folder:
                send, calls = transport()
                d = dispatcher(folder, send)
                original = d.budget._mirror
                def broken(doc):
                    if doc["events"] and doc["events"][-1]["decision"] == phase:
                        raise OSError("simulated crash before mirror")
                    return original(doc)
                with patch.object(d.budget, "_mirror", broken):
                    self.assertEqual(d.attempt("task", "p", "req", work_bound=.75, review_bound=.1).decision,
                                     "blocked:budget-state")
                restored = dispatcher(folder, send)
                self.assertEqual(restored._task("task")["attempts"], 1)
                self.assertEqual(restored.pilot_spent, .75 if phase == "dispatched" else 0)
                self.assertEqual(restored.pilot_reserved, .1 if phase == "dispatched" else .85)
                self.assertEqual(len(calls), 1 if phase == "dispatched" else 0)
                events = [json.loads(line) for line in restored.ledger_path.read_text().splitlines()]
                self.assertEqual(events[-1]["decision"], phase)

    def test_missing_corrupt_or_changed_authority_never_resets(self):
        for mutation in ("delete", "corrupt", "payload", "caps", "ledger", "store"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                send, calls = transport()
                d = dispatcher(folder, send)
                d.attempt("task", "p", "req", work_bound=.75, review_bound=0)
                config = prices()
                if mutation == "delete":
                    d.budget.path.unlink()
                elif mutation == "corrupt":
                    d.budget.path.write_bytes(b"CORRUPT_AUTHORITY")
                elif mutation == "payload":
                    with sqlite3.connect(d.budget.path) as connection:
                        envelope = json.loads(connection.execute("SELECT payload FROM authority").fetchone()[0])
                        envelope["document"]["tasks"]["task"]["charged"] = "0"
                        connection.execute("UPDATE authority SET payload=?", (json.dumps(envelope),))
                    connection.close()
                elif mutation == "caps":
                    config["pilot_caps"]["max_cost_per_pilot_usd"] = 2
                elif mutation == "ledger":
                    with d.ledger_path.open("a") as handle:
                        handle.write('{"partial')
                if mutation == "store":
                    second = ld.LiveDispatcher(config, Path(folder) / "other.jsonl", dispatch_fn=send,
                        confirm_egress=True, task_store=Path(folder) / "tasks", now_fn=lambda: 1000)
                else:
                    second = dispatcher(folder, send, config)
                result = second.attempt("other", "p", "req", work_bound=.1, review_bound=0)
                self.assertEqual(result.decision, "blocked:budget-state")
                self.assertEqual(len(calls), 1)

    def test_real_adapter_missing_usage_is_refused_after_response(self):
        for usage in (None, {}, {"input_tokens": True, "output_tokens": 0}, {"input_tokens": 1}):
            with self.subTest(usage=usage), patch.object(adapter, "_post", return_value={"usage": usage}):
                with self.assertRaises(RuntimeError):
                    adapter._http_transport({}, "synthetic", "placeholder")

    def test_deadline_expiring_during_durable_commit_cancels_before_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport()
            now = [1000]
            d = dispatcher(folder, send)
            d.now_fn = lambda: now[0]
            original = d.budget._mirror
            def delayed(doc):
                if doc["events"] and doc["events"][-1]["decision"] == "dispatch-reserved":
                    now[0] = 1300
                original(doc)
            with patch.object(d.budget, "_mirror", delayed):
                result = d.attempt("task", "p", "req", work_bound=.75, review_bound=.1)
            self.assertEqual(result.decision, "blocked-deadline")
            self.assertEqual(calls, [])
            self.assertEqual(d._task("task")["attempts"], 0)
            self.assertEqual(d.pilot_reserved, 0)
            entries = [json.loads(line) for line in d.ledger_path.read_text().splitlines()]
            self.assertEqual(pilot_report.build_report(prices(), entries)["pilot"]["dispatches"], 0)

    def test_reports_count_one_attempt_and_keep_unknown_accounting_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            def send(*args):
                raise TimeoutError("synthetic timeout")
            send.max_tokens = 1
            send.count_tokens = lambda *args: 0
            d = dispatcher(folder, send)
            d.attempt("task", "p", "req", work_bound=.75, review_bound=.1)
            def entries():
                return [json.loads(line) for line in d.ledger_path.read_text().splitlines()]
            report = pilot_report.build_report(prices(), entries())
            self.assertEqual(report["pilot"]["dispatches"], 1)
            self.assertEqual(report["per_task"][0]["attempts"], 1)
            self.assertEqual(report["pilot"]["reserved_usd"], .85)
            self.assertFalse(report["pilot"]["total_spend_complete"])
            self.assertEqual(report["accounting_status"], "GAPS_FOUND")
            close = pilot_close.close_ledger(prices(), entries())
            self.assertEqual(close["pilot_totals"]["headroom_usd"], .15)
            self.assertEqual(close["pilot_totals"]["completed"], 0)
            sheet = {"cells": {}}
            findings = live_fill_tally.import_from_ledger(sheet, entries(), {})
            self.assertEqual([item["kind"] for item in findings], ["unknown-usage"])
            task = d._task("task")
            d.reconcile_dispatch("task", task["pending"]["id"], input_tokens=600_000, output_tokens=0,
                                 evidence_ref="fixture://receipt", transport_finished=True)
            report = pilot_report.build_report(prices(), entries())
            self.assertEqual(report["accounting_status"], "intact")
            self.assertEqual(report["pilot"]["dispatches"], 1)
            self.assertEqual(report["pilot"]["total_spend_usd"], .6)
            self.assertTrue(report["pilot"]["total_spend_complete"])
            self.assertEqual(report["pilot"]["reserved_usd"], .1)
            self.assertEqual(pilot_close.close_ledger(prices(), entries())["pilot_totals"]["completed"], 0)
            d.complete_verification("task", evidence_ref="fixture://passed-checks")
            self.assertEqual(pilot_close.close_ledger(prices(), entries())["pilot_totals"]["completed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
