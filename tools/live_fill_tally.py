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
import hashlib
from pathlib import Path
from typing import Dict

NOT_MEASURED = "not_measured"
UNKNOWN_LATENCY = "not_measured_transport_latency"
MEASURED_REQUIRED = ("ts", "profile_dispatched", "input_tokens", "output_tokens",
                     "cost_usd", "latency_s", "outcome", "task_id")


def load_prices():
    return json.loads(Path(__file__).with_name("prices-2.json").read_text(encoding="utf-8"))


def frozen_evaluation_plan():
    import eval_pool
    return eval_pool.freeze_plan(eval_pool.load_pool())


def _matches_assignment(actual, expected):
    """Match frozen scalar metadata without Python's bool/int/float coercion."""
    return isinstance(actual, dict) and all(
        key in actual and type(actual[key]) is type(value) and actual[key] == value
        for key, value in expected.items()
    )


def empty_observation(obs):
    return (isinstance(obs, dict) and obs.get("task_id") is None
            and all(obs.get(k) == NOT_MEASURED for k in MEASURED_REQUIRED if k != "task_id"))


def source_fingerprint(entry, line):
    fields = {k: entry.get(k) for k in
              ("task_id", "profile_id", "ts", "observation_ts", "input_tokens", "output_tokens", "cost_usd", "decision", "reservation_id", "purpose", "transport_started_at", "transport_finished_at")}
    fields["ledger_line_no"] = line
    return hashlib.sha256(json.dumps(fields, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def observation_problems(obs, prices):
    import pilot_report as pr
    if not isinstance(obs, dict):
        return ["observation must be an object"]
    entry = {"task_id": obs.get("task_id"), "profile_id": obs.get("profile_dispatched"),
             "ts": obs.get("ts"), "input_tokens": obs.get("input_tokens"),
             "output_tokens": obs.get("output_tokens"), "cost_usd": obs.get("cost_usd"),
             "decision": obs.get("outcome"), "reason": "sheet observation",
             "reservation_id": obs.get("reservation_id"),
             "purpose": obs.get("purpose", "work"),
             "transport_started_at": obs.get("transport_started_at"),
             "transport_finished_at": obs.get("transport_finished_at")}
    problems = pr.entry_problems(entry)
    for field in ("input_tokens", "output_tokens"):
        if type(obs.get(field)) is not int or obs[field] < 0:
            problems.append(f"{field} must be measured nonnegative integer usage")
    if not pr.finite_nonnegative(obs.get("cost_usd")):
        problems.append("cost_usd must be measured finite nonnegative cost")
    if not pr.finite_nonnegative(obs.get("source_event_ts", obs.get("ts"))):
        problems.append("source_event_ts must be a finite nonnegative observation")
    if obs.get("accounting_intact") is not True:
        problems.append("accounting_intact must be true")
    if type(obs.get("ledger_line_no")) is not int or obs["ledger_line_no"] < 1:
        problems.append("ledger_line_no must be a positive integer")
    latency = obs.get("latency_s")
    if latency not in ("not_computable_first_dispatch", UNKNOWN_LATENCY) and not pr.finite_nonnegative(latency):
        problems.append("latency_s must be measured or explicitly unavailable")
    started, finished = obs.get("transport_started_at"), obs.get("transport_finished_at")
    if started is not None and finished is not None:
        if (not pr.finite_nonnegative(started) or not pr.finite_nonnegative(finished)
                or finished < started or not pr.finite_nonnegative(latency)
                or abs(latency - (finished - started)) > 1e-9):
            problems.append("latency_s must match the observed transport interval")
    elif latency != UNKNOWN_LATENCY:
        problems.append("transport latency requires both start and finish evidence")
    if obs.get("purpose", "work") != "work":
        problems.append("a verification call is not an independent evaluation trial")
    if not problems:
        if entry["decision"] in ("dispatched", "dispatch-error", "dispatch-reconciled"):
            expected = pr.recompute_cost(prices, entry["profile_id"], entry["input_tokens"], entry["output_tokens"])
            if expected is None or not pr.finite_nonnegative(expected) or abs(expected - entry["cost_usd"]) > 1e-9:
                problems.append("observation cost does not match configured profile rates")
        elif entry["input_tokens"] or entry["output_tokens"] or entry["cost_usd"]:
            problems.append("a blocked observation cannot carry dispatch usage")
        entry["reservation_id"] = obs.get("reservation_id")
        entry["observation_ts"] = obs.get("ts")
        entry["ts"] = obs.get("source_event_ts", obs.get("ts"))
        if obs.get("source_fingerprint") != source_fingerprint(entry, obs["ledger_line_no"]):
            problems.append("observation changed from its imported evidence")
    return problems


def check_integrity(sheet: dict, prices=None, *, recorded_counts=None) -> list:
    prices = load_prices() if prices is None else prices
    problems = []
    if (not isinstance(sheet, dict) or not isinstance(sheet.get("cells"), dict)
            or not isinstance(sheet.get("arms"), list)
            or not sheet["arms"] or any(arm not in ("A", "B", "C", "D") for arm in sheet["arms"])
            or len(set(sheet["arms"])) != len(sheet["arms"])
            or type(sheet.get("observations_per_arm_target")) is not int
            or sheet["observations_per_arm_target"] <= 0):
        return ["sheet has invalid cells, arms, or observation target"]
    frozen = None
    if "evaluation_plan" in sheet:
        try:
            frozen = frozen_evaluation_plan()
            expected = {key: frozen[key] for key in ("pool_id", "manifest_sha256", "schedule_sha256")}
            if sheet["evaluation_plan"] != expected:
                return ["sheet evaluation plan differs from the frozen pool"]
        except (ValueError, OSError):
            return ["frozen evaluation pool cannot be validated"]
    from gen_live_fill_sheet import ARMS, TASKS, OBS_PER_ARM, REPEATS_PER_TASK, PROFILE_BY_ARM
    if (set(sheet["arms"]) != set(ARMS) or set(sheet["cells"]) != {f"{arm}|{task}" for arm in ARMS for task in TASKS}
            or sheet["observations_per_arm_target"] < OBS_PER_ARM
            or type(sheet.get("repeats_per_task")) is not int
            or sheet.get("repeats_per_task") != REPEATS_PER_TASK):
        problems.append("sheet does not cover the ratified arms, task columns, target, and repeats")
    capacity = {arm: 0 for arm in sheet["arms"]}
    evidence_lines = set()
    evidence_hashes = set()
    evidence_trials = set()
    for cell_id, c in sheet["cells"].items():
        if (not isinstance(c, dict) or not isinstance(c.get("arm"), str) or c["arm"] not in capacity
                or not isinstance(c.get("observations"), list) or type(c.get("filled")) is not bool
                or type(c.get("planned_tasks")) is not int or c["planned_tasks"] <= 0
                or type(c.get("planned_repeats_per_task")) is not int or c["planned_repeats_per_task"] <= 0
                or not isinstance(c.get("task_category"), str)
                or not isinstance(c.get("task_id"), str) or c["task_id"] not in TASKS
                or cell_id != f"{c['arm']}|{c['task_id']}"
                or not isinstance(c.get("planned_profile"), str)):
            problems.append(f"{cell_id}: malformed cell")
            continue
        observations = c["observations"]
        capacity[c["arm"]] += len(observations)
        planned = c.get("planned_observations")
        if (type(planned) is not int or planned <= 0 or len(observations) != planned
                or planned != c["planned_tasks"] * c["planned_repeats_per_task"]
                or c["planned_repeats_per_task"] != REPEATS_PER_TASK):
            problems.append(f"{cell_id}: capacity does not match its observation plan")
        if c["arm"] in ("A", "B", "C") and c["planned_profile"] != PROFILE_BY_ARM[c["arm"]]:
            problems.append(f"{cell_id}: fixed-arm profile differs from the sampling plan")
        recorded = 0
        task_counts = {}
        assignment_by_task = {}
        for obs in observations:
            if empty_observation(obs):
                if c["filled"]:
                    problems.append(f"{cell_id}: cell says filled but an observation is not measured")
                continue
            failures = observation_problems(obs, prices)
            if not failures:
                planned_profile = c.get("planned_profile")
                if (c["arm"] in ("A", "B", "C") and obs["outcome"] in ("dispatched", "dispatch-error", "dispatch-reconciled")
                        and obs["profile_dispatched"] != planned_profile):
                    failures.append("observation profile does not match its fixed arm")
                if obs.get("cell_id") != cell_id:
                    failures.append("observation is assigned to another cell")
                line = obs["ledger_line_no"]
                fingerprint = obs.get("source_fingerprint")
                if line in evidence_lines or isinstance(fingerprint, str) and fingerprint in evidence_hashes:
                    failures.append("duplicate source evidence")
                if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                    failures.append("source_fingerprint must identify imported evidence")
                evidence_lines.add(line)
                if isinstance(fingerprint, str):
                    evidence_hashes.add(fingerprint)
                if frozen is not None:
                    assignment = frozen["assignments"].get(obs["task_id"])
                    if assignment is None or not _matches_assignment(obs, assignment):
                        failures.append("observation differs from its frozen trial assignment")
                    if obs["task_id"] in evidence_trials:
                        failures.append("one trial cannot be counted twice")
                    evidence_trials.add(obs["task_id"])
                task = (assignment["fixture_id"] if frozen is not None and assignment is not None
                        else obs["task_id"])
                task_counts[task] = task_counts.get(task, 0) + 1
                if (type(obs.get("repeat")) is not int or (frozen is None and obs["repeat"] != task_counts[task])
                        or task_counts[task] > c.get("planned_repeats_per_task", 0)):
                    failures.append("task repeat count does not match its plan")
                assignment_by_task.setdefault(task, len(assignment_by_task) + 1)
                if (type(obs.get("assignment_slot")) is not int
                        or obs.get("assignment_slot") != assignment_by_task[task]):
                    failures.append("task assignment slot does not match imported task")
                if len(assignment_by_task) > c.get("planned_tasks", 0):
                    failures.append("too many independently assigned tasks in cell")
            if failures:
                problems.extend(f"{cell_id}: {failure}" for failure in failures)
            else:
                recorded += 1
        if recorded_counts is not None:
            recorded_counts[cell_id] = recorded
        if c["filled"] and recorded != planned:
            problems.append(f"{cell_id}: filled count does not match validated observations")
    for arm, count in capacity.items():
        if count < sheet["observations_per_arm_target"]:
            problems.append(f"arm {arm}: insufficient capacity for observation target")
    return problems


def tally_summary(sheet: dict, prices=None) -> dict:
    """Machine-readable fill status: per-cell + per-arm + totals + integrity.
    Used by this tool's human output and by pilot_close.py --with-sheet
    (session-close embeds this dict verbatim in the close report). Recorded
    Counts include only complete, validated observations. First-dispatch slots
    may explicitly carry not_computable_first_dispatch latency."""
    recorded_counts = {}
    problems = check_integrity(sheet, prices, recorded_counts=recorded_counts)
    if not isinstance(sheet, dict) or not isinstance(sheet.get("cells"), dict) or not isinstance(sheet.get("arms"), list):
        return {"per_cell": {}, "per_arm": {}, "target_per_arm": 0, "cells_filled": 0,
                "cells_total": 0, "observations_recorded": 0, "observations_max": 0,
                "problems": problems, "integrity_ok": False}
    per_cell = {}
    per_arm: Dict[str, int] = {arm: 0 for arm in sheet.get("arms", []) if isinstance(arm, str)}
    cells_filled = 0
    for cell_id in sorted(sheet["cells"], key=str):
        c = sheet["cells"][cell_id]
        if not isinstance(c, dict) or not isinstance(c.get("arm"), str) or c["arm"] not in per_arm:
            continue
        n = recorded_counts.get(cell_id, 0)
        per_arm[c["arm"]] += n
        cells_filled += 1 if c.get("filled") else 0
        per_cell[cell_id] = {"arm": c["arm"], "task_category": c.get("task_category", "unknown"),
                             "recorded": n, "filled": bool(c.get("filled"))}
    target = sheet.get("observations_per_arm_target", 0)
    if type(target) is not int or target < 0:
        target = 0
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
        "evaluation_plan_bound": "evaluation_plan" in sheet,
        "live_model_qualification": "pending",
    }


def summarize_sheet(sheet_path: Path) -> tuple:
    """Load a sheet: (summary, None) on success, (None, 2) if missing/corrupt."""
    if not sheet_path.is_file():
        return None, 2
    try:
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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


def import_from_ledger(sheet: dict, entries: list, assignments: dict, prices=None) -> list:
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
      * latency uses the observed transport interval, or is explicitly unavailable;
        same-task timestamp deltas are separate inter-observation intervals
      * D-arm gate-runner route is not carried by ledger lines: recorded as
        gate_runner_route = "ledger-only"
    """
    prices = load_prices() if prices is None else prices
    findings: list = []  # rows: {"line", "task_id", "kind", "detail"}
    def _finding(kind: str, detail: str) -> None:
        findings.append({"line": idx, "task_id": tid, "kind": kind, "detail": detail})
    if not isinstance(assignments, dict):
        return [{"line": None, "task_id": None, "kind": "bad-assignment", "detail": "assignments must be an object"}]
    if not isinstance(sheet, dict) or not isinstance(sheet.get("cells"), dict):
        return [{"line": None, "task_id": None, "kind": "invalid-sheet", "detail": "sheet cells must be an object"}]
    violations = check_integrity(sheet, prices)
    if violations:
        return [{"line": None, "task_id": None, "kind": "invalid-sheet", "detail": "; ".join(violations)}]
    frozen = None
    bound = "evaluation_plan" in sheet
    wants_frozen = bound or any(isinstance(value, dict) and "manifest_sha256" in value for value in assignments.values())
    if wants_frozen:
        try:
            frozen = frozen_evaluation_plan()
        except (ValueError, OSError):
            return [{"line": None, "task_id": None, "kind": "invalid-plan", "detail": "frozen evaluation pool cannot be validated"}]
        if (assignments != frozen["assignments"] or any(
                not _matches_assignment(assignments[task_id], expected)
                for task_id, expected in frozen["assignments"].items())):
            return [{"line": None, "task_id": None, "kind": "invalid-plan", "detail": "assignments must match the complete frozen schedule"}]
        if not bound:
            if any(not empty_observation(obs) for cell in sheet["cells"].values()
                   if isinstance(cell, dict) for obs in cell.get("observations", [])):
                return [{"line": None, "task_id": None, "kind": "invalid-plan", "detail": "legacy recorded sheet cannot silently acquire a new protocol"}]
            sheet["evaluation_plan"] = {key: frozen[key] for key in ("pool_id", "manifest_sha256", "schedule_sha256")}
    per_task_prev_ts: dict = {}
    empties: dict = {}
    imported = {}
    for cell_id, c in sheet["cells"].items():
        empties[cell_id] = [o for o in c["observations"] if empty_observation(o)]
        for obs in c["observations"]:
            if not empty_observation(obs) and type(obs.get("ledger_line_no")) is int:
                imported[obs["ledger_line_no"]] = (cell_id, obs)
    from pilot_report import effective_entries, ledger_problems
    invalid_rows = ledger_problems(entries)
    for idx, errors in invalid_rows.items():
        e = entries[idx - 1]
        findings.append({"line": idx, "task_id": e.get("task_id") if isinstance(e, dict) else None,
                         "kind": "invalid-ledger-entry", "detail": "; ".join(errors)})
    if frozen is not None:
        started_trials = []
        excluded = {"verification-complete", "dispatch-cancelled", "task-abandoned",
                    "blocked-verified", "blocked-abandoned", "blocked-uncertain"}
        for line, event in enumerate(entries, 1):
            if (line in invalid_rows or event.get("purpose", "work") != "work"
                    or event.get("decision") in excluded):
                continue
            trial = event["task_id"]
            if trial not in started_trials:
                started_trials.append(trial)
        expected_order = [trial["task_id"] for trial in frozen["trials"]]
        if started_trials != expected_order[:len(started_trials)]:
            findings.append({"line": None, "task_id": None, "kind": "schedule-drift",
                             "detail": "execution order is not a prefix of the frozen schedule"})
            return findings
    effective = list(effective_entries(entries))
    # Reconciliation is accounting evidence recorded later; it is not a new
    # execution timestamp. Retain the original reservation/send observations.
    original = {}
    for origin_line, row in enumerate(entries, 1):
        if origin_line in invalid_rows or not isinstance(row, dict) or not isinstance(row.get("reservation_id"), str):
            continue
        if row.get("decision") in ("dispatch-reserved", "dispatch-error", "dispatched"):
            prior = original.get(row["reservation_id"])
            if prior is None or row.get("decision") != "dispatch-reserved":
                original[row["reservation_id"]] = row
    sampling_entries = []
    for line, event in effective:
        row = dict(event)
        origin = original.get(row.get("reservation_id"), row) if row["decision"] == "dispatch-reconciled" else row
        for field in ("transport_started_at", "transport_finished_at"):
            if row.get(field) is None:
                row[field] = origin.get(field)
        row["purpose"] = row.get("purpose", "work")
        row["observation_ts"] = origin.get("transport_finished_at") or origin["ts"]
        sampling_entries.append((line, row))
    current_lines = {idx for idx, _ in effective}
    for idx, (_, obs) in imported.items():
        if idx not in current_lines:
            findings.append({"line": idx, "task_id": obs["task_id"], "kind": "missing-source-evidence",
                             "detail": "recorded source is absent or superseded in current ledger; original observation preserved"})
    for idx, e in sampling_entries:
        tid = e.get("task_id")
        if (e.get("purpose", "work") != "work" or e.get("decision") in (
                "verification-complete", "dispatch-cancelled", "task-abandoned",
                "blocked-verified", "blocked-abandoned", "blocked-uncertain")):
            continue  # acceptance evidence is not an additional model trial
        if any(e.get(field) is None for field in ("input_tokens", "output_tokens", "cost_usd")):
            _finding("unknown-usage", "unsettled dispatch is not a completed measured observation")
            continue
        digest = source_fingerprint(e, idx)
        if idx in imported:
            old_cell, old = imported[idx]
            expected_assignment = ({key: old.get(key) for key in frozen["assignments"][tid]} if frozen else
                                   {"arm": sheet["cells"][old_cell]["arm"], "cell": sheet["cells"][old_cell]["task_id"]})
            if old.get("source_fingerprint") != digest or assignments.get(tid) != expected_assignment:
                _finding("changed-evidence", "recorded source or assignment changed; original observation preserved")
            per_task_prev_ts[tid] = e["observation_ts"]
            continue
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
        obs = dict(empty[0])
        ts = e["observation_ts"]
        in_toks = e["input_tokens"]
        out_toks = e["output_tokens"]
        prev = per_task_prev_ts.get(tid)
        interval = ts - prev if prev is not None else None
        started, finished = e.get("transport_started_at"), e.get("transport_finished_at")
        latency = finished - started if started is not None and finished is not None else UNKNOWN_LATENCY
        obs.update({
            "task_id": tid,
            "ts": ts,
            "source_event_ts": e["ts"],
            "purpose": e.get("purpose", "work"),
            "transport_started_at": started,
            "transport_finished_at": finished,
            "inter_observation_interval_s": interval,
            "profile_dispatched": e.get("profile_id"),
            "input_tokens": in_toks,
            "output_tokens": out_toks,
            "cost_usd": e.get("cost_usd"),
            "latency_s": latency,
            "outcome": e.get("decision"),
            "ledger_line_no": idx,
            "gate_runner_route": "ledger-only" if cell["arm"] == "D" else obs.get("gate_runner_route"),
            "accounting_intact": True,
            "source_fingerprint": digest,
            "reservation_id": e.get("reservation_id"),
        })
        if frozen is not None:
            obs.update(a)
        if (arm in ("A", "B", "C") and obs["outcome"] in ("dispatched", "dispatch-error", "dispatch-reconciled")
                and obs["profile_dispatched"] != cell["planned_profile"]):
            _finding("wrong-arm-profile", "observation profile does not match its fixed arm")
            continue
        errors = observation_problems(obs, prices)
        if errors:
            _finding("invalid-observation", "; ".join(errors))
            continue
        fixture_id = a.get("fixture_id", tid) if frozen is not None else tid
        recorded_for_task = sum(1 for recorded in cell["observations"]
                                if (recorded.get("fixture_id", recorded.get("task_id")) if frozen is not None
                                    else recorded.get("task_id")) == fixture_id)
        if frozen is not None and any(recorded.get("task_id") == tid for recorded in cell["observations"]):
            _finding("duplicate-trial-work", "repairs of one execution are not independent repeats")
            continue
        if recorded_for_task >= cell["planned_repeats_per_task"]:
            _finding("over-repeat-limit", "task already has its planned repeat count")
            continue
        assigned_tasks = list(dict.fromkeys(o.get("fixture_id", o["task_id"]) if frozen is not None else o["task_id"]
                                            for o in cell["observations"] if not empty_observation(o)))
        if fixture_id not in assigned_tasks and len(assigned_tasks) >= cell["planned_tasks"]:
            _finding("over-task-capacity", "cell already contains its planned assigned tasks")
            continue
        if fixture_id not in assigned_tasks:
            assigned_tasks.append(fixture_id)
        obs["repeat"] = a["repeat"] if frozen is not None else recorded_for_task + 1
        obs["assignment_slot"] = assigned_tasks.index(fixture_id) + 1
        per_task_prev_ts[tid] = ts
        empty.pop(0).update(obs)
        imported[idx] = (cell_id, obs)
        # mark cell filled when it has no empties left
        if not empties[cell_id]:
            cell["filled"] = True
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
    import_findings = []

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
        violations = check_integrity(sheet)
        if violations:
            print("live_fill_tally: existing sheet is invalid; preserved for reconciliation", file=__import__("sys").stderr)
            return 1
        entries = load_ledger(Path(args.import_ledger))
        amap = json.loads(Path(args.assignments).read_text(encoding="utf-8"))
        findings = import_from_ledger(sheet, entries, amap)
        import_findings = findings
        sheet_p.write_text(json.dumps(sheet, indent=2, ensure_ascii=False, sort_keys=True) + chr(10),
                           encoding="utf-8", newline=chr(10))
        if findings:
            print("live_fill_tally --import: FINDINGS (re-derivable, nothing silently dropped):",
                  file=__import__("sys").stderr)
            for f in findings:
                print("  -", f, file=__import__("sys").stderr)
        n_filled = sum(1 for c in sheet["cells"].values() if c.get("filled"))
        print(f"import done: sheet written to {sheet_p}; findings: {len(findings)}; "
              f"cells marked filled: {n_filled}")
        if getattr(args, "mode", "full") != "gate":
            # fall through to the normal tally print so the same invocation tallies
            pass
        else:
            return 1 if findings or check_integrity(sheet) else 0

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

    summary = tally_summary(sheet)
    problems = summary["problems"]
    if problems:
        print("live_fill_tally: invalid sheet — " + "; ".join(problems), file=__import__("sys").stderr)
        return 1

    per_arm: Dict[str, int] = {arm: 0 for arm in sheet["arms"]}
    cells_filled = 0
    print(f"{'cell':6} {'recorded':>8} {'planned':>8} {'filled':>6}")
    for cell_id in sorted(sheet["cells"]):
        c = sheet["cells"][cell_id]
        n = summary["per_cell"][cell_id]["recorded"]
        per_arm[c["arm"]] += n
        tag = "yes" if c.get("filled") else "no"
        cells_filled += 1 if c.get("filled") else 0
        print(f"{cell_id:6} {n:>8} {c['planned_observations']:>8} {tag:>6}")
    recorded = sum(per_arm.values())
    print()
    for arm, n in per_arm.items():
        target = sheet["observations_per_arm_target"]
        status = "OK" if n >= target else f"{target - n} to go"
        print(f"arm {arm}: {n}/{target} observations ({status})")
    print(f"\ncells filled: {cells_filled}/{len(sheet['cells'])} · "
          f"observations recorded: {recorded}/{target * len(per_arm)}")

    if problems or import_findings:
        print("\nINTEGRITY VIOLATIONS:", file=__import__("sys").stderr)
        for pr_ in problems:
            print("  -", pr_, file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
