#!/usr/bin/env python3
"""Local fixture qualification and prospective schedule invariants; no providers."""
from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("ep", Path(__file__).with_name("eval_pool.py"))
ep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ep)


class ProspectivePool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = ep.load_pool()

    def test_frozen_manifest_and_literal_seed_inputs_recompute(self):
        self.assertEqual(ep.manifest_hash(self.pool), ep.EXPECTED_MANIFEST_SHA256)
        self.assertEqual(self.pool["seeds"], {"split": 6520794217341159832,
                                             "ordering": 14410658242273238690})
        self.assertFalse(self.pool["historical_ratification"])
        self.assertEqual(self.pool["live_model_qualification"], "pending")

    def test_schedule_is_deterministic_interleaved_and_complete(self):
        plan = ep.freeze_plan(self.pool)
        self.assertEqual(plan, ep.freeze_plan(deepcopy(self.pool)))
        self.assertEqual(plan["schedule_sha256"], ep.EXPECTED_SCHEDULE_SHA256)
        trials = plan["trials"]
        self.assertEqual(len(trials), 80)
        self.assertEqual(len({trial["trial_id"] for trial in trials}), 80)
        self.assertEqual(len({trial["task_id"] for trial in trials}), 80)
        self.assertEqual([trial["schedule_index"] for trial in trials], list(range(1, 81)))
        self.assertEqual(Counter(trial["arm"] for trial in trials), dict.fromkeys(ep.ARMS, 20))
        self.assertEqual(Counter(meta["split"] for meta in plan["fixtures"].values()),
                         {"tuning": 5, "holdout": 5})
        for cell in ep.CELLS:
            self.assertEqual(Counter(meta["split"] for meta in plan["fixtures"].values() if meta["cell"] == cell),
                             {"tuning": 1, "holdout": 1})
        for arm in ep.ARMS:
            selected = [trial for trial in trials if trial["arm"] == arm]
            self.assertEqual(Counter(trial["fixture_id"] for trial in selected),
                             dict.fromkeys(plan["fixtures"], 2))
            self.assertEqual(Counter(trial["split"] for trial in selected), {"tuning": 10, "holdout": 10})
        for identifier in plan["fixtures"]:
            selected = [trial for trial in trials if trial["fixture_id"] == identifier]
            self.assertEqual({(trial["arm"], trial["repeat"]) for trial in selected},
                             {(arm, repeat) for arm in ep.ARMS for repeat in (1, 2)})
            self.assertEqual(len({trial["split"] for trial in selected}), 1)
        for offset in range(0, 80, 4):
            block = trials[offset:offset + 4]
            self.assertEqual({trial["arm"] for trial in block}, set(ep.ARMS))
            self.assertEqual(len({(trial["fixture_id"], trial["repeat"]) for trial in block}), 1)
        for trial in trials:
            expected = {key: value for key, value in trial.items() if key not in ("trial_id", "task_id")}
            self.assertEqual(plan["assignments"][trial["task_id"]], expected)

    def test_different_rng_order_cannot_silently_change_frozen_trials(self):
        with patch.object(ep.random.Random, "shuffle", side_effect=lambda values: values.reverse()):
            with self.assertRaisesRegex(ep.PoolInvalid, "frozen schedule"):
                ep.freeze_plan(self.pool)

    def test_ten_baselines_fail_and_ten_references_pass(self):
        result = ep.self_check(self.pool)
        self.assertTrue(result["passed"], result)
        self.assertEqual(len(result["fixtures"]), 10)
        self.assertTrue(all(row["baseline_rejected"] and row["reference_accepted"] for row in result["fixtures"]))
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["live_model_qualification"], "pending")

    def test_relabelled_duplicate_is_not_an_independent_fixture(self):
        pool = deepcopy(self.pool)
        pool["fixtures"][1] = deepcopy(pool["fixtures"][0])
        pool["fixtures"][1]["fixture_id"] = "PE-02"
        pool["fixtures"][1]["title"] = "A renamed task"
        with self.assertRaisesRegex(ep.PoolInvalid, "identical fixture"):
            ep.validate_pool(pool)

    def test_weakening_checks_and_rehashing_does_not_change_frozen_contract(self):
        for change in (lambda p: p["fixtures"][0].update(checks="pass\n"),
                       lambda p: p["fixtures"][0]["writable_paths"].append("policy.txt"),
                       lambda p: p["seeds"].update(split=1),
                       lambda p: p.update(live_model_qualification="qualified")):
            pool = deepcopy(self.pool)
            change(pool)
            pool["manifest_sha256"] = ep.manifest_hash(pool)
            with self.assertRaises(ep.PoolInvalid):
                ep.validate_pool(pool)

    def test_malformed_paths_counters_and_duplicate_json_are_refused(self):
        cases = []
        for key, value in (("schema_version", True), ("repeats", True), ("observations_per_arm", 20.0)):
            pool = deepcopy(self.pool)
            pool[key] = value
            cases.append(pool)
        for writes in ([{}], ["../outside.py"], ["C:/outside.py"], ["README.md", "README.md"]):
            pool = deepcopy(self.pool)
            pool["fixtures"][0]["writable_paths"] = writes
            cases.append(pool)
        for pool in cases:
            with self.assertRaises(ep.PoolInvalid):
                ep.validate_pool(pool)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ep.PoolInvalid, "duplicate JSON"):
                ep.load_pool(path)

    def test_prepare_uses_new_identity_and_never_resets_prior_workspace(self):
        trial = ep.freeze_plan(self.pool)["trials"][0]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new-trial"
            result = ep.prepare_trial(self.pool, trial["trial_id"], destination)
            self.assertEqual(result["fixture_id"], trial["fixture_id"])
            before = {path.name: path.read_bytes() for path in destination.iterdir()}
            with self.assertRaisesRegex(ep.PoolInvalid, "never reset"):
                ep.prepare_trial(self.pool, trial["trial_id"], destination)
            self.assertEqual(before, {path.name: path.read_bytes() for path in destination.iterdir()})
            self.assertFalse(any("reference" in name for name in before))
            with self.assertRaisesRegex(ep.PoolInvalid, "not in the frozen"):
                ep.prepare_trial(self.pool, "made-up-trial", Path(directory) / "other")

    def test_readonly_and_unlisted_writes_fail_before_execution(self):
        fixture = self.pool["fixtures"][0]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            ep._write_files(workspace, fixture["reference"])
            (workspace / "policy.txt").write_text("changed\n", encoding="utf-8")
            with patch.object(ep.subprocess, "run") as run:
                self.assertFalse(ep.verify_fixture(self.pool, fixture["fixture_id"], workspace)["accepted"])
                run.assert_not_called()
            ep._write_files(workspace, fixture["reference"])
            (workspace / "extra.py").write_text("", encoding="utf-8")
            with patch.object(ep.subprocess, "run") as run:
                self.assertFalse(ep.verify_fixture(self.pool, fixture["fixture_id"], workspace)["accepted"])
                run.assert_not_called()

    def test_writes_during_acceptance_are_checked_again(self):
        fixture = self.pool["fixtures"][0]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            ep._write_files(workspace, fixture["reference"])
            def changed(*args, **kwargs):
                (workspace / "policy.txt").write_text("changed\n", encoding="utf-8")
                return subprocess.CompletedProcess([], 0, b"", b"")
            with patch.object(ep.subprocess, "run", side_effect=changed):
                result = ep.verify_fixture(self.pool, fixture["fixture_id"], workspace)
            self.assertFalse(result["accepted"])
            self.assertIn("read-only", result["reason"])

    def test_early_zero_exit_cannot_claim_acceptance_checks_completed(self):
        fixture = self.pool["fixtures"][1]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            ep._write_files(workspace, fixture["files"])
            (workspace / "ranges.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
            result = ep.verify_fixture(self.pool, fixture["fixture_id"], workspace)
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(result["accepted"], "zero exit alone does not prove that checks ran")

    def test_invalid_and_expired_acceptance_timeouts_do_not_pass(self):
        fixture = self.pool["fixtures"][1]
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            ep._write_files(workspace, fixture["files"])
            for value in (True, 0, -1, float('nan'), float('inf'), 10**1000):
                with self.subTest(value_type=type(value).__name__), patch.object(ep.subprocess, "run") as run:
                    with self.assertRaises(ep.PoolInvalid):
                        ep.verify_fixture(self.pool, fixture["fixture_id"], workspace, timeout_s=value)
                    run.assert_not_called()
            with patch.object(ep.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 1)):
                result = ep.verify_fixture(self.pool, fixture["fixture_id"], workspace)
            self.assertFalse(result["accepted"])
            self.assertIn("timed out", result["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
