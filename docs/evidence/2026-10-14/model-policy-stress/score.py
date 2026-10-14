"""Replay frozen scalar expectations; object conformance is reported separately.

Run from any directory. This is a small descriptive comparison, not model
qualification. Packet/key hashes are checked after portable LF normalization.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import conform_spec as cs


def equal(actual, expected):
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and set(actual) == set(expected)
                and all(equal(actual[k], v) for k, v in expected.items()))
    if expected is None or type(expected) is bool:
        return actual is expected
    return type(actual) is type(expected) and actual == expected


def grade(answers, expected):
    ids = [a['id'] for a in answers]
    if len(ids) != len(set(ids)) or set(ids) != {e['id'] for e in expected}:
        raise ValueError('response case IDs missing, duplicated or unexpected')
    actual = {a['id']: a for a in answers}
    mismatches = []
    correct_cases = policy_correct = code_correct = calc_correct = calc_total = 0
    object_checks = []
    for target in expected:
        response = actual[target['id']]
        fields = {k: v for k, v in target.items() if k not in ('id', 'object_requirements')}
        errors = [k for k, v in fields.items() if not equal(response.get(k), v)]
        if response.get('dispatch_performed') is not False:
            errors.append('dispatch_performed')
        if not errors:
            correct_cases += 1
        if target['id'].startswith('N'):
            policy_correct += all(equal(response.get(k), target[k]) for k in
                                  ('route', 'first_failing_gate', 'human_gate', 'proposal_valid'))
        else:
            code_correct += equal(response.get('answer'), target['answer'])
        calc = target.get('calculation')
        if calc:
            for key, value in calc.items():
                if value is not None:
                    calc_total += 1
                    calc_correct += equal((response.get('calculation') or {}).get(key), value)
        if errors:
            mismatches.append({'id': target['id'], 'fields': errors,
                               'expected': fields, 'actual': {k: response.get(k) for k in fields}})
        if target['id'] in ('N10', 'N14'):
            key, checker = ('brief', cs.check_brief) if target['id'] == 'N10' else (
                'speculative_set', cs.check_speculative)
            try:
                checker(response.get(key) or {})
                object_checks.append({'id': target['id'], 'schema_conformant': True})
            except cs.Violation as exc:
                object_checks.append({'id': target['id'], 'schema_conformant': False,
                                      'reason': str(exc)})
    return {'correct_expected_fields_cases': correct_cases, 'cases': len(expected),
            'policy_decisions_correct': policy_correct, 'policy_cases': 18,
            'code_traces_correct': code_correct, 'code_cases': 6,
            'calculation_fields_correct': calc_correct, 'calculation_fields': calc_total,
            'object_schema_checks': object_checks, 'mismatches': mismatches}


def main():
    protocol = json.loads((HERE / 'protocol.json').read_text(encoding='utf-8'))
    def digest(name):
        text = (HERE / name).read_text(encoding='utf-8').replace('\r\n', '\n')
        return hashlib.sha256(text.encode()).hexdigest()
    if digest('answer-key.json') != protocol['answer_key_sha256']:
        raise ValueError('frozen answer key hash mismatch')
    for run, packet in protocol['packets'].items():
        if digest(f'packet-{run}.txt') != packet['sha256']:
            raise ValueError('frozen packet hash mismatch')
    expected = json.loads((HERE / 'answer-key.json').read_text(encoding='utf-8'))['answers']
    results = {}
    for model in ('luna', 'sol', 'astra'):
        for run in (1, 2):
            name = f'{model}-{run}'
            response = json.loads((HERE / f'{name}.json').read_text(encoding='utf-8'))['answers']
            results[name] = grade(response, expected)
    # Negative control: a wrong cash field must lower the score.
    response = json.loads((HERE / 'sol-1.json').read_text(encoding='utf-8'))['answers']
    next(x for x in response if x['id'] == 'N05')['calculation']['free_cash'] = 0.99
    assert grade(response, expected)['correct_expected_fields_cases'] == 23
    print(json.dumps({'frozen_hashes_verified': True, 'negative_control_passed': True,
                      'usage_tokens': None, 'billed_cost': None,
                      'results': results}, indent=2))


if __name__ == '__main__':
    main()
