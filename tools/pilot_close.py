#!/usr/bin/env python3
"""Pilot close generator — per-task closure records + pilot totals for the Phase 4 report.

Reads the same observation ledger as tools/pilot_report.py and produces:
  * per-task closure: total spend, attempts (dispatched count), disposition
    (completed / blocked:cap / blocked:gate / unknown-profile / mixed), and
    whether caps were touched
  * pilot totals: tasks opened, tasks closed, dispatches, blocked dispositions,
    total spend vs. the §5 ceilings, and remaining headroom
  * dual output: machine-readable JSON (default stdout) and a markdown block
    paste-ready for docs/PHASE4_PILOT_REPORT.md (--markdown)

Reuses pilot_report.build_report's accounting validation; if the ledger has
gaps (cost mismatches, cap violations), closure rows are still produced but
flagged `accounting_gap: true` and the tool exits 1 — the §7 accounting rule
says gaps are disclosed, never silenced.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
import pilot_report as pr  # noqa: E402

LEDGER_DEFAULT = REPO_ROOT / "tools" / "pilot_ledger.jsonl"
PRICES_PATH = REPO_ROOT / "tools" / "prices-2.json"
SHEET_DEFAULT = REPO_ROOT / "tools" / "live_fill_sheet.json"
ASSIGNMENTS_DEFAULT = REPO_ROOT / "tools" / "live_fill_assignments.json"


def disposition_of(task_row: dict) -> str:
    outcome = task_row.get("outcome", "")
    if outcome in ("dispatched", "verified"):
        return "completed"
    if isinstance(outcome, str) and outcome.startswith("blocked:"):
        return outcome  # blocked:cap / blocked:gate
    return outcome or "unknown"


def close_ledger(prices: dict, entries: List[dict], *, accounting_report=None) -> dict:
    base = pr.build_report(prices, entries) if accounting_report is None else accounting_report
    caps = base["pilot"]["caps"]
    accounting_gap = base["accounting_status"] != "intact"

    closures: List[dict] = []
    for st in base["per_task"]:
        closed = {
            "task_id": st["task_id"],
            "attempts": st["attempts"],
            "spend_usd": round(st["spent"], 6),
            "spend_complete": st.get("spend_complete", True),
            "review_reserved_usd": round(st.get("review_reserved", 0), 6),
            "uncertain_reserved_usd": round(st.get("uncertain_reserved", 0), 6),
            "last_refusal": st.get("last_refusal"),
            "disposition": disposition_of(st),
            "same_profile_repairs_credited": st.get("same_profile_repairs_credited", 0),
            "within_attempt_cap": st["attempts"] <= caps["max_attempts_per_task"],
            "within_cost_cap": (st["spent"] <= caps["max_cost_per_task_usd"] + 1e-9
                                if st.get("spend_complete", True) else None),
            "accounting_gap": accounting_gap,
        }
        closures.append(closed)

    n_completed = sum(1 for c in closures if c["disposition"] == "completed")
    n_blocked = sum(1 for c in closures if c["disposition"].startswith("blocked"))
    pilot = {
        "tasks_closed": len(closures),
        "completed": n_completed,
        "blocked": n_blocked,
        "dispatches": base["pilot"]["dispatches"],
        "total_spend_usd": base["pilot"]["total_spend_usd"],
        "cap_task_usd": caps["max_cost_per_task_usd"],
        "cap_pilot_usd": caps["max_cost_per_pilot_usd"],
        "reserved_usd": base["pilot"].get("reserved_usd", 0),
        "total_spend_complete": base["pilot"].get("total_spend_complete", True),
        "headroom_usd": (round(caps["max_cost_per_pilot_usd"] - base["pilot"]["total_spend_usd"]
                               - base["pilot"].get("reserved_usd", 0), 6)
                          if base["pilot"].get("reserved_complete", True) else None),
        "within_pilot_cap": (base["pilot"]["total_spend_usd"] <= caps["max_cost_per_pilot_usd"] + 1e-9
                             if base["pilot"].get("total_spend_complete", True) else None),
        "halted": base["pilot"].get("halted", False),
        "reservation_overruns": base["pilot"].get("reservation_overruns", 0),
        "accounting_status": base["accounting_status"],
        "problems": base["problems"],
        "accounting_source": base.get("accounting_source", "provided-ledger"),
        "source_evidence": base.get("source_evidence"),
    }
    return {
        "generator": "tools/pilot_close.py",
        "extends": "docs/PHASE4_PILOT_REPORT.md §2 (per-task evidence ledger)",
        "closures": closures,
        "pilot_totals": pilot,
        "decision_note": "No §7 decision is derived here; closures feed the Phase 4 report only.",
    }


def markdown(closure: dict) -> str:
    rows = ["| Task | Attempts | Spend (USD) | Reserved (USD) | Disposition | Caps OK |",
            "| --- | --- | --- | --- | --- | --- |"]
    for c in closure["closures"]:
        caps_ok = c["within_attempt_cap"] and c["within_cost_cap"]
        spend = f"{c['spend_usd']:.6f}" if c["spend_complete"] else f"known {c['spend_usd']:.6f}; incomplete"
        caps_label = "UNKNOWN" if c["within_cost_cap"] is None else "OK" if caps_ok else "FLAG"
        reserved = c["review_reserved_usd"] + c["uncertain_reserved_usd"]
        rows.append(f"| {c['task_id']} | {c['attempts']} | {spend} | {reserved:.6f} "
                    f"| {c['disposition']} | {caps_label} |")
    p = closure["pilot_totals"]
    headroom = "unknown" if p["headroom_usd"] is None else f"${p['headroom_usd']:.6f}"
    rows.append("")
    rows.append(f"**Pilot totals**: {p['completed']}/{p['tasks_closed']} tasks completed, "
                f"{p['blocked']} blocked; {p['dispatches']} dispatches; "
                f"known spend ${p['total_spend_usd']:.6f} of ${p['cap_pilot_usd']:.2f} "
                f"({'complete' if p['total_spend_complete'] else 'incomplete'}; ${p['reserved_usd']:.6f} reserved); "
                f"(headroom {headroom}); accounting {p['accounting_status']}.")
    if p["halted"]:
        rows.append(f"Pilot stopped: unresolved usage or reservation overrun ({p['reservation_overruns']} overrun(s)).")
    rows.append("_No section-7 decision is derived from this table; see the Phase 4 report's section-4 fields._")
    return "\n".join(rows)


def split_arg(s, sep=":"):
    """'A|T-01:T-03' style is not used here; helper kept minimal."""
    return [x for x in s.split(sep) if x]


def build_sheet_section(entries, assignments: Optional[Dict[str, dict]],
                        sheet_path: Path, prices=None) -> dict:
    """Session-close sheet mode: regenerate/refresh the live-fill sheet from the
    ledger mechanically, tally it, and return the embeddable summary.

    Honest rules:
      * if the sheet file exists: preserve recorded slots, reconcile their source
        identities, and import newly appended evidence once (idempotent);
      * if absent: generate the §8 skeleton and fill slots mechanically from
        the ledger via the assignments map (task_id → {arm, cell}); lines that
        cannot be placed become findings, never silently dropped;
      * tally integrity violations are embedded verbatim — a close report
        carrying violations still exits 1 for the §8 drift rule.
    """
    import gen_live_fill_sheet as gf  # noqa: E402
    if sheet_path.is_file():
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
        action = "loaded-existing"
    else:
        sheet = gf.build_sheet()
        action = "generated-skeleton"

    filled_lines, missed = 0, []
    if assignments is not None:
        # DELEGATED to live_fill_tally.import_from_ledger — the single source of
        # truth for mechanical slot-filling (line order, skip-filled idempotency,
        # §8 latency delta with not_computable_first_dispatch, D-arm
        # gate_runner_route=ledger-only, unassignable lines as findings never
        # dropped). Duplicating it here DID drift once; don't re-duplicate.
        import live_fill_tally as lft  # noqa: E402
        before = lft.tally_summary(sheet, prices)["observations_recorded"]
        missed = lft.import_from_ledger(sheet, entries, assignments, prices)
        filled_lines = lft.tally_summary(sheet, prices)["observations_recorded"] - before
    else:
        missed = [{"line": None, "task_id": None, "kind": "missing-assignments",
                   "detail": "current ledger cannot be assigned to evaluation cells"}]

    if action == "generated-skeleton" or filled_lines:
        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        sheet_path.write_text(json.dumps(sheet, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                              encoding="utf-8")
        csv_path = sheet_path.with_suffix(".csv")
        import csv as _csv
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=gf.CSV_FIELDS)
            w.writeheader()
            w.writerows(gf.csv_rows(sheet))

    import live_fill_tally as lft  # noqa: E402
    summary = lft.tally_summary(sheet, prices)
    summary["sheet_action"] = action
    summary["ledger_lines_placed"] = filled_lines
    summary["ledger_lines_unplaced"] = missed
    return summary


def embed_sheet_markdown(summary: dict) -> str:
    lines = ["", "**Live-fill sheet (§8)** — "
             f"{summary['cells_filled']}/{summary['cells_total']} cells filled, "
             f"{summary['observations_recorded']}/{summary['observations_max']} observations "
             f"recorded (sheet action: {summary['sheet_action']})."]
    for cell_id, c in sorted(summary["per_cell"].items()):
        lines.append(f"- {cell_id}: recorded {c['recorded']}, "
                     f"{'FILLED' if c['filled'] else 'open'}")
    if summary["ledger_lines_unplaced"]:
        lines.append("")
        lines.append("_Unplaced ledger lines (disclosed, not dropped):_")
        for m in summary["ledger_lines_unplaced"]:
            lines.append(f"- line {m['line']} ({m['kind']}): {m['detail']}")
    if not summary["integrity_ok"]:
        lines.append("")
        lines.append("_Sheet integrity violations (§8 drift rule applies):_")
        for v in summary["problems"]:
            lines.append(f"- {v.get('detail', str(v)) if isinstance(v, dict) else v}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Close pilot tasks from the observation ledger")
    ap.add_argument("--ledger", default=str(LEDGER_DEFAULT))
    ap.add_argument("--prices", default=str(PRICES_PATH))
    ap.add_argument("--markdown", action="store_true", help="emit paste-ready markdown instead of JSON")
    ap.add_argument("--with-sheet", action="store_true",
                    help="session-close mode: regenerate/load the live-fill sheet, tally it, "
                         "and embed per-cell fill status in the report")
    ap.add_argument("--sheet", default=str(SHEET_DEFAULT), help="live-fill sheet path for --with-sheet")
    ap.add_argument("--assignments", default=str(ASSIGNMENTS_DEFAULT),
                    help="task_id→{arm,cell} map used when the sheet must be generated from the ledger")
    args = ap.parse_args(argv)

    prices = json.loads(Path(args.prices).read_text(encoding="utf-8"))
    if prices.get("revision") != "prices-2":
        print("pilot_close: unexpected prices revision — stop", file=sys.stderr)
        return 2
    inputs = pr.load_accounting_inputs(Path(args.ledger))
    if not inputs["accounting_entries"] and not inputs["authority_present"]:
        print("pilot_close: ledger empty or missing — nothing to close", file=sys.stderr)
        return 2
    accounting = pr.build_accounting_report(prices, inputs)
    closure = close_ledger(prices, inputs["accounting_entries"], accounting_report=accounting)
    sheet_summary = None
    sheet_violations = 0
    if args.with_sheet:
        assignments = None
        if Path(args.assignments).is_file():
            assignments = json.loads(Path(args.assignments).read_text(encoding="utf-8"))
        sheet_summary = build_sheet_section(inputs["raw_entries"], assignments, Path(args.sheet), prices)
        closure["live_fill_sheet"] = sheet_summary
        if not sheet_summary["integrity_ok"]:
            sheet_violations = len(sheet_summary["problems"])
        sheet_violations += len(sheet_summary["ledger_lines_unplaced"])
    if args.markdown:
        print(markdown(closure))
        if sheet_summary is not None:
            print(embed_sheet_markdown(sheet_summary))
    else:
        print(json.dumps(closure, indent=2, sort_keys=True))

    base_ok = closure["pilot_totals"]["accounting_status"] == "intact"
    sheet_ok = args.with_sheet and sheet_violations == 0
    if args.with_sheet and sheet_violations:
        print(f"pilot_close: {sheet_violations} sheet integrity violation(s) — §8 drift rule applies",
              file=sys.stderr)
    if not base_ok:
        return 1
    return 0 if (not args.with_sheet or sheet_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
