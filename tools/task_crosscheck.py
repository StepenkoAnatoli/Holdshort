#!/usr/bin/env python3
"""Compare dispatch accounting with persisted task and ledger mirrors.

When a budget authority exists, inspect its committed snapshot read-only and
report mirror lag, divergence, corrupt state, or counter disagreement. Reading
must neither recover receipts nor create or rewrite any accounting files.
Optional mirrors may be absent; their absence never erases authority charges.

Without an authority, retain the weaker legacy comparison: task state must
cover known ledger spend and physical attempts. Unknown or invalid accounting
remains a finding; extra state attempts alone cannot prove a lost send.

Exit 0 only when consistent, 1 for findings, and 2 for unavailable inputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
import pilot_report as pr  # noqa: E402


def state_view(state_dir: Path, *, problems=None) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not state_dir.is_dir():
        return out
    for p in sorted(state_dir.glob("*.json")):
        if p.name == ".dispatch-budget-owner.json":
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError):
            doc = None
        if (not isinstance(doc, dict) or not isinstance(doc.get("task_id"), str)
                or not doc["task_id"].strip() or type(doc.get("attempts")) is not int
                or doc["attempts"] < 0 or not pr.finite_nonnegative(doc.get("spent"))):
            if problems is not None:
                problems.append({"task_id": None, "kind": "invalid-task-mirror",
                                 "detail": f"invalid optional task mirror: {p.name}"})
            continue
        out[doc["task_id"]] = doc
    return out


def ledger_view(prices: dict, entries: List[dict]) -> Dict[str, dict]:
    base = pr.build_report(prices, entries)
    return {row["task_id"]: row for row in base["per_task"]}


def check(state_dir: Path, prices: dict, entries: List[dict], *, ledger_path=None) -> dict:
    if ledger_path is not None:
        ledger_path = Path(ledger_path)
        authority_path = ledger_path.with_name(ledger_path.name + ".budget.sqlite3")
        if authority_path.exists():
            return check_authority(state_dir, prices, entries, ledger_path)
    findings: List[dict] = []
    sv = state_view(state_dir, problems=findings)
    lv = ledger_view(prices, entries)
    report = pr.build_report(prices, entries)
    if report["accounting_status"] != "intact":
        findings.append({"task_id": None, "kind": "accounting-gaps", "detail": "; ".join(report["problems"])})

    for task_id, lrow in sorted(lv.items()):
        l_attempts = lrow.get("attempts", 0)
        l_spent = lrow.get("spent", 0.0)
        if l_attempts == 0 and l_spent == 0.0:
            continue  # blocked-only task: no ledger spend to reconcile
        st = sv.get(task_id)
        if st is None:
            # maybe the file exists under the sanitized id but with a different task_id field
            st = None  # malformed mirrors remain findings, never a second unvalidated fallback
        if st is None:
            findings.append({
                "task_id": task_id, "kind": "state-missing",
                "detail": f"ledger has {l_attempts} dispatched attempt(s) / ${l_spent:.6f} "
                          "but no persisted state file — restart crash lost state",
            })
            continue
        if st.get("spent", 0.0) < l_spent - 1e-9:
            findings.append({
                "task_id": task_id, "kind": "spend-under-report",
                "detail": f"state says ${st.get('spent', 0.0):.6f} < ledger ${l_spent:.6f} "
                          "— dispatch recorded but counters not persisted",
            })
        if st.get("attempts", 0) < l_attempts:
            findings.append({
                "task_id": task_id, "kind": "attempts-under-report",
                "detail": f"state says {st.get('attempts', 0)} attempts < ledger {l_attempts}",
            })

    return {"consistent": not findings, "findings": findings,
            "tasks_in_state": sorted(sv), "tasks_in_ledger": sorted(lv),
            "source": "legacy-task-mirrors"}


def check_authority(state_dir, prices, entries, ledger_path):
    """Inspect the authority without replaying mirrors, recovering, or writing."""
    import dispatch_budget as db
    findings = []
    def finding(kind, detail, task_id=None):
        findings.append({"task_id": task_id, "kind": kind, "detail": detail})
    try:
        doc = db.read_authority(ledger_path)
    except db.BudgetStateError:
        return {"consistent": False, "source": "sqlite-authority", "findings": [
            {"task_id": None, "kind": "authority-unreadable", "detail": "authority cannot be validated; preserved"}],
            "tasks_in_state": [], "tasks_in_ledger": []}
    journal = doc["events"]
    if len(entries) > len(journal) or entries != journal[:len(entries)]:
        finding("journal-divergence", "ledger is not a prefix of the authoritative journal")
    elif len(entries) < len(journal):
        finding("mirror-lag", f"ledger omits {len(journal) - len(entries)} committed authority event(s)")
    summary = pr.build_report(prices, journal)
    if summary["accounting_status"] != "intact":
        finding("accounting-gaps", "; ".join(summary["problems"]))
    sv = state_view(state_dir, problems=findings)
    for task_id, task in sorted(doc["tasks"].items()):
        if task.get("pending"):
            finding("unsettled-reservation", "authority retains an unresolved send reservation", task_id)
        st = sv.get(task_id)
        if st is not None and (st.get("attempts") != task["attempts"]
                              or st.get("spent") != float(db.money(task["charged"]))):
            finding("optional-mirror-stale", "optional task mirror differs from authority counters", task_id)
        attempts = max((event.get("attempt_no", 0) or 0 for _, event in pr.effective_entries(journal)
                        if event.get("task_id") == task_id), default=0)
        if task["attempts"] != attempts:
            finding("authority-attempt-mismatch", "attempt counter differs from committed journal", task_id)
    spent, reserved = db.totals(doc)
    return {"consistent": not findings, "source": "sqlite-authority", "findings": findings,
            "tasks_in_state": sorted(doc["tasks"]),
            "tasks_in_ledger": sorted({e["task_id"] for e in entries if isinstance(e, dict) and isinstance(e.get("task_id"), str)}),
            "authority_event_count": len(journal), "ledger_event_count": len(entries),
            "known_spend_usd": float(spent), "reserved_usd": float(reserved),
            "halted": doc.get("halted", False), "overrun": doc.get("overrun", False)}


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-check persisted task state against the pilot ledger")
    ap.add_argument("--state-dir", default=str(REPO_ROOT / "tools" / "task_state"))
    ap.add_argument("--ledger", default=str(REPO_ROOT / "tools" / "pilot_ledger.jsonl"))
    ap.add_argument("--prices", default=str(REPO_ROOT / "tools" / "prices-2.json"))
    args = ap.parse_args(argv)

    prices = json.loads(Path(args.prices).read_text(encoding="utf-8"))
    if prices.get("revision") != "prices-2":
        print("task_crosscheck: unexpected prices revision — stop", file=sys.stderr)
        return 2
    ld = Path(args.ledger)
    authority_exists = ld.with_name(ld.name + ".budget.sqlite3").exists()
    if not ld.is_file() and not authority_exists:
        print(f"task_crosscheck: ledger missing at {ld} — nothing to check", file=sys.stderr)
        return 2
    entries = pr.load_jsonl(ld) if ld.is_file() else []
    if not entries and not authority_exists:
        print("task_crosscheck: ledger is empty — nothing to check", file=sys.stderr)
        return 2

    result = check(Path(args.state_dir), prices, entries, ledger_path=ld)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["findings"]:
        print("task_crosscheck: FINDINGS FOUND — investigate before close (§7 drift rule)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
