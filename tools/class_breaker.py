#!/usr/bin/env python3
"""Class-level circuit breaker — failure tracking that runs under eval-prep, not routing.

HITL §9.6 flag 3: a class-level escalation rate (">30%") is aggregated data, and
brief-and-result.md reserves above-attempt statistics for the separately authorized
evaluation flow (`smart-router-eval-prep`) — never per-task routing. A host that
recomputes class rates inline, on every task, launders evaluation into routing:
thresholds drift per task, samples are whatever happened to run lately, and no owner
ever approved the gate change. This tool is the split, executable:

  * Per-task path (always allowed): `record` appends one attempt-level FACT
    (task id, class, outcome) to the Outcome Ledger, and `gate` reads the
    currently PUBLISHED effective gate table. No rates are computed here — the
    table is an input, exactly like prices-2.json is to the dispatcher.
  * Evaluation path (separately authorized): `recompute` reads a ledger window,
    computes per-class escalation rates, and publishes a new gate-table version —
    but ONLY with a valid evaluation authorization (frozen window, minimum
    samples, frozen threshold, raise-to gate, owner approval with name+date).
    Without it the run refuses fail-closed (exit 2) instead of adjusting anything.

Ledger lines (JSONL): {"task-id","class","outcome","ts"} where outcome is
`accepted` or `needs-human` (other terminal outcomes count as non-escalated).
Gate table (JSON): {"version": N, "classes": {class: HumanGate}, ...}.
Auth doc (JSON): {"window": N, "min_samples": N, "threshold": 0..1,
"raise_to": HumanGate, "approved_by": name, "approved_at": ISO date}.

Exit codes: 0 decided/published (report printed whether or not the table changed);
2 fail-closed (bad auth, unreadable ledger/table, malformed lines).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HUMANGATES = ("none", "review-before-merge", "review-before-dispatch", "approval-required")
ESCALATED = "needs-human"


class FailClosed(RuntimeError):
    """Refuse to decide — never adjust routing on incomplete authority or data."""


# ------------------------------------------------------------------ facts (per-task)

def record(ledger_path: Path, *, task_id: str, task_class: str, outcome: str) -> dict:
    if not task_id or not task_class or not outcome:
        raise FailClosed("record needs task-id, class, and outcome")
    entry = {"task-id": task_id, "class": task_class, "outcome": outcome, "ts": time.time()}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def read_ledger(ledger_path: Path) -> list[dict]:
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
        if not all(k in doc for k in ("task-id", "class", "outcome")):
            raise FailClosed(f"ledger line {i} lacks task-id/class/outcome")
        entries.append(doc)
    return entries


# ------------------------------------------------------------------ table (per-task read)

def load_table(table_path: Path) -> dict:
    try:
        doc = json.loads(table_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise FailClosed(f"gate table {table_path} unreadable ({e})") from e
    except json.JSONDecodeError as e:
        raise FailClosed(f"gate table {table_path} malformed ({e})") from e
    if not isinstance(doc.get("classes"), dict):
        raise FailClosed(f"gate table {table_path} lacks a 'classes' object")
    return doc


def effective_gate(table: dict, task_class: str, default: str | None = None, *,
                   human_requested: bool = False) -> str:
    """The gate routing enforces for one task: a table LOOKUP, never a computation."""
    fallback = default if default is not None else ("review-before-merge" if human_requested else "none")
    gate = table.get("classes", {}).get(task_class, fallback)
    if gate not in HUMANGATES:
        raise FailClosed(f"published gate {gate!r} for class {task_class!r} is not a HumanGate")
    return gate if human_requested else "none"


# ------------------------------------------------------------------ evaluation (authorized only)

def load_auth(auth_path: Path) -> dict:
    try:
        doc = json.loads(auth_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise FailClosed(f"auth {auth_path} unreadable ({e})") from e
    except json.JSONDecodeError as e:
        raise FailClosed(f"auth {auth_path} malformed ({e})") from e
    for key in ("window", "min_samples", "threshold", "raise_to", "approved_by", "approved_at"):
        if key not in doc or doc[key] in (None, ""):
            raise FailClosed(f"auth {auth_path} lacks {key!r} — refusing to recompute "
                             f"(evaluation needs frozen params + owner approval)")
    if not isinstance(doc["window"], int) or doc["window"] <= 0:
        raise FailClosed("auth 'window' must be a positive int (newest N outcomes)")
    if not isinstance(doc["min_samples"], int) or doc["min_samples"] <= 0:
        raise FailClosed("auth 'min_samples' must be a positive int")
    if not isinstance(doc["threshold"], (int, float)) or not 0 < doc["threshold"] < 1:
        raise FailClosed("auth 'threshold' must be a rate in (0, 1)")
    if doc["raise_to"] not in HUMANGATES:
        raise FailClosed(f"auth 'raise_to' {doc['raise_to']!r} is not a HumanGate")
    return doc


def recompute(entries: list[dict], auth: dict, table: dict) -> tuple[dict, dict]:
    """(new_table, report). Raises FailClosed only on programmer error (validated upstream)."""
    window = entries[-auth["window"]:]
    by_class: dict[str, list[dict]] = {}
    for e in window:
        by_class.setdefault(str(e["class"]), []).append(e)
    report: dict[str, dict] = {}
    new_classes = dict(table.get("classes", {}))
    for cls in sorted(by_class):
        group = by_class[cls]
        n = len(group)
        esc = sum(1 for e in group if e["outcome"] == ESCALATED)
        rate = esc / n
        if n < auth["min_samples"]:
            report[cls] = {"n": n, "escalated": esc, "rate": round(rate, 4),
                           "decision": "insufficient-evidence (table unchanged)"}
            continue
        if rate > auth["threshold"]:
            new_classes[cls] = auth["raise_to"]
            report[cls] = {"n": n, "escalated": esc, "rate": round(rate, 4),
                           "decision": f"raised to {auth['raise_to']}"}
        else:
            report[cls] = {"n": n, "escalated": esc, "rate": round(rate, 4),
                           "decision": "within threshold (table unchanged)"}
    new_table = dict(table)
    new_table["classes"] = new_classes
    return new_table, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Class-level breaker: facts per task, rates only under eval auth.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="append one attempt-level fact to the ledger")
    r.add_argument("--ledger", type=Path, required=True)
    r.add_argument("--task-id", required=True)
    r.add_argument("--class", dest="task_class", required=True)
    r.add_argument("--outcome", required=True)
    c = sub.add_parser("recompute", help="recompute class rates under eval auth; publish table")
    c.add_argument("--ledger", type=Path, required=True)
    c.add_argument("--auth", type=Path, required=True)
    c.add_argument("--table", type=Path, required=True, help="current published gate table")
    c.add_argument("--out", type=Path, required=True, help="where to write the new table version")
    g = sub.add_parser("gate", help="look up the published gate for one class (routing path)")
    g.add_argument("--table", type=Path, required=True)
    g.add_argument("--class", dest="task_class", required=True)
    g.add_argument("--human-requested", action="store_true",
                   help="apply the published human gate only on explicit user request")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "record":
            entry = record(args.ledger, task_id=args.task_id,
                           task_class=args.task_class, outcome=args.outcome)
            print(f"class_breaker: recorded {entry['class']}/{entry['outcome']}")
            return 0
        if args.cmd == "gate":
            print(effective_gate(load_table(args.table), args.task_class,
                                 human_requested=args.human_requested))
            return 0
        table = load_table(args.table)
        auth = load_auth(args.auth)
        new_table, report = recompute(read_ledger(args.ledger), auth, table)
        new_table["version"] = int(table.get("version", 0)) + 1
        new_table["updated_by"] = f"eval auth {auth['approved_by']} {auth['approved_at']}"
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(new_table, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
        changed = [c for c, r in report.items() if r["decision"].startswith("raised")]
        print(f"class_breaker: {len(report)} classe(s), raised: {changed or 'none'}")
        for cls, rep in report.items():
            print(f"  {cls}: n={rep['n']} escalated={rep['escalated']} "
                  f"rate={rep['rate']} → {rep['decision']}")
        return 0
    except FailClosed as e:
        print(f"class_breaker: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
