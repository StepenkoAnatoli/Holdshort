#!/usr/bin/env python3
"""Score synthetic reservation answers against a separate, static decimal key.

No provider calls or production dispatch. Exit 0 for agreement, 1 for a valid
answer with wrong fields, and 2 for malformed or unreadable evidence.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/reservation-comparison"
CASH_FIELDS = ("free_cash", "all_in_bound", "additional_cash")
CALL_FIELDS = ("additional_calls", "prospective_calls")
FIELDS = ("id", "route", "first_failing_gate") + CASH_FIELDS + CALL_FIELDS


def decimal_cash(value):
    if not isinstance(value, str):
        raise ValueError("cash fields must be decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal cash") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("cash must be finite and nonnegative")
    return number


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def validate_answers(document):
    if (not isinstance(document, dict) or set(document) != {"schema_version", "answers"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or not isinstance(document["answers"], list) or not document["answers"]):
        raise ValueError("invalid response envelope")
    indexed = {}
    for answer in document["answers"]:
        if not isinstance(answer, dict) or set(answer) != set(FIELDS):
            raise ValueError("invalid answer fields")
        identifier = answer["id"]
        if not isinstance(identifier, str) or not identifier or identifier in indexed:
            raise ValueError("missing or duplicate case ID")
        if answer["route"] not in ("direct", "blocked"):
            raise ValueError("invalid route")
        gate = answer["first_failing_gate"]
        if gate is not None and (type(gate) is not int or not 1 <= gate <= 5):
            raise ValueError("invalid gate")
        for field in CASH_FIELDS:
            decimal_cash(answer[field])
        for field in CALL_FIELDS:
            if type(answer[field]) is not int or answer[field] < 0:
                raise ValueError("calls must be nonnegative integers")
        indexed[identifier] = answer
    return indexed


def score(response, answer_key):
    actual = validate_answers(response)
    expected = validate_answers(answer_key)
    if set(actual) != set(expected):
        raise ValueError("response must contain every expected case ID exactly once")
    mismatches = []
    matching_cases = 0
    for identifier, wanted in expected.items():
        errors = []
        for field in FIELDS[1:]:
            got, target = actual[identifier][field], wanted[field]
            if field in CASH_FIELDS:
                got, target = decimal_cash(got), decimal_cash(target)
            if got != target:
                errors.append(field)
                mismatches.append({"id": identifier, "field": field})
        matching_cases += not errors
    return {"case_count": len(expected), "matching_cases": matching_cases,
            "mismatches": mismatches, "all_fields_match": not mismatches}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--answer-key", type=Path, default=FIXTURES / "answer-key.json")
    args = parser.parse_args(argv)
    try:
        result = score(read_json(args.responses), read_json(args.answer_key))
    except (OSError, ValueError, TypeError, InvalidOperation):
        print("reservation scorer: malformed or unreadable evidence", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["all_fields_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
