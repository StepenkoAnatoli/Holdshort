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
}


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
    except pricing.UnpriceableProfile:
        return None  # unauditable: callers already treat None as a problem


def build_report(prices: dict, entries: List[dict]) -> dict:
    caps = prices["pilot_caps"]
    problems: List[str] = []
    pilot_spent_observed = 0.0
    per_task: Dict[str, dict] = {}
    per_profile_spent: Dict[str, float] = defaultdict(float)
    per_profile_dispatches: Dict[str, int] = defaultdict(int)
    repair_credits: Dict[str, int] = defaultdict(int)
    last_profile_by_task: Dict[str, str] = {}

    for idx, e in enumerate(entries, 1):
        tid = e.get("task_id", "<missing>")
        pid = e.get("profile_id", "<missing>")
        dec = e.get("decision", "<missing>")
        if dec not in KNOWN_DECISIONS:
            problems.append(f"line {idx}: unknown decision {dec!r}")

        in_t, out_t = int(e.get("input_tokens", 0)), int(e.get("output_tokens", 0))
        cost = float(e.get("cost_usd", 0.0))
        exp = recompute_cost(prices, pid, in_t, out_t)

        if exp is None:
            if dec == DISPATCHED:
                problems.append(f"line {idx}: dispatched on unpriced profile {pid!r}")
        else:
            if abs(exp - cost) > 1e-9:
                problems.append(
                    f"line {idx}: cost mismatch — ledger says ${cost:.6f}, rates say ${exp:.6f}"
                )
            if dec == DISPATCHED:
                per_profile_spent[pid] += exp
                per_profile_dispatches[pid] += 1

        if dec == DISPATCHED:
            pilot_spent_observed += cost
            st = per_task.setdefault(tid, {
                "task_id": tid, "attempts": 0, "spent": 0.0,
                "last_profile": "", "same_profile_repairs_credited": 0,
                "outcome": "dispatched",
            })
            st["attempts"] += 1
            st["spent"] += cost
            if st["last_profile"] and pid == st["last_profile"]:
                st["same_profile_repairs_credited"] += 1
                repair_credits[tid] += 1
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
