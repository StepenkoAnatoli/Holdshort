#!/usr/bin/env python3
"""Spec §10 conformance checker — validate host-emitted objects, fail on §12 breaches.

A host that emits a malformed Brief (missing acceptance, invented isolation level) or a
NestedBrief wider than its parent's remaining allowance is already violating §12
(dispatch under unknown/missing accounting, weaker isolation, unobserved evidence) by
the time anything runs. This checker proves the objects BEFORE dispatch:

  * Brief (§10.1): all keys present with typed values; isolation/nested-allowed enums;
    allowance numbers non-negative; attempts a non-negative int
  * SpeculativeSet (§10.2): at least two distinct profiles; bounded integer
    parallelism; finite non-negative cash and integer calls; winner-owns true
  * Outcome (§10.3): via tools/outcome_ledger.validate (the canonical Outcome schema)
  * NestedBrief (§10.4 + bound rules against --parent-brief / --parent-state):
    sub-allowance within parent REMAINING cash/calls, deadline at/before parent's,
    attempts within remaining, effects subset, isolation >= parent's, depth = parent
    depth + 1 within max, nested-allowed false at max depth, ownership parent-worker
  * LedgerRecord (§10.5): kind enum; counters non-negative with
    repairs-used <= repairs-allowed; ISO datetimes parse where given
  * Route/object agreement (§12): `delegate` without a Brief, `speculative` without a
    SpeculativeSet, acceptance with zero checks, or isolation weaker than
    --recommended-isolation are VIOLATIONS, not warnings

Exit 0 conformant; 1 violation (first breach named, with the §12 rule it breaks);
2 fail-closed (unreadable/malformed JSON, or a NestedBrief offered without the parent
context needed to verify its bounds — unverifiable is never "conformant").
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import math
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ol = _load("oll_conform", TOOLS / "outcome_ledger.py")

ISOLATION = ["none", "directory", "worktree+branch", "ephemeral-container"]
CANCEL = ("first-success", "budget-exhausted", "all-fail")
KINDS = ("decision", "dispatch", "outcome", "spend", "escalation")


class FailClosed(RuntimeError):
    pass


class Violation(RuntimeError):
    pass


def _is_num(x) -> bool:
    if type(x) not in (int, float):
        return False
    try:
        return math.isfinite(x)
    except OverflowError:
        return False


def load_json(path: Path, what: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise FailClosed(f"{what} {path} unreadable ({e})") from e
    except json.JSONDecodeError as e:
        raise FailClosed(f"{what} {path} malformed ({e})") from e
    if not isinstance(doc, dict):
        raise FailClosed(f"{what} {path} must be an object")
    return doc


def _iso_ok(value: str, where: str) -> None:
    if value not in ISOLATION:
        raise Violation(f"{where}: isolation {value!r} outside §6 lattice {ISOLATION}")


def _iso_level(value: str, where: str) -> int:
    _iso_ok(value, where)
    return ISOLATION.index(value)


def check_brief(doc: dict) -> None:
    for key in ("objective", "acceptance", "sources", "permitted-effects", "non-goals",
                "isolation", "branch-hint", "allowance", "attempts", "stop-triggers",
                "ownership", "nested-allowed", "max-nesting-depth"):
        if key not in doc:
            raise Violation(f"Brief lacks §10.1 key {key!r}")
    _iso_ok(doc["isolation"], "Brief")
    checks = doc["acceptance"].get("checks") if isinstance(doc["acceptance"], dict) else None
    if not isinstance(checks, list) or not checks:
        raise Violation("Brief acceptance has zero checks (§12: no completion claim "
                        "without observed evidence; Gate 3 needs the contract before start)")
    for c in checks:
        if not isinstance(c, dict) or "command" not in c or "expect" not in c:
            raise Violation("Brief acceptance checks need command + expect (§10.1)")
    al = doc["allowance"]
    if not isinstance(al, dict):
        raise Violation("Brief allowance must be an object")
    for key in ("cash", "calls", "deadline"):
        if key not in al:
            raise Violation(f"Brief allowance lacks {key!r}")
    if (not _is_num(al["cash"]) or al["cash"] < 0
            or type(al["calls"]) is not int or al["calls"] < 0):
        raise Violation("Brief allowance needs finite non-negative cash and integer calls")
    _iso_datetime(al["deadline"], "Brief allowance.deadline")
    if not isinstance(doc["attempts"], int) or isinstance(doc["attempts"], bool) or doc["attempts"] < 0:
        raise Violation("Brief attempts must be a non-negative int")
    if not isinstance(doc["nested-allowed"], bool):
        raise Violation("Brief nested-allowed must be true/false")
    if doc["max-nesting-depth"] not in (0, 1, 2):
        raise Violation("Brief max-nesting-depth must be 0, 1, or 2")
    if type(doc["max-nesting-depth"]) is not int:
        raise Violation("Brief max-nesting-depth must be an integer")
    if doc["ownership"] != "worker":
        raise Violation("Brief ownership must be worker")
    for key in ("sources", "permitted-effects", "non-goals", "stop-triggers"):
        if not isinstance(doc[key], list) or any(not isinstance(x, str) for x in doc[key]):
            raise Violation(f"Brief {key} must be a list of strings")


def _iso_datetime(value, where: str) -> None:
    if not isinstance(value, str):
        raise Violation(f"{where} must be an ISO-8601 datetime string")
    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise Violation(f"{where} {value!r} is not ISO-8601 ({e})") from e


def check_speculative(doc: dict) -> None:
    cands = doc.get("candidates")
    if not isinstance(cands, list) or len(cands) < 2:
        raise Violation("SpeculativeSet needs at least two eligible candidates (§8.4)")
    for c in cands:
        if not isinstance(c, dict) or not isinstance(c.get("profile"), str) or not c["profile"].strip():
            raise Violation("SpeculativeSet candidates need profile strings")
        if 'weight' in c and (not _is_num(c['weight']) or c['weight'] <= 0):
            raise Violation("SpeculativeSet weights must be positive finite numbers")
    if len({c['profile'] for c in cands}) != len(cands):
        raise Violation("SpeculativeSet candidates must have distinct profiles")
    parallel = doc.get('max-parallel')
    if type(parallel) is not int or not 2 <= parallel <= len(cands):
        raise Violation("SpeculativeSet max-parallel must be an integer from 2 to candidate count")
    sb = doc.get("shared-budget", {})
    if not isinstance(sb, dict) or not _is_num(sb.get("cash")) or sb["cash"] < 0 or \
       type(sb.get("calls")) is not int or sb["calls"] < 0:
        raise Violation("SpeculativeSet budget needs finite non-negative cash and integer calls")
    if doc.get("cancel-policy") not in CANCEL:
        raise Violation(f"SpeculativeSet cancel-policy must be one of {list(CANCEL)}")
    if doc.get("winner-owns") is not True:
        raise Violation("SpeculativeSet winner-owns must be true (§8.4)")


def check_outcome(doc: dict) -> None:
    try:
        ol.validate(doc)
    except ol.FailClosed as e:
        raise Violation(f"Outcome breaks §10.3 ({e})") from e


def check_nested(doc: dict, parent_brief: dict | None, parent_state: dict | None) -> None:
    for key in ("parent-task-id", "parent-brief-fingerprint", "nesting-depth",
                "max-nesting-depth", "objective", "acceptance", "permitted-effects",
                "non-goals", "isolation", "allowance", "attempts", "ownership",
                "nested-allowed"):
        if key not in doc:
            raise Violation(f"NestedBrief lacks §10.4 key {key!r}")
    if doc["ownership"] != "parent-worker":
        raise Violation("NestedBrief ownership must stay the parent worker (§8.3/§10.4)")
    if not isinstance(doc["nested-allowed"], bool):
        raise Violation("NestedBrief nested-allowed must be true/false")
    if doc["nesting-depth"] != parent_depth(parent_state) + 1:
        raise Violation("NestedBrief nesting-depth must be parent depth + 1")
    if doc["nesting-depth"] > doc["max-nesting-depth"]:
        raise Violation("NestedBrief depth exceeds max-nesting-depth (§10.4)")
    if doc["nesting-depth"] == doc["max-nesting-depth"] and doc["nested-allowed"]:
        raise Violation("NestedBrief at max depth must set nested-allowed false")
    if parent_brief is None or parent_state is None:
        raise FailClosed("NestedBrief offered without --parent-brief/--parent-state: "
                         "sub-allowance bounds are unverifiable, never assumed")
    _iso_ok(doc["isolation"], "NestedBrief")
    if _iso_level(doc["isolation"], "NestedBrief") < _iso_level(
            parent_brief.get("isolation", "none"), "parent Brief"):
        raise Violation("NestedBrief isolation weaker than the parent's (§10.4)")
    rem = parent_state
    for key in ("cash", "calls"):
        if key not in rem:
            raise FailClosed(f"parent-state lacks remaining {key!r}")
    if doc["allowance"]["cash"] > rem["cash"] or doc["allowance"]["calls"] > rem["calls"]:
        raise Violation("NestedBrief allowance exceeds the parent's REMAINING allowance (§10.4)")
    if doc["allowance"]["deadline"] > parent_brief["allowance"]["deadline"]:
        raise Violation("NestedBrief deadline past the parent's deadline (§10.4)")
    if doc["attempts"] > rem.get("attempts", doc["attempts"]):
        raise Violation("NestedBrief attempts exceed the parent's remaining attempts")
    uncovered = [e for e in doc["permitted-effects"]
                 if e not in parent_brief.get("permitted-effects", [])]
    if uncovered:
        raise Violation(f"NestedBrief effects outside the parent's: {uncovered[:5]} (§10.4)")


def parent_depth(state: dict | None) -> int:
    if state is None:
        return 1  # top-level Brief is depth 1; checked structurally elsewhere
    d = state.get("depth", 1)
    if not isinstance(d, int) or d < 1:
        raise FailClosed("parent-state depth must be a positive int")
    return d


def check_record(doc: dict) -> None:
    for key in ("task-id", "seq", "kind", "ts", "counters", "detail"):
        if key not in doc:
            raise Violation(f"LedgerRecord lacks §10.5 key {key!r}")
    if doc["kind"] not in KINDS:
        raise Violation(f"LedgerRecord kind {doc['kind']!r} outside {list(KINDS)}")
    if not isinstance(doc["seq"], int) or isinstance(doc["seq"], bool) or doc["seq"] < 1:
        raise Violation("LedgerRecord seq starts at 1 and strictly increases")
    _iso_datetime(doc["ts"], "LedgerRecord ts")
    c = doc["counters"]
    for key in ("calls-used", "calls-limit", "cash-spent", "cash-cap",
                "repairs-used", "repairs-allowed"):
        if key not in c or not _is_num(c[key]) or c[key] < 0:
            raise Violation(f"LedgerRecord counters.{key} must be a non-negative number")
    if c["repairs-used"] > c["repairs-allowed"]:
        raise Violation("LedgerRecord repairs-used exceeds repairs-allowed (§10.5)")
    if doc.get("deadline") is not None:
        _iso_datetime(doc["deadline"], "LedgerRecord deadline")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate §10 objects; fail on §12 breaches.")
    ap.add_argument("--route", default=None,
                    choices=["direct", "delegate", "speculative", "recommend-escalation", "blocked"])
    ap.add_argument("--brief", type=Path, default=None)
    ap.add_argument("--speculative", type=Path, default=None)
    ap.add_argument("--outcome", type=Path, default=None)
    ap.add_argument("--nested", type=Path, default=None)
    ap.add_argument("--record", type=Path, default=None)
    ap.add_argument("--parent-brief", type=Path, default=None)
    ap.add_argument("--parent-state", type=Path, default=None)
    ap.add_argument("--recommended-isolation", default=None, choices=ISOLATION)
    args = ap.parse_args(argv)
    try:
        brief = load_json(args.brief, "Brief") if args.brief else None
        if args.route == "delegate" and brief is None:
            raise Violation("route is delegate but no Brief emitted (§12: never dispatch "
                            "delegation without its machine-readable object, §9)")
        if args.route == "speculative" and args.speculative is None:
            raise Violation("route is speculative but no SpeculativeSet emitted (§9/§12)")
        if brief is not None:
            check_brief(brief)
            if args.recommended_isolation and \
               _iso_level(brief["isolation"], "Brief") < _iso_level(
                   args.recommended_isolation, "recommended"):
                raise Violation(f"Brief isolation {brief['isolation']!r} weaker than "
                                f"recommended {args.recommended_isolation!r} (§12/§6)")
        if args.speculative is not None:
            check_speculative(load_json(args.speculative, "SpeculativeSet"))
        if args.outcome is not None:
            check_outcome(load_json(args.outcome, "Outcome"))
        if args.nested is not None:
            nested = load_json(args.nested, "NestedBrief")
            pb = load_json(args.parent_brief, "parent Brief") if args.parent_brief else None
            ps = load_json(args.parent_state, "parent state") if args.parent_state else None
            if pb is not None:
                check_brief(pb)
            check_nested(nested, pb, ps)
        if args.record is not None:
            check_record(load_json(args.record, "LedgerRecord"))
        parts = [p for p in ("brief" if brief is not None else None,
                             "speculative" if args.speculative else None,
                             "outcome" if args.outcome else None,
                             "nested" if args.nested else None,
                             "record" if args.record else None) if p]
        print(f"conform_spec: CONFORMANT ({', '.join(parts) or 'route-only agreement'})")
        return 0
    except Violation as e:
        print(f"conform_spec: VIOLATION — {e}", file=sys.stderr)
        return 1
    except FailClosed as e:
        print(f"conform_spec: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
