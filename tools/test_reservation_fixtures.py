"""Independently audit the static key, paired inputs and scorer failure paths."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import score_reservation_fixtures as scorer

ROOT = Path(__file__).resolve().parents[1]
PACKET = scorer.read_json(scorer.FIXTURES / "cases.json")
KEY = scorer.read_json(scorer.FIXTURES / "answer-key.json")


def changed_leaves(left, right, prefix=""):
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return [prefix]
        return [path for name in left for path in
                changed_leaves(left[name], right[name], f"{prefix}/{name}")]
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [prefix]
        return [path for i, (a, b) in enumerate(zip(left, right)) for path in
                changed_leaves(a, b, f"{prefix}/{i}")]
    return [] if left == right else [prefix]


class ReservationFixtures(unittest.TestCase):
    def test_five_pairs_change_exactly_one_fact(self):
        expected = {"cash-owner": "/cash_reservations/0/owner",
                    "call-owner": "/call_reservations/0/owner",
                    "cash-boundary": "/cash_cap",
                    "call-boundary": "/planned_calls",
                    "verification-omission": "/proposed_all_in_bound"}
        pairs = {}
        for case in PACKET["cases"]:
            pairs.setdefault(case["pair_id"], []).append(case)
        self.assertEqual(set(pairs), set(expected))
        for name, cases in pairs.items():
            with self.subTest(pair=name):
                self.assertEqual(len(cases), 2)
                self.assertEqual(changed_leaves(cases[0]["input"], cases[1]["input"]),
                                 [expected[name]])

    def test_static_key_against_independent_decimal_accounting(self):
        # This audit derives from the input facts and does not call dispatcher
        # pricing, routing or scorer arithmetic to manufacture expected answers.
        answers = {answer["id"]: answer for answer in KEY["answers"]}
        identifiers = [case["id"] for case in PACKET["cases"]]
        self.assertEqual(len(set(identifiers)), 10)
        self.assertEqual(set(answers), set(identifiers))
        for case in PACKET["cases"]:
            with self.subTest(case=case["id"]):
                data = case["input"]
                cash_reserved = Decimal("0")
                own_cash = Decimal("0")
                slots_reserved = own_slots = 0
                for reservation in data["cash_reservations"]:
                    self.assertEqual(set(reservation), {"owner", "amount"})
                    self.assertTrue(isinstance(reservation["owner"], str) and reservation["owner"])
                    amount = Decimal(reservation["amount"])
                    self.assertTrue(amount.is_finite() and amount >= 0)
                    cash_reserved += amount
                    if reservation["owner"] == data["task_id"]:
                        own_cash += amount
                for reservation in data["call_reservations"]:
                    self.assertEqual(set(reservation), {"owner", "slots"})
                    self.assertTrue(isinstance(reservation["owner"], str) and reservation["owner"])
                    self.assertIs(type(reservation["slots"]), int)
                    self.assertGreaterEqual(reservation["slots"], 0)
                    slots_reserved += reservation["slots"]
                    if reservation["owner"] == data["task_id"]:
                        own_slots += reservation["slots"]
                free = Decimal(data["cash_cap"]) - Decimal(data["settled_cash"]) - cash_reserved
                bound = Decimal(data["work_bound"]) + Decimal(data["mandatory_verification_bound"])
                cash_needed = max(Decimal("0"), bound - own_cash)
                calls_needed = max(0, data["planned_calls"] - own_slots)
                total_calls = data["used_calls"] + slots_reserved + calls_needed
                approved = (Decimal(data["proposed_all_in_bound"]) >= bound
                            and cash_needed <= free and total_calls <= data["call_limit"])
                answer = answers[case["id"]]
                for field, amount in (("free_cash", free), ("all_in_bound", bound),
                                      ("additional_cash", cash_needed)):
                    self.assertEqual(Decimal(answer[field]), amount)
                self.assertEqual(answer["additional_calls"], calls_needed)
                self.assertEqual(answer["prospective_calls"], total_calls)
                self.assertEqual(answer["route"], "direct" if approved else "blocked")
                self.assertEqual(answer["first_failing_gate"], None if approved else 4)

    def test_each_numeric_field_is_scored_even_with_correct_route(self):
        for field in scorer.CASH_FIELDS + scorer.CALL_FIELDS:
            response = deepcopy(KEY)
            response["answers"][0][field] = ("9.00" if field in scorer.CASH_FIELDS else 9)
            result = scorer.score(response, KEY)
            self.assertEqual(result["matching_cases"], 9)
            self.assertEqual(result["mismatches"], [{"id": "cash-owner-other", "field": field}])
            self.assertFalse(result["all_fields_match"])

    def test_order_and_decimal_format_do_not_change_score(self):
        response = deepcopy(KEY)
        response["answers"].reverse()
        response["answers"][0]["free_cash"] = "0.0600"
        self.assertTrue(scorer.score(response, KEY)["all_fields_match"])

    def test_missing_duplicate_extra_and_invalid_values_fail_closed(self):
        variants = []
        missing = deepcopy(KEY)
        missing["answers"].pop()
        variants.append(missing)
        duplicate = deepcopy(KEY)
        duplicate["answers"][-1] = deepcopy(duplicate["answers"][0])
        variants.append(duplicate)
        extra = deepcopy(KEY)
        extra["answers"][0]["id"] = "unknown-case"
        variants.append(extra)
        for field, value in (("free_cash", "NaN"), ("free_cash", "Infinity"),
                             ("free_cash", "-0.01"), ("free_cash", 0.0),
                             ("additional_calls", True), ("prospective_calls", -1),
                             ("first_failing_gate", True)):
            response = deepcopy(KEY)
            response["answers"][0][field] = value
            variants.append(response)
        for response in variants:
            with self.subTest(response=response["answers"][0]):
                with self.assertRaises(ValueError):
                    scorer.score(response, KEY)

    def test_cli_exit_codes_and_duplicate_json_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "response.json"
            def run(text):
                path.write_text(text, encoding="utf-8")
                return subprocess.run([sys.executable, str(ROOT / "tools/score_reservation_fixtures.py"),
                                       "--responses", str(path)], capture_output=True, text=True)
            self.assertEqual(run(json.dumps(KEY)).returncode, 0)
            wrong = deepcopy(KEY)
            wrong["answers"][0]["all_in_bound"] = "0.03"
            mismatch = run(json.dumps(wrong))
            self.assertEqual(mismatch.returncode, 1)
            self.assertIn('"field": "all_in_bound"', mismatch.stdout)
            for text in ('{"schema_version":1,"schema_version":1,"answers":[]}', "PRIVATE_INVALID_SOURCE"):
                rejected = run(text)
                self.assertEqual(rejected.returncode, 2)
                self.assertNotIn(text, rejected.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
