"""Reservation, process concurrency and crash tests. No provider requests."""
from copy import deepcopy
from dataclasses import asdict
from contextlib import contextmanager
import json
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

import live_dispatcher as ld
from dispatch_budget import BudgetStateError, read_authority
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


def live_owner_writer(folder, task, entered, release, results):
    config = prices()
    config["pilot_caps"].update(max_cost_per_task_usd=2, max_cost_per_pilot_usd=2)
    def send(*args):
        entered.put(task)
        if not release.wait(20):
            raise TimeoutError("synthetic owner not released")
        return 500_000, 0
    send.max_tokens = 1
    send.count_tokens = lambda *args: 0
    result = dispatcher(folder, send, config).attempt(task, "p", "synthetic", work_bound=.5, review_bound=0)
    results.put(result.decision)


class DispatchBudget(unittest.TestCase):
    def test_invalid_purpose_refuses_without_state_or_transport_mutation(self):
        for existing in (False, True):
            for purpose in ("invalid-purpose", "", None, [], {}):
                with self.subTest(existing=existing, purpose=purpose), tempfile.TemporaryDirectory() as folder:
                    send, calls = transport(100_000)
                    d = dispatcher(folder, send)
                    if existing:
                        self.assertEqual(d.attempt("task", "p", "initial", work_bound=.1,
                                                  review_bound=0).decision, "dispatched")
                    before = {str(path.relative_to(folder)): path.read_bytes()
                              for path in Path(folder).rglob("*") if path.is_file()}
                    calls_before = list(calls)
                    with patch.object(d, "_task", side_effect=AssertionError("task must not be read or created")):
                        result = d.attempt("task", "p", "invalid", work_bound=.1,
                                           review_bound=0, purpose=purpose)
                    self.assertEqual(result.decision, "blocked-gate4")
                    self.assertEqual(result.purpose, "work")
                    self.assertEqual(pilot_report.entry_problems(asdict(result)), [])
                    self.assertEqual(calls, calls_before)
                    self.assertEqual(before, {str(path.relative_to(folder)): path.read_bytes()
                                             for path in Path(folder).rglob("*") if path.is_file()})

    def test_zero_dispatch_abandonment_is_canonical_and_preserves_empty_last_profile(self):
        for refusal in (None, "unknown-profile", "blocked-gate4"):
            with self.subTest(refusal=refusal), tempfile.TemporaryDirectory() as folder:
                send, calls = transport(100_000)
                d = dispatcher(folder, send)
                if refusal is not None:
                    profile = "missing-profile" if refusal == "unknown-profile" else "p"
                    result = d.attempt("task", profile, "preflight", work_bound=2, review_bound=0)
                    self.assertEqual(result.decision, refusal)
                result = d.abandon_task("task", evidence_ref="fixture://not-started")
                self.assertEqual(result.decision, "task-abandoned")
                self.assertEqual(result.profile_id, "<not-dispatched>")
                self.assertEqual(pilot_report.entry_problems(asdict(result)), [])
                snapshot = read_authority(d.ledger_path)
                task = snapshot["tasks"]["task"]
                self.assertTrue(task["abandoned"])
                self.assertFalse(task["verified"])
                self.assertEqual(task["last_profile"], "")
                self.assertEqual(task["attempts"], 0)
                self.assertEqual(task["repairs"], 0)
                self.assertEqual(float(task["charged"]), 0)
                report = pilot_report.build_report(d.prices, snapshot["events"])
                self.assertEqual(report["accounting_status"], "intact", report["problems"])
                self.assertEqual(report["per_task"][0]["outcome"], "abandoned")
                self.assertEqual(d.attempt("task", "p", "after", work_bound=.1,
                                           review_bound=0).decision, "blocked-abandoned")
                self.assertEqual(calls, [])

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
            self.assertEqual(d.attempt("other", "p", "other", work_bound=.01, review_bound=0).decision,
                             "blocked-uncertain")
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
                    result = d.attempt("task", "p", "req", work_bound=.75, review_bound=.1)
                    self.assertEqual(result.decision, "dispatched")
                    self.assertIsNotNone(result.reservation_id)
                    self.assertEqual(result.input_tokens, 750_000)
                    self.assertEqual(result.cost_usd, .75)
                    self.assertEqual(result.settlement_status, "committed")
                    if phase == "dispatched":
                        self.assertEqual(result.mirror_status, "pending")
                restored = dispatcher(folder, send)
                self.assertEqual(restored._task("task")["attempts"], 1)
                self.assertEqual(restored.pilot_spent, .75)
                self.assertEqual(restored.pilot_reserved, .1)
                self.assertEqual(len(calls), 1)
                events = [json.loads(line) for line in restored.ledger_path.read_text().splitlines()]
                self.assertEqual(events[-1]["decision"], "dispatched")

    def test_settlement_lock_failure_retains_usage_and_recovers_overrun_before_send(self):
        for receipt_failure in (False, True):
            with self.subTest(receipt_failure=receipt_failure), tempfile.TemporaryDirectory() as folder:
                config = prices()
                config["pilot_caps"].update(max_cost_per_task_usd=2, max_cost_per_pilot_usd=2)
                holder = None
                sends = []
                def send(*args):
                    sends.append("A")
                    holder.execute("BEGIN IMMEDIATE")
                    return 1_500_000, 0
                send.max_tokens, send.count_tokens = 1, lambda *args: 0
                d = dispatcher(folder, send, config)
                d._task("A")
                real_connect = sqlite3.connect
                holder = real_connect(d.budget.path, isolation_level=None)
                def fast_connect(*args, **kwargs):
                    kwargs["timeout"] = .05
                    return real_connect(*args, **kwargs)
                try:
                    with patch("dispatch_budget.sqlite3.connect", fast_connect):
                        if receipt_failure:
                            with patch.object(d.budget, "write_receipt", side_effect=OSError("synthetic disk full")):
                                result = d.attempt("A", "p", "PRIVATE_PROMPT_MARKER", work_bound=.5, review_bound=0)
                        else:
                            result = d.attempt("A", "p", "PRIVATE_PROMPT_MARKER", work_bound=.5, review_bound=0)
                finally:
                    holder.rollback()
                    holder.close()
                self.assertEqual(result.decision, "dispatch-unsettled")
                self.assertEqual(result.input_tokens, 1_500_000)
                self.assertEqual(result.cost_usd, 1.5)
                self.assertEqual(result.known_cost_usd, 1.5)
                self.assertIsNotNone(result.reservation_id)
                self.assertEqual(result.settlement_status, "unsettled")
                for path in d.budget.recovery_dir.glob("*.json"):
                    self.assertNotIn("PRIVATE_PROMPT_MARKER", path.read_text())
                later, later_calls = transport(500_000)
                restarted = dispatcher(folder, later, config)
                blocked = restarted.attempt("B", "p", "new", work_bound=.5, review_bound=0)
                self.assertEqual(blocked.decision, "blocked-uncertain")
                self.assertEqual(later_calls, [])
                if receipt_failure:
                    snapshot = read_authority(d.ledger_path)
                    self.assertEqual(snapshot["tasks"]["A"]["pending"]["status"], "uncertain")
                    restarted.reconcile_dispatch("A", result.reservation_id, input_tokens=1_500_000,
                        output_tokens=0, evidence_ref="fixture://host-retained-receipt", transport_finished=True)
                snapshot = read_authority(d.ledger_path)
                self.assertEqual(float(snapshot["tasks"]["A"]["charged"]), 1.5)
                self.assertTrue(snapshot["overrun"])
                self.assertTrue(snapshot["halted"])
                self.assertIsNone(snapshot["tasks"]["A"]["pending"])
                self.assertEqual(restarted.pilot_spent, 1.5)
                self.assertEqual(sends, ["A"])

    def test_live_owned_concurrent_transports_are_not_orphans(self):
        context = mp.get_context("spawn")
        with tempfile.TemporaryDirectory() as folder:
            entered, results = context.Queue(), context.Queue()
            release = context.Event()
            children = [context.Process(target=live_owner_writer, args=(folder, task, entered, release, results))
                        for task in ("A", "B")]
            try:
                for child in children:
                    child.start()
                self.assertEqual({entered.get(timeout=20), entered.get(timeout=20)}, {"A", "B"})
                snapshot = read_authority(Path(folder) / "ledger.jsonl")
                self.assertFalse(snapshot.get("halted", False))
                self.assertTrue(all(task["pending"]["status"] == "pending" for task in snapshot["tasks"].values()))
            finally:
                release.set()
                for child in children:
                    child.join(timeout=20)
                    if child.is_alive():
                        child.terminate()
                        child.join()
                entered.close()
            self.assertEqual([child.exitcode for child in children], [0, 0])
            self.assertEqual([results.get(timeout=5) for _ in children], ["dispatched", "dispatched"])
            results.close()

    def test_another_caller_can_replay_receipt_before_original_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            send_a, calls_a = transport(300_000)
            send_b, calls_b = transport(200_000)
            a, b = dispatcher(folder, send_a), dispatcher(folder, send_b)
            original = a.budget.transaction
            interleaved = []
            @contextmanager
            def transaction(*args, **kwargs):
                if kwargs.get("settling") is not None and not interleaved:
                    interleaved.append(True)
                    result_b = b.attempt("B", "p", "B", work_bound=.2, review_bound=0)
                    self.assertEqual(result_b.decision, "dispatched")
                with original(*args, **kwargs) as doc:
                    yield doc
            with patch.object(a.budget, "transaction", transaction):
                result = a.attempt("A", "p", "A", work_bound=.3, review_bound=0)
            self.assertEqual(result.decision, "dispatched")
            self.assertEqual(result.settlement_status, "committed")
            self.assertEqual(result.cost_usd, .3)
            self.assertEqual(len(calls_a), 1)
            self.assertEqual(len(calls_b), 1)
            self.assertEqual(a.pilot_spent, .5)
            snapshot = read_authority(a.ledger_path)
            self.assertEqual([e["task_id"] for e in snapshot["events"] if e["decision"] == "dispatched"], ["A", "B"])

    def test_failed_verification_keeps_one_owed_slot_within_attempt_cap(self):
        for known_failure in (False, True):
            with self.subTest(known_failure=known_failure), tempfile.TemporaryDirectory() as folder:
                config = prices()
                config["pilot_caps"]["max_attempts_per_task"] = 4
                outputs = [(300_000, 0), ld.DispatchFailure("synthetic", input_tokens=0, output_tokens=0)
                           if known_failure else TimeoutError("synthetic"), (100_000, 0)]
                def send(*args):
                    output = outputs.pop(0)
                    if isinstance(output, Exception):
                        raise output
                    return output
                send.max_tokens, send.count_tokens = 1, lambda *args: 0
                d = dispatcher(folder, send, config)
                d.attempt("A", "p", "work", work_bound=.3, review_bound=.2)
                failed = d.attempt("A", "p", "check", work_bound=.1, review_bound=0, purpose="verification")
                self.assertEqual(failed.decision, "dispatch-error")
                if not known_failure:
                    d.reconcile_dispatch("A", failed.reservation_id, input_tokens=0, output_tokens=0,
                        evidence_ref="fixture://not-billed", transport_finished=True)
                self.assertEqual(d._task("A")["review_calls_reserved"], 1)
                retried = d.attempt("A", "p", "check-again", work_bound=.1, review_bound=0, purpose="verification")
                self.assertEqual(retried.decision, "dispatched")
                self.assertEqual(retried.purpose, "verification")
                refused = d.attempt("A", "p", "extra-check", work_bound=.1, review_bound=0, purpose="verification")
                self.assertEqual(refused.decision, "blocked-gate4")
                self.assertEqual(refused.purpose, "verification")
                self.assertEqual(outputs, [])

    def test_failed_verification_never_restores_beyond_attempt_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            config = prices()
            config["pilot_caps"]["max_attempts_per_task"] = 2
            send, _ = transport(100_000)
            d = dispatcher(folder, send, config)
            d.attempt("A", "p", "work", work_bound=.1, review_bound=.2)
            def fail(*args):
                raise ld.DispatchFailure("synthetic", input_tokens=0, output_tokens=0)
            fail.max_tokens, fail.count_tokens = 1, lambda *args: 0
            d.dispatch_fn = fail
            d.attempt("A", "p", "check", work_bound=.1, review_bound=0, purpose="verification")
            self.assertEqual(d._task("A")["review_calls_reserved"], 0)
            self.assertEqual(d.attempt("A", "p", "again", work_bound=.1, review_bound=0,
                                     purpose="verification").decision, "blocked-attempt-cap")

    def test_abandonment_releases_review_without_claiming_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport(500_000)
            d = dispatcher(folder, send)
            clock = [1000]
            d.now_fn = lambda: clock[0]
            d.attempt("A", "p", "work", work_bound=.5, review_bound=.4)
            clock[0] = 1300
            self.assertEqual(d.attempt("A", "p", "check", work_bound=.4, review_bound=0,
                                      purpose="verification").decision, "blocked-deadline")
            closed = d.abandon_task("A", evidence_ref="fixture://deadline-expired")
            self.assertEqual(closed.decision, "task-abandoned")
            task = d._task("A")
            self.assertTrue(task["abandoned"])
            self.assertFalse(task["verified"])
            self.assertEqual(task["attempts"], 1)
            self.assertEqual(task["spent"], .5)
            self.assertEqual(d.pilot_reserved, 0)
            self.assertEqual(d.attempt("A", "p", "again", work_bound=.1, review_bound=0).decision,
                             "blocked-abandoned")
            with self.assertRaises(BudgetStateError):
                d.complete_verification("A", evidence_ref="fixture://not-verified")
            fresh, fresh_calls = transport(200_000)
            self.assertEqual(dispatcher(folder, fresh).attempt("B", "p", "new", work_bound=.2,
                review_bound=0).decision, "dispatched")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(fresh_calls), 1)

    def test_own_completion_is_allowed_while_another_task_halts_pilot(self):
        with tempfile.TemporaryDirectory() as folder:
            send, _ = transport(100_000)
            a = dispatcher(folder, send)
            a.attempt("A", "p", "work", work_bound=.1, review_bound=.2)
            a.attempt("A", "p", "check", work_bound=.1, review_bound=0, purpose="verification")
            overrun, _ = transport(500_000)
            b = dispatcher(folder, overrun)
            b.attempt("B", "p", "overrun", work_bound=.1, review_bound=0)
            result = a.complete_verification("A", evidence_ref="fixture://passed")
            self.assertEqual(result.decision, "verification-complete")
            self.assertTrue(a._task("A")["verified"])
            self.assertEqual(a.pilot_reserved, 0)
            self.assertTrue(read_authority(a.ledger_path)["halted"])

    def test_abandonment_cannot_release_an_unsettled_send(self):
        with tempfile.TemporaryDirectory() as folder:
            def fail(*args):
                raise TimeoutError("synthetic")
            fail.max_tokens, fail.count_tokens = 1, lambda *args: 0
            d = dispatcher(folder, fail)
            d.attempt("A", "p", "work", work_bound=.5, review_bound=.2)
            with self.assertRaises(BudgetStateError):
                d.abandon_task("A", evidence_ref="fixture://still-unknown")
            self.assertEqual(d.pilot_reserved, .7)

    def test_optional_task_store_can_be_omitted_but_not_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport(100_000)
            first = dispatcher(folder, send)
            first.attempt("A", "p", "one", work_bound=.1, review_bound=0)
            omitted = dispatcher(folder, send, store=False)
            self.assertEqual(omitted.attempt("A", "p", "two", work_bound=.1, review_bound=0).decision, "dispatched")
            self.assertEqual(omitted._task("A")["attempts"], 2)
            different = ld.LiveDispatcher(prices(), first.ledger_path, now_fn=lambda: 1000,
                dispatch_fn=send, confirm_egress=True, task_store=Path(folder) / "different")
            refused = different.attempt("B", "p", "three", work_bound=.1, review_bound=0)
            self.assertEqual(refused.decision, "blocked:budget-state")
            self.assertIn("explicit task-store", refused.reason)
            self.assertEqual(len(calls), 2)

    def test_qualified_adapter_cannot_use_different_dispatcher_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            send, calls = transport(100_000)
            send.price_configuration = prices()
            send.price_configuration["profiles"]["p"]["input_rate_per_mtok"] = 2
            with patch.object(send, "count_tokens") as count:
                result = dispatcher(folder, send).attempt("A", "p", "synthetic", work_bound=.1, review_bound=0)
            self.assertEqual(result.decision, "blocked-gate4")
            self.assertEqual(calls, [])
            count.assert_not_called()

    def test_actual_transport_duration_survives_unknown_usage_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = [1000]
            def send(*args):
                clock[0] = 1003.5
                raise TimeoutError("synthetic")
            send.max_tokens, send.count_tokens = 1, lambda *args: 0
            d = dispatcher(folder, send)
            d.now_fn = lambda: clock[0]
            failed = d.attempt("A", "p", "synthetic", work_bound=.5, review_bound=.1)
            self.assertEqual(failed.transport_started_at, 1000)
            self.assertEqual(failed.transport_finished_at, 1003.5)
            clock[0] = 1100
            result = d.reconcile_dispatch("A", failed.reservation_id, input_tokens=100_000,
                output_tokens=0, evidence_ref="fixture://receipt", transport_finished=True)
            self.assertEqual(result.ts, 1100)
            self.assertEqual(result.transport_started_at, 1000)
            self.assertEqual(result.transport_finished_at, 1003.5)

    def test_authority_snapshot_is_read_only_and_does_not_repair_mirror(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing" / "ledger.jsonl"
            with self.assertRaises(BudgetStateError):
                read_authority(missing)
            self.assertFalse(missing.parent.exists())
            send, _ = transport(100_000)
            d = dispatcher(folder, send)
            original = d.budget._mirror
            def fail_final(doc):
                if doc["events"] and doc["events"][-1]["decision"] == "dispatched":
                    raise OSError("synthetic derived failure")
                return original(doc)
            with patch.object(d.budget, "_mirror", fail_final):
                d.attempt("A", "p", "one", work_bound=.1, review_bound=0)
            before = d.ledger_path.read_bytes()
            snapshot = read_authority(d.ledger_path)
            self.assertEqual(snapshot["tasks"]["A"]["charged"], "0.1")
            self.assertEqual(d.ledger_path.read_bytes(), before)

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
        from test_billing_qualification import synthetic_fixture
        with tempfile.TemporaryDirectory() as folder:
            qualification, price_path, _ = synthetic_fixture(folder)
            fn = adapter.build_dispatch_fn(api_key="placeholder", qualification_path=qualification,
                                           prices_path=price_path, now_fn=lambda: 1500)
            for usage in (None, {}, {"input_tokens": True, "output_tokens": 0}, {"input_tokens": 1}):
                with self.subTest(usage=usage), patch.object(adapter, "_post", return_value={
                        "model": "claude-haiku-5-5", "usage": usage}) as posted:
                    with self.assertRaises(RuntimeError):
                        fn("cloud-C", "synthetic")
                    posted.assert_called_once()

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
            from gen_live_fill_sheet import build_sheet
            sheet = build_sheet()
            sheet.pop("evaluation_plan", None)  # Empty legacy-format fixture; this test audits unknown accounting.
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
