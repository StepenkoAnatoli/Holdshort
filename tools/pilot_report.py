#!/usr/bin/env python3
"""Pilot report aggregator — ledger → per-task and per-profile aggregates.

Reads the JSON Lines observation ledger written by tools/live_dispatcher.py,
validates accounting against the prices-2 rate sheet and the ratified §5 caps,
and prints aggregates that feed the Phase 4 report fields.

Checks (fail non-zero on violation — fail-closed accounting):
  A. per-task attempts <= §5 cap; per-task and pilot spend <= ceilings
  B. every ledger line's cost recomputes exactly from decided profile rates
     and token counts (accounting completeness — no unauditable spend)
  C. repair-cap credits only actually-dispatched same-profile repairs
  D. block reasons preserved verbatim; nothing silently dropped

Output (to stdout, machine-readable JSON): per-task summary (attempts, spent,
outcome), per-profile totals, pilot totals, plus a §7-relevant readiness block
flagging whether the pilot is complete/incomplete by caps alone. This tool
makes NO promotion decision — decision ∈ {reject, inconclusive, simplify,
promote} stays with the plan §11 predicates and the owner.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

try:
    import pricing
except ImportError:
    from tools import pricing

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "tools" / "prices-2.json"
LEDGER_DEFAULT = REPO_ROOT / "tools" / "pilot_ledger.jsonl"

DISPATCHED = "dispatched"
KNOWN_DECISIONS = {
    "dispatched", "unknown-profile", "blocked-attempt-cap", "blocked-cost-cap",
    "blocked-gate4", "blocked-deadline", "blocked-repair-cap", "blocked-pilot-cap",
    "dispatch-reserved", "dispatch-error", "dispatch-reconciled", "dispatch-cancelled", "verification-complete",
    "blocked-uncertain", "blocked-verified", "blocked:budget-state", "blocked:state-corrupt",
}


def finite_nonnegative(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def entry_problems(entry):
    """Validate ledger inputs before coercion, aggregation, or supersession.

    Null physical usage remains unknown. Invalid usage must never be truncated
    or converted into a zero-cost observation.
    """
    if not isinstance(entry, dict):
        return ["ledger entry must be an object"]
    problems = []
    for field in ("task_id", "profile_id", "decision", "reason"):
        if not isinstance(entry.get(field), str) or (field != "reason" and not entry[field].strip()):
            problems.append(f"{field} must be a string" )
    if not isinstance(entry.get("decision"), str) or entry["decision"] not in KNOWN_DECISIONS:
        problems.append("unknown decision")
    if not finite_nonnegative(entry.get("ts")):
        problems.append("ts must be a finite nonnegative number")
    physical = entry.get("decision") in (DISPATCHED, "dispatch-error", "dispatch-reconciled", "dispatch-reserved")
    for field in ("input_tokens", "output_tokens"):
        value = entry.get(field)
        if value is None and physical:
            continue
        if type(value) is not int or value < 0:
            problems.append(f"{field} must be a nonnegative integer or unknown physical usage")
    for field in ("cost_usd", "known_cost_usd", "reserved_cost_usd", "review_reserved_usd"):
        if field != "cost_usd" and field not in entry:
            continue
        if field == "cost_usd" and entry.get(field) is None and physical:
            continue
        if not finite_nonnegative(entry.get(field)):
            problems.append(f"{field} must be finite and nonnegative")
    if entry.get("reservation_id") is not None and (not isinstance(entry["reservation_id"], str) or not entry["reservation_id"].strip()):
        problems.append("reservation_id must be a nonempty string")
    if "purpose" in entry and entry["purpose"] not in ("work", "verification"):
        problems.append("purpose must be work or verification")
    if not physical and any(entry.get(field) != 0 for field in ("input_tokens", "output_tokens", "cost_usd")):
        problems.append("non-dispatch events must have zero usage and cost")
    if entry.get("decision") == "dispatch-reserved" and any(entry.get(field) is not None for field in ("input_tokens", "output_tokens", "cost_usd")):
        problems.append("a pending reservation must retain unknown usage")
    if entry.get("decision") == "dispatch-reconciled" and any(entry.get(field) is None for field in ("input_tokens", "output_tokens", "cost_usd")):
        problems.append("reconciliation requires complete measured usage and cost")
    return problems


def ledger_problems(entries):
    """Bind reservation transitions before selecting superseding observations."""
    invalid = {}
    reservations = {}
    for idx, event in enumerate(entries, 1):
        errors = entry_problems(event)
        if errors:
            invalid[idx] = errors
            continue
        identifier = event.get("reservation_id")
        if not identifier:
            continue  # legacy entries and non-transport events do not supersede
        decision = event["decision"]
        identity = (event["task_id"], event["profile_id"], event.get("purpose", "work"))
        previous = reservations.get(identifier)
        if decision == "dispatch-reserved":
            if previous is not None:
                invalid[idx] = ["duplicate reservation identifier"]
            else:
                reservations[identifier] = (identity, decision, event.get("known_cost_usd", 0))
            continue
        if previous is None:
            invalid[idx] = ["settlement has no preceding reservation"]
        elif previous[0] != identity:
            invalid[idx] = ["reservation task, profile, or purpose changed"]
        elif not (previous[1] == "dispatch-reserved" and decision in ("dispatched", "dispatch-error", "dispatch-cancelled", "dispatch-reconciled")
                  or previous[1] == "dispatch-error" and decision == "dispatch-reconciled"):
            invalid[idx] = ["invalid or repeated reservation settlement"]
        elif decision == "dispatch-reconciled" and event["cost_usd"] < previous[2]:
            invalid[idx] = ["reconciliation cannot reduce already known charges"]
        else:
            reservations[identifier] = (identity, decision, max(
                previous[2], event.get("known_cost_usd", 0), event.get("cost_usd") or 0))
    return invalid


def effective_entries(entries):
    """A reservation + settlement is one attempt; reconciliation supersedes uncertainty.

    Keep original line numbers. Historical entries without reservation IDs keep
    their original interpretation. Audit events remain in the source ledger.
    """
    invalid = ledger_problems(entries)
    valid = [(i, e) for i, e in enumerate(entries, 1) if i not in invalid]
    finals = {e["reservation_id"]: i for i, e in valid
              if e.get("reservation_id") and e.get("decision") in
              ("dispatched", "dispatch-error", "dispatch-reconciled", "dispatch-cancelled")}
    for i, event in valid:
        identifier = event.get("reservation_id")
        if identifier in finals and i != finals[identifier]:
            continue
        yield i, event


def load_jsonl(path: Path) -> List[dict]:
    if not path.is_file():
        raise SystemExit(f"pilot_report: ledger not found: {path}")
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"pilot_report: corrupt ledger line {i}: {e}")
    return out


def recompute_cost(prices: dict, profile_id: str, in_toks: int, out_toks: int) -> Optional[float]:
    p = prices["profiles"].get(profile_id)
    if p is None:
        return None
    try:
        return pricing.token_cost(p, in_toks, out_toks)
    except (pricing.UnpriceableProfile, ArithmeticError):
        return None  # unauditable: callers already treat None as a problem


def build_report(prices: dict, entries: List[dict]) -> dict:
    caps = prices["pilot_caps"]
    for field in ("max_cost_per_task_usd", "max_cost_per_pilot_usd"):
        if not finite_nonnegative(caps.get(field)):
            raise ValueError(f"invalid pilot cap: {field}")
    for field in ("max_attempts_per_task", "same_profile_repairs_allowed_per_task"):
        if type(caps.get(field)) is not int or caps[field] < 0:
            raise ValueError(f"invalid pilot cap: {field}")
    invalid = ledger_problems(entries)
    problems: List[str] = [f"line {i}: {problem}" for i, findings in invalid.items() for problem in findings]
    pilot_spent_observed = 0.0
    per_task: Dict[str, dict] = {}
    per_profile_spent: Dict[str, float] = defaultdict(float)
    per_profile_dispatches: Dict[str, int] = defaultdict(int)
    repair_credits: Dict[str, int] = defaultdict(int)
    last_profile_by_task: Dict[str, str] = {}

    uncertain_count = 0
    for idx, e in effective_entries(entries):
        tid = e.get("task_id", "<missing>")
        pid = e.get("profile_id", "<missing>")
        dec = e.get("decision", "<missing>")
        if dec not in KNOWN_DECISIONS:
            problems.append(f"line {idx}: unknown decision {dec!r}")

        physical = dec in (DISPATCHED, "dispatch-error", "dispatch-reconciled", "dispatch-reserved")
        unknown = physical and any(e.get(field) is None for field in
                                    ("input_tokens", "output_tokens", "cost_usd"))
        if dec == "verification-complete":
            if (tid in per_task and per_task[tid].get("attempts", 0)
                    and per_task[tid].get("outcome") not in ("usage-unknown", "verified")
                    and per_task[tid].get("uncertain_reserved", 0) == 0):
                per_task[tid]["review_reserved"] = 0.0
                per_task[tid]["outcome"] = "verified"
            else:
                problems.append(f"line {idx}: verification completion has no settled unfinished task")
                invalid[idx] = ["invalid verification transition"]
            continue
        in_t = e.get("input_tokens") or 0
        out_t = e.get("output_tokens") or 0
        cost = float(e.get("known_cost_usd", 0)) if unknown else float(e.get("cost_usd") or 0.0)
        exp = None if unknown else recompute_cost(prices, pid, in_t, out_t)
        if unknown:
            uncertain_count += 1
            problems.append(f"line {idx}: dispatch usage unknown; reservation retained")
            per_profile_spent[pid] += cost

        if exp is None:
            if physical and not unknown:
                problems.append(f"line {idx}: dispatched on unpriced profile {pid!r}")
        else:
            if abs(exp - cost) > 1e-9:
                problems.append(
                    f"line {idx}: cost mismatch — ledger says ${cost:.6f}, rates say ${exp:.6f}"
                )
            if physical:
                per_profile_spent[pid] += exp
        if physical:
            per_profile_dispatches[pid] += 1

        if physical:
            pilot_spent_observed += cost
            st = per_task.setdefault(tid, {
                "task_id": tid, "attempts": 0, "spent": 0.0,
                "last_profile": "", "same_profile_repairs_credited": 0,
                "outcome": "dispatched", "review_reserved": 0.0, "uncertain_reserved": 0.0,
            })
            st["attempts"] += 1
            st["spent"] += cost
            st.setdefault("uncertain_reserved", 0.0)
            st["review_reserved"] = float(e.get("review_reserved_usd", 0))
            if unknown:
                st["uncertain_reserved"] += (max(0, float(e.get("reserved_cost_usd", 0)) - cost)
                                               if e.get("purpose", "work") == "work" else 0)
                st["outcome"] = "usage-unknown"
            elif "usage_status" in e:
                st["outcome"] = "awaiting-verification"
            if (e.get("purpose", "work") == "work" and st["last_profile"] and pid == st["last_profile"]):
                st["same_profile_repairs_credited"] += 1
                repair_credits[tid] += 1
            if e.get("purpose", "work") == "work":
                st["last_profile"] = pid

            if st["attempts"] > caps["max_attempts_per_task"]:
                problems.append(
                    f"line {idx}: task {tid} exceeded attempt cap"
                    f" ({st['attempts']} > {caps['max_attempts_per_task']})"
                )
            if st["spent"] > caps["max_cost_per_task_usd"] + 1e-9:
                problems.append(
                    f"line {idx}: task {tid} spent ${st['spent']:.4f} above"
                    f" ${caps['max_cost_per_task_usd']:.2f}"
                )
        else:
            if tid in per_task:
                per_task[tid]["outcome"] = "blocked:" + ("cap" if "cap" in dec else "gate")
                per_task[tid]["review_reserved"] = float(e.get("review_reserved_usd", per_task[tid].get("review_reserved", 0)))
            else:
                per_task[tid] = {
                    "task_id": tid, "attempts": 0, "spent": 0.0,
                    "last_profile": "", "same_profile_repairs_credited": 0,
                    "outcome": "blocked:" + ("cap" if "cap" in dec else "gate"),
                }
        if a := e.get("reason", ""):
            if len(a) > 512:
                problems.append(f"line {idx}: reason field exceeds 512 chars (ledger truncation drift)")
        if "reason" not in e:
            problems.append(f"line {idx}: missing reason field")

        if st_last := per_task.get(tid, {}).get("last_profile"):
            last_profile_by_task[tid] = st_last

    if pilot_spent_observed > caps["max_cost_per_pilot_usd"] + 1e-9:
        problems.append(
            f"pilot spend ${pilot_spent_observed:.4f} above cap ${caps['max_cost_per_pilot_usd']:.2f}"
        )

    for tid, st in per_task.items():
        if st["same_profile_repairs_credited"] > caps["same_profile_repairs_allowed_per_task"]:
            problems.append(
                f"task {tid}: {st['same_profile_repairs_credited']} same-profile repairs credited"
                f" > allowance {caps['same_profile_repairs_allowed_per_task']}"
            )

    return {
        "per_task": [
            {k: v for k, v in st.items() if k != "last_profile"}
            for st in per_task.values()
        ],
        "per_profile": {
            pid: {"dispatch_count": per_profile_dispatches[pid], "spend_usd": round(v, 6)}
            for pid, v in sorted(per_profile_spent.items())
        },
        "pilot": {
            "tasks": len(per_task),
            "dispatches": sum(per_profile_dispatches.values()),
            "total_spend_usd": round(pilot_spent_observed, 6),
            "total_spend_complete": uncertain_count == 0 and not invalid,
            "invalid_ledger_lines": sorted(invalid),
            "unknown_usage_dispatches": uncertain_count,
            "reserved_usd": round(sum(st.get("review_reserved", 0) + st.get("uncertain_reserved", 0)
                                      for st in per_task.values()), 6),
            "caps": {
                "max_attempts_per_task": caps["max_attempts_per_task"],
                "max_cost_per_task_usd": caps["max_cost_per_task_usd"],
                "max_cost_per_pilot_usd": caps["max_cost_per_pilot_usd"],
            },
        },
        "accounting_status": "intact" if not problems else "GAPS_FOUND",
        "problems": problems,
        "_note": "This tool reports accounting; the §7/§11 decision field (reject/inconclusive/"
                 "simplify/promote) is NOT made here — it needs the plan predicates and the owner.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Aggregate the pilot observation ledger")
    ap.add_argument("--prices", default=str(PRICES_PATH))
    ap.add_argument("--ledger", default=str(LEDGER_DEFAULT))
    args = ap.parse_args(argv)

    prices = json.loads(Path(args.prices).read_text(encoding="utf-8"))
    if prices.get("revision") != "prices-2":
        print("pilot_report: unexpected prices revision — stop", file=sys.stderr)
        return 2
    entries = load_jsonl(Path(args.ledger))
    if not entries:
        print("pilot_report: ledger is empty — nothing to report", file=sys.stderr)
        return 2
    report = build_report(prices, entries)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["accounting_status"] == "intact" else 1


if __name__ == "__main__":
    sys.exit(main())
