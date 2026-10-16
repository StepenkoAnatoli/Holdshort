"""Local synthetic evidence validation and sampling tests; no provider calls."""
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

import gen_live_fill_sheet as gen
import live_fill_tally as tally
import pilot_report as report


PRICES = tally.load_prices()


def entry(task="live-1", ts=100, **changes):
    result = {"task_id": task, "ts": ts, "profile_id": "cloud-C",
              "input_tokens": 1000, "output_tokens": 100,
              "cost_usd": report.recompute_cost(PRICES, "cloud-C", 1000, 100),
              "decision": "dispatched", "reason": "synthetic"}
    result.update(changes)
    return result


class LiveFill(unittest.TestCase):
    def sheet(self):
        return gen.build_sheet()

    def assignments(self):
        return {task: {"arm": "B", "cell": "T-01"} for task in ("live-1", "live-2")}

    def test_capacity_meets_ratified_target_and_repeats(self):
        sheet = self.sheet()
        self.assertEqual(len(sheet["cells"]), 20)
        self.assertEqual(len(gen.csv_rows(sheet)), 80)
        for arm in sheet["arms"]:
            self.assertEqual(sum(len(c["observations"]) for c in sheet["cells"].values() if c["arm"] == arm), 20)
        for cell in sheet["cells"].values():
            self.assertEqual([o["repeat"] for o in cell["observations"]], [1, 2, 1, 2])
            self.assertEqual(cell["planned_observations"], 4)
        self.assertTrue(tally.tally_summary(sheet)["integrity_ok"])

    def test_csv_headers_are_unique_and_preserve_planned_task(self):
        self.assertEqual(len(gen.CSV_FIELDS), len(set(gen.CSV_FIELDS)))
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=gen.CSV_FIELDS)
        writer.writeheader(); writer.writerows(gen.csv_rows(self.sheet()))
        row = next(csv.DictReader(io.StringIO(stream.getvalue())))
        self.assertEqual(row["planned_task_id"], "T-01")
        self.assertEqual(row["task_id"], "")

    def test_null_measurements_cannot_complete_a_sheet(self):
        sheet = self.sheet()
        for cell in sheet["cells"].values():
            cell["filled"] = True
            for obs in cell["observations"]:
                obs.update({field: None for field in tally.MEASURED_REQUIRED})
                obs["accounting_intact"] = None
        summary = tally.tally_summary(sheet)
        self.assertFalse(summary["integrity_ok"])
        self.assertEqual(summary["observations_recorded"], 0)

    def test_corrupt_cost_and_usage_do_not_consume_slots(self):
        for change in ({"cost_usd": 999}, {"cost_usd": float("nan")},
                       {"input_tokens": 1000.9}, {"output_tokens": True},
                       {"ts": None}, {"profile_id": None}):
            with self.subTest(change=change):
                sheet = self.sheet(); before = copy.deepcopy(sheet)
                findings = tally.import_from_ledger(sheet, [entry(**change)], self.assignments())
                self.assertTrue(findings)
                self.assertEqual(sheet, before)

    def test_partial_and_complete_fill_require_valid_observations(self):
        sheet = self.sheet()
        entries = [entry(ts=100), entry(ts=101), entry("live-2", 102), entry("live-2", 103)]
        self.assertEqual(tally.import_from_ledger(sheet, entries[:2], self.assignments()), [])
        cell = sheet["cells"]["B|T-01"]
        self.assertFalse(cell["filled"])
        self.assertEqual(tally.import_from_ledger(sheet, entries, self.assignments()), [])
        self.assertTrue(cell["filled"])
        summary = tally.tally_summary(sheet)
        self.assertTrue(summary["integrity_ok"])
        self.assertEqual(summary["observations_recorded"], 4)
        self.assertEqual(cell["observations"][1]["inter_observation_interval_s"], 1)
        self.assertEqual(cell["observations"][1]["latency_s"], tally.UNKNOWN_LATENCY)

    def test_reimport_is_idempotent_even_with_empty_slots(self):
        sheet = self.sheet(); entries = [entry(), entry(ts=101)]
        self.assertEqual(tally.import_from_ledger(sheet, entries, self.assignments()), [])
        before = copy.deepcopy(sheet)
        self.assertEqual(tally.import_from_ledger(sheet, entries, self.assignments()), [])
        self.assertEqual(sheet, before)

    def frozen_rows(self):
        plan = tally.frozen_evaluation_plan()
        rows = []
        for trial in plan["trials"]:
            profile = "cloud-S" if trial["arm"] == "A" else "cloud-C"
            row = entry(trial["task_id"], 100 + trial["schedule_index"], profile_id=profile,
                        cost_usd=report.recompute_cost(PRICES, profile, 1000, 100))
            rows.append(row)
        return plan, rows

    def test_frozen_plan_counts_fixture_repeats_with_unique_execution_ids(self):
        plan, rows = self.frozen_rows()
        sheet = self.sheet()
        self.assertEqual(tally.import_from_ledger(sheet, rows[:37], plan["assignments"]), [])
        self.assertEqual(tally.import_from_ledger(sheet, rows, plan["assignments"]), [])
        summary = tally.tally_summary(sheet)
        self.assertEqual(summary["per_arm"], {arm: 20 for arm in "ABCD"})
        self.assertEqual(summary["cells_filled"], 20)
        self.assertTrue(summary["evaluation_plan_bound"])
        self.assertEqual(summary["live_model_qualification"], "pending")
        self.assertTrue(summary["integrity_ok"], summary["problems"])
        before = copy.deepcopy(sheet)
        self.assertEqual(tally.import_from_ledger(sheet, rows, plan["assignments"]), [])
        self.assertEqual(sheet, before)

    def test_frozen_plan_rejects_assignment_split_and_execution_order_drift(self):
        plan, rows = self.frozen_rows()
        mapping = copy.deepcopy(plan["assignments"])
        mapping[rows[0]["task_id"]]["split"] = "invented"
        findings = tally.import_from_ledger(self.sheet(), rows, mapping)
        self.assertEqual(findings[0]["kind"], "invalid-plan")
        sheet = self.sheet()
        findings = tally.import_from_ledger(sheet, [rows[1], rows[0]], plan["assignments"])
        self.assertEqual(findings[0]["kind"], "schedule-drift")
        self.assertEqual(tally.tally_summary(sheet)["observations_recorded"], 0)

    def test_frozen_plan_malformed_metadata_produces_findings_without_crash(self):
        plan, rows = self.frozen_rows()
        sheet = self.sheet()
        sheet["cells"]["A|T-01"]["observations"] = None
        before = copy.deepcopy(sheet)
        findings = tally.import_from_ledger(sheet, rows, plan["assignments"])
        self.assertEqual(findings[0]["kind"], "invalid-sheet")
        self.assertEqual(sheet, before)
        sheet = self.sheet()
        self.assertEqual(tally.import_from_ledger(sheet, rows[:1], plan["assignments"]), [])
        obs = next(obs for cell in sheet["cells"].values() for obs in cell["observations"] if obs["task_id"])
        obs["fixture_id"] = []
        self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_frozen_assignment_map_rejects_coerced_numeric_metadata(self):
        plan, rows = self.frozen_rows()
        for field, value in (("schedule_index", True), ("schedule_index", 1.0),
                             ("repeat", float(plan["assignments"][rows[0]["task_id"]]["repeat"]))):
            with self.subTest(field=field, value=value):
                mapping = copy.deepcopy(plan["assignments"])
                mapping[rows[0]["task_id"]][field] = value
                sheet = self.sheet(); before = copy.deepcopy(sheet)
                findings = tally.import_from_ledger(sheet, rows[:1], mapping)
                self.assertEqual(findings[0]["kind"], "invalid-plan")
                self.assertEqual(sheet, before)

    def test_frozen_observations_reject_coerced_numeric_metadata(self):
        plan, rows = self.frozen_rows()
        for field, value in (("schedule_index", True), ("schedule_index", 1.0),
                             ("assignment_slot", True), ("assignment_slot", 1.0)):
            with self.subTest(field=field, value=value):
                sheet = self.sheet()
                self.assertEqual(tally.import_from_ledger(sheet, rows[:1], plan["assignments"]), [])
                self.assertTrue(tally.tally_summary(sheet)["integrity_ok"])
                obs = next(obs for cell in sheet["cells"].values()
                           for obs in cell["observations"] if obs["task_id"])
                obs[field] = value
                self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_sheet_repeats_metadata_requires_an_integer(self):
        sheet = self.sheet()
        sheet["repeats_per_task"] = float(sheet["repeats_per_task"])
        self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_frozen_plan_does_not_count_a_repair_as_another_repeat(self):
        plan, rows = self.frozen_rows()
        sheet = self.sheet()
        findings = tally.import_from_ledger(sheet, [rows[0], dict(rows[0], ts=200)], plan["assignments"])
        self.assertEqual(findings[0]["kind"], "duplicate-trial-work")
        self.assertEqual(tally.tally_summary(sheet)["observations_recorded"], 1)

    def test_verification_and_terminal_refusals_do_not_fill_trials(self):
        sheet = self.sheet()
        rows = [entry(), entry(ts=101, purpose="verification"),
                entry(ts=102, decision="blocked-verified", input_tokens=0, output_tokens=0, cost_usd=0)]
        self.assertEqual(tally.import_from_ledger(sheet, rows, self.assignments()), [])
        self.assertEqual(tally.tally_summary(sheet)["observations_recorded"], 1)

    def test_reconciliation_preserves_execution_time_and_real_duration(self):
        sheet = self.sheet()
        pending = entry(ts=100, decision="dispatch-reserved", input_tokens=None, output_tokens=None,
                        cost_usd=None, reservation_id="r", reserved_cost_usd=.1)
        failed = entry(ts=105, decision="dispatch-error", input_tokens=None, output_tokens=None,
                       cost_usd=None, reservation_id="r", reserved_cost_usd=.1,
                       transport_started_at=100, transport_finished_at=105)
        receipt = entry(ts=3700, decision="dispatch-reconciled", reservation_id="r")
        self.assertEqual(tally.import_from_ledger(sheet, [pending, failed, receipt], self.assignments()), [])
        obs = sheet["cells"]["B|T-01"]["observations"][0]
        self.assertEqual(obs["ts"], 105)
        self.assertEqual(obs["source_event_ts"], 3700)
        self.assertEqual(obs["latency_s"], 5)
        self.assertTrue(tally.tally_summary(sheet)["integrity_ok"])

    def test_changed_source_or_assignment_is_reported_and_preserved(self):
        for changed, assignments in ([entry(ts=101)], self.assignments()), ([entry()], {"live-1": {"arm": "C", "cell": "T-01"}}):
            sheet = self.sheet(); tally.import_from_ledger(sheet, [entry()], self.assignments())
            before = copy.deepcopy(sheet)
            findings = tally.import_from_ledger(sheet, changed, assignments)
            self.assertEqual([f["kind"] for f in findings], ["changed-evidence"])
            self.assertEqual(sheet, before)

    def test_repeats_cannot_exceed_plan(self):
        sheet = self.sheet()
        findings = tally.import_from_ledger(sheet, [entry(ts=i) for i in (100, 101, 102)], self.assignments())
        self.assertEqual([f["kind"] for f in findings], ["over-repeat-limit"])
        self.assertEqual(tally.tally_summary(sheet)["observations_recorded"], 2)

    def test_unknown_usage_is_not_a_measured_trial(self):
        sheet = self.sheet()
        findings = tally.import_from_ledger(sheet, [entry(input_tokens=None, cost_usd=None)], self.assignments())
        self.assertEqual([f["kind"] for f in findings], ["unknown-usage"])
        self.assertEqual(tally.tally_summary(sheet)["observations_recorded"], 0)

    def test_accounting_true_does_not_bypass_rate_check(self):
        sheet = self.sheet(); tally.import_from_ledger(sheet, [entry()], self.assignments())
        sheet["cells"]["B|T-01"]["observations"][0]["cost_usd"] = 999
        self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_duplicate_source_evidence_cannot_complete_sheet(self):
        sheet = self.sheet(); tally.import_from_ledger(sheet, [entry()], self.assignments())
        obs = copy.deepcopy(sheet["cells"]["B|T-01"]["observations"][0])
        for cell in sheet["cells"].values():
            cell["filled"] = True
            cell["observations"] = [copy.deepcopy(obs) for _ in cell["observations"]]
        self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_interleaved_task_repeats_are_labeled_correctly(self):
        sheet = self.sheet(); entries = [entry("live-1",100),entry("live-2",101),entry("live-1",102),entry("live-2",103)]
        self.assertEqual(tally.import_from_ledger(sheet, entries, self.assignments()), [])
        obs = sheet["cells"]["B|T-01"]["observations"]
        self.assertEqual([(o["task_id"],o["repeat"],o["assignment_slot"]) for o in obs],
                         [("live-1",1,1),("live-2",1,2),("live-1",2,1),("live-2",2,2)])
        self.assertTrue(tally.tally_summary(sheet)["integrity_ok"])

    def test_fixed_arm_requires_its_planned_profile(self):
        sheet = self.sheet(); findings = tally.import_from_ledger(sheet, [entry()], {"live-1":{"arm":"A","cell":"T-01"}})
        self.assertEqual([f["kind"] for f in findings], ["wrong-arm-profile"])
        self.assertEqual(tally.tally_summary(sheet)["observations_recorded"], 0)

    def test_changed_measured_fields_require_new_source_evidence(self):
        sheet = self.sheet(); tally.import_from_ledger(sheet,[entry()],self.assignments())
        obs = sheet["cells"]["B|T-01"]["observations"][0]
        obs["input_tokens"] = 2000
        obs["cost_usd"] = report.recompute_cost(PRICES,"cloud-C",2000,100)
        self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_malformed_top_level_has_a_diagnostic_summary(self):
        for sheet in (None, [], {}, {"cells":[]}):
            with self.subTest(sheet=sheet):
                self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_missing_source_evidence_is_disclosed_and_preserved(self):
        sheet=self.sheet(); entries=[entry(),entry(ts=101)]
        tally.import_from_ledger(sheet,entries,self.assignments()); before=copy.deepcopy(sheet)
        findings=tally.import_from_ledger(sheet,entries[:1],self.assignments())
        self.assertEqual([f["kind"] for f in findings],["missing-source-evidence"])
        self.assertEqual(sheet,before)

    def test_sampling_metadata_cannot_weaken_ratified_plan(self):
        for mutate in (lambda s:s.update(observations_per_arm_target=1),
                       lambda s:s['cells']['B|T-01'].update(planned_profile='cloud-S'),
                       lambda s:s['cells']['B|T-01'].pop('task_id')):
            sheet=self.sheet(); mutate(sheet)
            self.assertFalse(tally.tally_summary(sheet)['integrity_ok'])

    def test_insufficient_legacy_capacity_is_not_validated(self):
        sheet = self.sheet()
        for cell in sheet["cells"].values():
            cell["observations"] = cell["observations"][:2]
        self.assertFalse(tally.tally_summary(sheet)["integrity_ok"])

    def test_cli_import_findings_fail_in_full_and_gate_modes(self):
        for mode in ("full", "gate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); sheet = root / "sheet.json"; ledger = root / "ledger.jsonl"; mapping = root / "map.json"
                sheet.write_text(json.dumps(self.sheet()), encoding="utf-8")
                ledger.write_text(json.dumps(entry(cost_usd=999)) + "\n", encoding="utf-8")
                mapping.write_text(json.dumps(self.assignments()), encoding="utf-8")
                self.assertEqual(tally.main(["--sheet", str(sheet), "--import", str(ledger), "--assignments", str(mapping), "--mode", mode]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
