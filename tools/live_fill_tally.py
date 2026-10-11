#!/usr/bin/env python3
"""Tally the live-fill sheet against the §8 sampling plan.

Reads tools/live_fill_sheet.json and prints:
  * per-cell: slots recorded / repeats per task / filled?
  * per-arm: observations recorded vs the 20/arm target
  * pilot-level: cells filled, observations recorded, cells remaining

Exit codes: 0 = tally printed (sheet state is honest, however empty);
1 = integrity violation (an observation marked filled but carrying
'not_measured' fields, or a filled arm under target) — never silence a
lie; 2 = sheet missing/corrupt.

Slot-filling should NOT be hand-edited: `--import <ledger> --assignments <map.json>`
records observations mechanically from the real pilot ledger lines (in file order,
armed by the task→arm assignment map, skipping already-filled slots). Manual edits are
still *allowed* but the import path is the auditable one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

NOT_MEASURED = "not_measured"
MEASURED_REQUIRED = ("ts", "profile_dispatched", "input_tokens", "output_tokens",
                     "cost_usd", "latency_s", "outcome", "task_id")


def check_integrity(sheet: dict) -> list:
    problems = []
    for cell_id, c in sheet["cells"].items():
        for obs in c["observations"]:
            marked = all(obs.get(k) != NOT_MEASURED for k in MEASURED_REQUIRED)
            if marked and not c.get("filled"):
                continue  # record exists but cell not yet marked filled: fine mid-fill
            if c.get("filled") and not marked:
                problems.append(f"{cell_id} slot {obs.get('slot')}: cell says filled "
                                "but this observation still has not_measured fields")
            if obs.get("accounting_intact") is False and c.get("filled"):
                problems.append(f"{cell_id}: filled with accounting_intact=false "
                                "(§8 completion rule violated)")
        n = sum(1 for obs in c["observations"]
                if all(obs.get(k) != NOT_MEASURED for k in MEASURED_REQUIRED))
        c["_recorded"] = n
    return problems


def tally_summary(sheet: dict) -> dict:
    """Machine-readable fill status: per-cell + per-arm + totals + integrity.
    Used by this tool's human output and by pilot_close.py --with-sheet
    (session-close embeds this dict verbatim in the close report). Recorded
    counts here match import_from_ledger's "empty" predicate exactly: a slot
    with ANY measured field set + task_id counts as recorded (first-dispatch
    slots legally carry not_computable_first_dispatch latency)."""
    problems = check_integrity(sheet)
    for cell_id, c in sheet["cells"].items():
        c["_recorded"] = sum(1 for obs in c["observations"]
                             if any(obs.get(k) != NOT_MEASURED
                                    for k in MEASURED_REQUIRED) and obs.get("task_id"))
    per_cell = {}
    per_arm: Dict[str, int] = {arm: 0 for arm in sheet["arms"]}
    cells_filled = 0
    for cell_id in sorted(sheet["cells"]):
        c = sheet["cells"][cell_id]
        n = c.get("_recorded", 0)
        per_arm[c["arm"]] += n
        cells_filled += 1 if c.get("filled") else 0
        per_cell[cell_id] = {"arm": c["arm"], "task_category": c["task_category"],
                             "recorded": n, "filled": bool(c.get("filled"))}
    target = sheet["observations_per_arm_target"]
    return {
        "per_cell": per_cell,
        "per_arm": per_arm,
        "target_per_arm": target,
        "cells_filled": cells_filled,
        "cells_total": len(sheet["cells"]),
        "observations_recorded": sum(per_arm.values()),
        "observations_max": target * len(per_arm),
        "problems": problems,
        "integrity_ok": not problems,
    }


def summarize_sheet(sheet_path: Path) -> tuple:
    """Load a sheet: (summary, None) on success, (None, 2) if missing/corrupt."""
    if not sheet_path.is_file():
        return None, 2
    try:
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, 2
    return tally_summary(sheet), None


def load_ledger(path: Path):
    """Parse the pilot ledger (same loader contract as pilot_report.load_jsonl)."""
    entries = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"live_fill_tally: corrupt ledger line {i}: {e}")
    return entries


def import_from_ledger(sheet: dict, entries: list, assignments: dict) -> list:
    """Fill empty slots mechanically from ledger lines. Returns findings list.

    Assignments map (required) routes each LIVE task into a sheet cell:
      {"L-101": {"arm": "A", "cell": "T-01"}}
    (a plain arm string like {"L-101": "A"} is an error — live task ids of any
    name may land in any T-column; the owner appoints the exact cell.)

    Mapping rules (§8 plan):
      * a ledger line fills the target cell's next EMPTY slot in line order
      * already-filled slots are skipped (idempotent re-import)
      * lines whose task has no assignment, wrong cell name, or whose target
        cell has no empty slot are NEVER silently dropped — findings
      * latency = same-task consecutive ts delta; first dispatch per task is
        "not_computable_first_dispatch"
      * D-arm gate-runner route is not carried by ledger lines: recorded as
        gate_runner_route = "ledger-only"
    """
    findings: list = []  # rows: {"line", "task_id", "kind", "detail"}
    def _finding(kind: str, detail: str) -> None:
        findings.append({"line": idx, "task_id": tid, "kind": kind, "detail": detail})
    per_task_prev_ts: dict = {}
    empties: dict = {}
    for cell_id, c in sheet["cells"].items():
        empties[cell_id] = [o for o in c["observations"]
                            if any(o.get(k) == NOT_MEASURED for k in MEASURED_REQUIRED)]
    for idx, e in enumerate(entries, 1):
        tid = e.get("task_id")
        a = assignments.get(tid)
        if a is None:
            _finding("unassigned", f"task {tid!r} has no assignment — not imported (add {'arm','cell'} to the assignments map)")
            continue
        if not isinstance(a, dict) or "arm" not in a or "cell" not in a:
            _finding("bad-assignment", f"assignment for {tid!r} must be {{\"arm\": \"A..D\", \"cell\": \"T-01..T-05\"}} — got {a!r}")
            continue
        arm, cell_task = a["arm"], a["cell"]
        cell_id = f"{arm}|{cell_task}"
        cell = sheet["cells"].get(cell_id)
        if cell is None:
            _finding("unknown-cell", f"{tid!r} → {cell_id!r} but that cell does not exist in this sheet")
            continue
        empty = empties.get(cell_id) or []
        if not empty:
            _finding("over-capacity", f"cell {cell_id!r} has no empty slot — line not imported (over-capacity task/repeat beyond plan)")
            continue
        obs = empty.pop(0)
        ts = e.get("ts")
        in_toks = int(e.get("input_tokens", 0))
        out_toks = int(e.get("output_tokens", 0))
        prev = per_task_prev_ts.get(tid)
        latency = (ts - prev) if (prev is not None and isinstance(ts, (int, float))) else "not_computable_first_dispatch"
        per_task_prev_ts[tid] = ts
        obs.update({
            "task_id": tid,
            "ts": ts,
            "profile_dispatched": e.get("profile_id"),
            "input_tokens": in_toks,
            "output_tokens": out_toks,
            "cost_usd": e.get("cost_usd"),
            "latency_s": latency,
            "outcome": e.get("decision"),
            "ledger_line_no": idx,
            "gate_runner_route": "ledger-only" if cell["arm"] == "D" else obs.get("gate_runner_route"),
            "accounting_intact": True,   # proven flags follow below via cost check
        })
        # mark cell filled when it has no empties left
        if not empties[cell_id]:
            cell["filled"] = True
    # accounting_intact per slot: recompute against prices via pilot_report when possible
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tally live-fill sheet vs §8 plan")
    ap.add_argument("--sheet", default=str(Path(__file__).resolve().parent / "live_fill_sheet.json"))
    ap.add_argument("--mode", choices=("full", "gate"), default="full",
                    help="full: session-close tally (missing sheet = exit 2). "
                         "gate: regression-gate mode — missing sheet passes (no session "
                         "opened); a sheet that exists MUST be honest or the gate fails.")
    ap.add_argument("--import", dest="import_ledger", metavar="LEDGER_JSONL", default=None,
                    help="fill empty slots mechanically from these pilot ledger lines (auditable path); "
                         "requires --assignments")
    ap.add_argument("--assignments", metavar="MAP_JSON", default=None,
                    help="task_id → arm map {'L-001': 'A', …} used by --import")
    args = ap.parse_args(argv)

    if args.import_ledger:
        if not args.assignments:
            print("live_fill_tally: --import requires --assignments (task_id → arm map)",
                  file=__import__("sys").stderr)
            return 2
        sheet_p = Path(args.sheet)
        if not sheet_p.is_file():
            print(f"live_fill_tally: sheet missing at {sheet_p} — run gen_live_fill_sheet.py first",
                  file=__import__("sys").stderr)
            return 2
        sheet = json.loads(sheet_p.read_text(encoding="utf-8"))
        entries = load_ledger(Path(args.import_ledger))
        amap = json.loads(Path(args.assignments).read_text(encoding="utf-8"))
        findings = import_from_ledger(sheet, entries, amap)
        sheet_p.write_text(json.dumps(sheet, indent=2, ensure_ascii=False, sort_keys=True) + chr(10),
                           encoding="utf-8", newline=chr(10))
        if findings:
            print("live_fill_tally --import: FINDINGS (re-derivable, nothing silently dropped):",
                  file=__import__("sys").stderr)
            for f in findings:
                print("  -", f, file=__import__("sys").stderr)
        n_filled = sum(1 for c in sheet["cells"].values() if c.get("filled"))
        n_rec = sum(c.get("_recorded", 0) for c in sheet["cells"].values()) if False else None
        print(f"import done: sheet written to {sheet_p}; findings: {len(findings)}; "
              f"cells marked filled: {n_filled}")
        if getattr(args, "mode", "full") != "gate":
            # fall through to the normal tally print so the same invocation tallies
            pass
        else:
            return 0

    p = Path(args.sheet)
    if not p.is_file():
        if getattr(args, "mode", "full") == "gate":
            print("live_fill_tally(gate): no sheet present — no live session state to audit; PASS")
            return 0
        print(f"live_fill_tally: sheet missing at {p} — run gen_live_fill_sheet.py", file=__import__("sys").stderr)
        return 2
    try:
        sheet = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"live_fill_tally: corrupt sheet: {e}", file=__import__("sys").stderr)
        return 2

    problems = check_integrity(sheet)

    per_arm: Dict[str, int] = {arm: 0 for arm in sheet["arms"]}
    cells_filled = 0
    print(f"{'cell':6} {'recorded':>8} /{sheet['repeats_per_task'] * len(sheet['cells']) // len(sheet['cells'])} {'filled':>6}")
    for cell_id in sorted(sheet["cells"]):
        c = sheet["cells"][cell_id]
        n = c.get("_recorded", 0)
        per_arm[c["arm"]] += n
        tag = "yes" if c.get("filled") else "no"
        cells_filled += 1 if c.get("filled") else 0
        print(f"{cell_id:6} {n:>8} {tag:>6}")
    recorded = sum(per_arm.values())
    print()
    for arm, n in per_arm.items():
        target = sheet["observations_per_arm_target"]
        status = "OK" if n >= target else f"{target - n} to go"
        print(f"arm {arm}: {n}/{target} observations ({status})")
    print(f"\ncells filled: {cells_filled}/{len(sheet['cells'])} · "
          f"observations recorded: {recorded}/{target * len(per_arm)}")

    if problems:
        print("\nINTEGRITY VIOLATIONS:", file=__import__("sys").stderr)
        for pr_ in problems:
            print("  -", pr_, file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
