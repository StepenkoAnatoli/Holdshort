#!/usr/bin/env python3
"""Outcome Ledger storage — the canonical JSONL store for spec-v2.md §10.3 Outcomes.

Every host in this ecosystem writes Outcomes somewhere (the dry-run harness wrote
ad-hoc dicts, the breaker keeps a class-tagged projection, the dispatcher writes
pilot ledger lines). This tool is the one specified store: a JSONL file with one
spec-v2.md §10.3 Outcome per line, schema-checked on write AND on read, so a
re-routing `PreviousResult` is always shaped the way §8.5/§10.3 promises.

Schema (required): task-id (non-empty string), outcome (one of accepted |
verification-failed | partial | cost-overrun | cancelled | blocked | escalated),
evidence {checks [{command, exit-code, output-ref}], actual-spend (number),
files-touched [string], notes (string)}, owner-profile (non-empty string).
Optional, preserved verbatim: original-brief-fingerprint, class (the breaker's
class tag — recording it here keeps the eval projection derivable from this
ledger), recorded_at (set automatically when absent).

Additive by spec-v2 §13: unknown keys are preserved, never stripped; known keys
with wrong types fail closed. A malformed line never reads as "no outcomes" —
`verify`/`get`/`list` exit 2 instead.

Usage:
    python tools/outcome_ledger.py record --ledger L.jsonl --task-id T --outcome accepted \
        --owner worker --check "pytest tests/x -q:0:out.ref" --spend 0.04 \
        --file src/a.py --note "done" [--class auth] [--fingerprint abc]
    python tools/outcome_ledger.py get --ledger L.jsonl --task-id T   # latest entry
    python tools/outcome_ledger.py list --ledger L.jsonl [--outcome accepted]
    python tools/outcome_ledger.py verify --ledger L.jsonl
Exit 0 decided/found/verified; 1 `get`/`list` found nothing; 2 fail-closed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

OUTCOMES = ("accepted", "verification-failed", "partial", "cost-overrun",
            "cancelled", "blocked", "escalated")


class FailClosed(RuntimeError):
    """The ledger entry or file is not schema-valid — never read it as empty."""


def validate(entry: dict) -> dict:
    """Schema-check one Outcome in place; returns it. Raises FailClosed."""
    if not isinstance(entry, dict):
        raise FailClosed("outcome must be an object")
    for key in ("task-id", "outcome", "evidence", "owner-profile"):
        if key not in entry:
            raise FailClosed(f"outcome lacks required {key!r}")
    for key in ("task-id", "owner-profile"):
        if not isinstance(entry[key], str) or not entry[key].strip():
            raise FailClosed(f"outcome {key} must be a non-empty string")
    if entry["outcome"] not in OUTCOMES:
        raise FailClosed(f"outcome {entry['outcome']!r} not in {list(OUTCOMES)}")
    ev = entry["evidence"]
    if not isinstance(ev, dict):
        raise FailClosed("evidence must be an object")
    for key in ("checks", "actual-spend", "files-touched", "notes"):
        if key not in ev:
            raise FailClosed(f"evidence lacks required {key!r}")
    if not isinstance(ev["checks"], list):
        raise FailClosed("evidence checks must be a list")
    for c in ev["checks"]:
        if not isinstance(c, dict) or not all(k in c for k in ("command", "exit-code", "output-ref")):
            raise FailClosed("every check needs command, exit-code, and output-ref")
        if not isinstance(c["command"], str) or not c["command"].strip():
            raise FailClosed("check command must be a non-empty string")
        if type(c["exit-code"]) is not int:
            raise FailClosed("check exit-code must be an int")
        if not isinstance(c["output-ref"], str):
            raise FailClosed("check output-ref must be a string")
    spend = ev["actual-spend"]
    try:
        valid_spend = type(spend) in (int, float) and math.isfinite(spend) and spend >= 0
    except OverflowError:
        valid_spend = False
    if not valid_spend:
        raise FailClosed("evidence actual-spend must be a finite non-negative number")
    if not isinstance(ev["files-touched"], list) or not all(isinstance(f, str) for f in ev["files-touched"]):
        raise FailClosed("evidence files-touched must be a list of strings")
    if not isinstance(ev["notes"], str):
        raise FailClosed("evidence notes must be a string")
    return entry


def record(ledger_path: Path, entry: dict) -> dict:
    """Validate, stamp, and append one Outcome. Returns the stored entry."""
    stored = dict(validate(entry))
    stored.setdefault("recorded_at", time.time())
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stored, sort_keys=True) + "\n")
    return stored


def read_all(ledger_path: Path) -> list[dict]:
    """Every entry, schema-checked. A malformed line fails the whole read closed."""
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise FailClosed(f"ledger {ledger_path} unreadable ({e})") from e
    entries = []
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError as e:
            raise FailClosed(f"ledger line {i} malformed ({e})") from e
        try:
            entries.append(validate(doc))
        except FailClosed as e:
            raise FailClosed(f"ledger line {i} invalid: {e}") from e
    return entries


def latest_for(entries: list[dict], task_id: str) -> dict | None:
    found = [e for e in entries if e.get("task-id") == task_id]
    return found[-1] if found else None


def parse_check(spec: str) -> dict:
    """'command:exit-code:output-ref' — command may contain colons; split from the right."""
    try:
        command, exit_s, ref = spec.rsplit(":", 2)
        return {"command": command, "exit-code": int(exit_s), "output-ref": ref}
    except ValueError as e:
        raise FailClosed(f"bad --check {spec!r}, want command:exit-code:output-ref") from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canonical spec-v2 §10.3 Outcome Ledger store.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="validate and append one Outcome")
    r.add_argument("--ledger", type=Path, required=True)
    r.add_argument("--task-id", required=True)
    r.add_argument("--outcome", required=True, choices=OUTCOMES)
    r.add_argument("--owner", required=True)
    r.add_argument("--check", action="append", default=[], metavar="CMD:EXIT:REF")
    r.add_argument("--spend", type=float, default=0.0)
    r.add_argument("--file", action="append", default=[], dest="files")
    r.add_argument("--note", default="")
    r.add_argument("--fingerprint", default="")
    r.add_argument("--class", dest="task_class", default="")
    g = sub.add_parser("get", help="print the latest entry for one task")
    g.add_argument("--ledger", type=Path, required=True)
    g.add_argument("--task-id", required=True)
    li = sub.add_parser("list", help="print entries, optionally filtered by outcome")
    li.add_argument("--ledger", type=Path, required=True)
    li.add_argument("--outcome", default=None, choices=OUTCOMES)
    v = sub.add_parser("verify", help="schema-check every line, fail closed on any defect")
    v.add_argument("--ledger", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "record":
            entry: dict = {
                "task-id": args.task_id, "outcome": args.outcome,
                "evidence": {"checks": [parse_check(c) for c in args.check],
                             "actual-spend": args.spend,
                             "files-touched": args.files, "notes": args.note},
                "owner-profile": args.owner,
            }
            if args.fingerprint:
                entry["original-brief-fingerprint"] = args.fingerprint
            if args.task_class:
                entry["class"] = args.task_class
            stored = record(args.ledger, entry)
            print(f"outcome_ledger: recorded {stored['task-id']}/{stored['outcome']}")
            return 0
        entries = read_all(args.ledger)
        if args.cmd == "verify":
            print(f"outcome_ledger: verified {len(entries)} entr(ies), schema §10.3 clean")
            return 0
        if args.cmd == "get":
            found = latest_for(entries, args.task_id)
            if found is None:
                print(f"outcome_ledger: no entry for {args.task_id}", file=sys.stderr)
                return 1
            print(json.dumps(found, indent=2, sort_keys=True))
            return 0
        for e in entries:
            if args.outcome is None or e["outcome"] == args.outcome:
                print(json.dumps(e, sort_keys=True))
        return 0
    except FailClosed as e:
        print(f"outcome_ledger: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
