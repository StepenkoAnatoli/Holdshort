#!/usr/bin/env python3
"""Arm-matrix live-fill tracking sheet — 20 empty cells waiting for the pilot (§8 plan).

Generates the per-cell observation skeleton from the same arm/task model the
non-live matrix uses (tools/arm_matrix.py), so live observations are recorded
in a structure that can be tallied against the §8 live sampling plan:

  tools/live_fill_sheet.json  — per-cell records: planned fill (20 obs/arm,
    2 repeats per task), observed slots (empty), tally fields
  tools/live_fill_sheet.csv   — same, 80 observation slots across the four arms

Both files are SKELETONS — every measured field starts empty ("not_measured")
and is only filled from real dispatches. The tally tool (tools/live_fill_tally.py)
reads the JSON back and reports per-cell/per-arm fill status vs. the §8 rules.

Regenerate with:  python tools/gen_live_fill_sheet.py [--out-dir tools]
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "tools"))
import smart_router_decisions as srd  # noqa: E402

ARMS = ("A", "B", "C", "D")
ARM_LABELS = {
    "A": "strong qualified direct",
    "B": "economical qualified direct",
    "C": "simple fixed rule",
    "D": "SmartRouter skill flow (ordered gates + brief/verifier/review)",
}
# live profiles per arm (plan §10 catalog; D is route-resolved per task)
PROFILE_BY_ARM = {"A": "cloud-S", "B": "cloud-C", "C": "cloud-C", "D": None}

# task palette per §3 live pool (categories mirrored from the matrix's five tasks)
TASKS = ["T-01", "T-02", "T-03", "T-04", "T-05"]
TASK_CATEGORY = {"T-01": "typo", "T-02": "mechanical", "T-03": "mechanical",
                 "T-04": "text", "T-05": "text"}

REPEATS_PER_TASK = 2          # preregistration §11, RATIFIED
OBS_PER_ARM = 20              # pre-registration §11, RATIFIED
NOT_MEASURED = "not_measured"


EMPTY_OBS = {
    "task_id": None,
    "ts": NOT_MEASURED,
    "profile_dispatched": NOT_MEASURED,
    "input_tokens": NOT_MEASURED,
    "output_tokens": NOT_MEASURED,
    "cost_usd": NOT_MEASURED,
    "latency_s": NOT_MEASURED,
    "outcome": NOT_MEASURED,      # dispatched / blocked:cap / blocked:gate / repair
    "ledger_line_no": NOT_MEASURED,
    "gate_runner_route": NOT_MEASURED,  # D arm only
    "rejected_by": [],                   # D arm only
    "accounting_intact": NOT_MEASURED,
    "drift_flag": False,
}


def build_sheet() -> dict:
    # T-columns are task categories. Each holds two independently assigned live
    # tasks, with two repeats each; five columns therefore hold 20 trials/arm.
    if OBS_PER_ARM % (len(TASKS) * REPEATS_PER_TASK):
        raise ValueError("sampling target must fit whole assigned tasks and repeats")
    tasks_per_cell = OBS_PER_ARM // (len(TASKS) * REPEATS_PER_TASK)
    if tasks_per_cell < 1:
        raise ValueError("sampling target cannot cover every task category")
    cells: Dict[str, dict] = {}
    slot_no = 0
    for arm in ARMS:
        for task in TASKS:
            cell_id = f"{arm}|{task}"
            observations = []
            for position in range(tasks_per_cell * REPEATS_PER_TASK):
                slot_no += 1
                obs = deepcopy(EMPTY_OBS)
                obs["slot"] = slot_no
                obs["repeat"] = position % REPEATS_PER_TASK + 1
                obs["assignment_slot"] = position // REPEATS_PER_TASK + 1
                obs["cell_id"] = cell_id
                observations.append(obs)
            cells[cell_id] = {
                "arm": arm,
                "arm_label": ARM_LABELS[arm],
                "task_id": task,
                "task_category": TASK_CATEGORY[task],
                "planned_profile": PROFILE_BY_ARM[arm] or "route-resolved by gate-runner",
                "planned_observations": tasks_per_cell * REPEATS_PER_TASK,
                "planned_tasks": tasks_per_cell,
                "planned_repeats_per_task": REPEATS_PER_TASK,
                "observations": observations,
                "filled": False,
                "nonlive_ground_truth": {"arm_semantics_only": True},
            }
    return {
        "sheet_version": 2,
        "extends": "docs/PHASE4_PILOT_REPORT.md §8 (live sampling plan)",
        "authority": "docs/PHASE3_PREREGISTRATION.md §11 (RATIFIED: 20 obs/arm, 2 repeats cold-cache, 50/50 tuning/holdout) + PHASE4_LIVE_START_PACKET.md §3 row-4 (SIGNED)",
        "arms": list(ARMS),
        "tasks": TASKS,
        "repeats_per_task": REPEATS_PER_TASK,
        "observations_per_arm_target": OBS_PER_ARM,
        "cells": cells,
        "tally": {"cells_filled": 0, "observations_recorded": 0,
                  "cells_remaining": len(cells)},
        "honesty_note": "Empty skeleton: every measured field is 'not_measured' until a real "
                        "live dispatch lands in it. A cell is 'filled' only when its full "
                        "per-arm observation share is recorded with accounting_intact=true. "
                        "Blocks are observations too (outcome=blocked:*); they consume slots.",
    }


def csv_rows(sheet: dict) -> List[dict]:
    rows: List[dict] = []
    for cell_id, c in sheet["cells"].items():
        for obs in c["observations"]:
            rows.append({
                "slot": obs["slot"], "cell_id": cell_id, "arm": c["arm"],
                "planned_task_id": c["task_id"], "task_category": c["task_category"],
                "repeat": obs["repeat"], "planned_profile": c["planned_profile"],
                **{k: obs[k] for k in EMPTY_OBS},
            })
    return rows


CSV_FIELDS = ["slot", "cell_id", "arm", "planned_task_id", "task_category", "repeat",
              "planned_profile"] + list(EMPTY_OBS)


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the live-fill 20-cell tracking skeleton (§8)")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "tools"))
    args = ap.parse_args(argv)
    out = Path(args.out_dir)

    sheet = build_sheet()
    (out / "live_fill_sheet.json").write_text(
        json.dumps(sheet, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    with (out / "live_fill_sheet.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(csv_rows(sheet))

    n_slots = sum(len(c["observations"]) for c in sheet["cells"].values())
    print(f"live_fill_sheet: {len(sheet['cells'])} cells / {n_slots} slots written to "
          f"{out}/live_fill_sheet.json + .csv (all fields not_measured; tallied by "
          f"tools/live_fill_tally.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
