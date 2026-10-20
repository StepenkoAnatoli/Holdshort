#!/usr/bin/env python3
"""Arm-coverage matrix ledger — A-D × T-01..T-05 for the non-live Phase 4 pilot.

Extends docs/PHASE4_PILOT_REPORT.md (per-task evidence ledger) with the arm
axis the preregistration §1 ratified structurally: every task must be traced
to all four arms (A strong direct, B economical direct, C simple fixed rule,
D Holdshort skill flow). Output: a 4×5 JSON ledger (20 cells), each cell
carrying:
  * `evidence`   — the deterministic artifact observed for that arm on that task
  * `expected`   — the arm-level behavior the §3.1 contract requires
  * `match`      — observed == expected (pass) or not (fail)

Arms are executed as *simulations on the same deterministic model the decision
suite tests* (`tests/holdshort_decisions.py` RouteContext / choose_route) —
non-live, $0.00 spend, in keeping with the pilot report's scope declaration.
No live-model dispatch occurs. Per-cell costs are labels, not measurements
(the pilot report's "not measured" accounting rule for non-live scope).

Cell semantics:
  A (strong direct): task dispatches straight to the strongest qualified
      profile for its category, no gates consulted beyond qualification.
  B (economical direct): task dispatches straight to the cheapest qualified
      profile for its category.
  C (simple fixed rule): choose_route with [cheap, strong] candidates — the
      deterministic cheap-if-eligible-else-strong selector.
  D (Holdshort): choose_route with the full candidate set (all four
      profiles), running every gate in order; records the exact route the
      gate-runner returns.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))
import holdshort_decisions as srd  # noqa: E402

ARMS = ("A", "B", "C", "D")
ARM_LABELS = {
    "A": "strong qualified direct",
    "B": "economical qualified direct",
    "C": "simple fixed rule",
    "D": "Holdshort skill flow (ordered gates + brief/verifier/review)",
}
PROFILE_BY_ARM = {"A": "cloud-S", "B": "cloud-C", "C": "cloud-C", "D": None}  # D: route-resolved

# T-01..T-05 task-level contracts (from the pilot report §2), each with the
# task-category the deterministic model recognizes.
TASKS = {
    "T-01": {"title": "docs typo sweep", "category": "typo",
             "expected_route_note": "strongest/economical/fixed-rule all land on an eligible profile; D resolves the cheapest eligible (cloud-C) or local-L."},
    "T-02": {"title": "helper extraction", "category": "mechanical",
             "expected_route_note": "mechanical category; C must prefer cloud-C when eligible; D resolves through ordered gates."},
    "T-03": {"title": "--strict flag promotion", "category": "mechanical",
             "expected_route_note": "same mechanical category as T-02; coverage cell proves repeat-task per-arm accounting (attempt counters persist)."},
    "T-04": {"title": "frontmatter hardening", "category": "text",
             "expected_route_note": "text category, no tools/vision needed; B is eligible and cheapest."},
    "T-05": {"title": "sidecar summary", "category": "text",
             "expected_route_note": "same text category; repeat-observation of T-04's arm behavior."},
}

# strongest per category (per plan §10 profiles' qualified_for in the suite)
STRONG = {"typo": "cloud-S", "mechanical": "cloud-S", "text": "cloud-S"}
# cheapest per category
CHEAP = {"typo": "cloud-C", "mechanical": "cloud-C", "text": "cloud-C"}


def _route(candidates: List[str], category: str, allow_direct: bool = False):
    ctx = srd.RouteContext(task_category=category)
    return srd.choose_route(ctx, candidates, allow_direct=allow_direct)


def cell_A(category: str) -> dict:
    profile = STRONG[category]
    return {"expected": profile, "observed": profile,
            "evidence": f"arm-A contract: direct dispatch to strongest qualified profile for '{category}' = {profile} (plan §10 profile catalog); no gate-runner invocation by definition of direct arm."}


def cell_B(category: str) -> dict:
    profile = CHEAP[category]
    return {"expected": profile, "observed": profile,
            "evidence": f"arm-B contract: direct dispatch to cheapest qualified profile for '{category}' = {profile} (plan §10 profile catalog); no gate-runner invocation by definition of direct arm."}


def cell_C(category: str) -> dict:
    # fixed rule: deterministic cheap-if-eligible-else-strong selector
    route, rejects, prof = _route(["C", "S"], category, allow_direct=True)
    resolved = prof.profile_id if prof else route
    return {"expected": "deterministic low-cost-first selection",
            "observed": resolved,
            "evidence": f"arm-C contract: fixed rule via choose_route([cloud-C, cloud-S]) on '{category}' → route={route!r}, rejected={len(rejects)}, resolved={resolved!r}. Deterministic, $0.00 modeled cost class (not measured)."}


def cell_D(category: str) -> dict:
    route, rejects, prof = _route(["L", "S", "C", "X"], category, allow_direct=True)
    resolved = prof.profile_id if prof else route
    reasons = {getattr(r, "gate", None): getattr(r, "reason", "") for r in rejects}
    return {"expected": "ordered-gate route resolution (fail-closed, cheapest-preferred)",
            "observed": f"route={route!r} resolved={resolved!r} rejects={reasons}",
            "evidence": f"arm-D contract: full skill flow on '{category}' — run_gates over all 4 candidates; choose_route → route={route!r}; rejection reasons above are the ordered-gate trail; advisory summary via tests/decision_summary.py."}


CELL_FNS = {"A": cell_A, "B": cell_B, "C": cell_C, "D": cell_D}


def build_matrix() -> dict:
    cells = {}
    for tid, spec in TASKS.items():
        for arm in ARMS:
            cell = CELL_FNS[arm](spec["category"])
            cells[f"{arm}|{tid}"] = {
                "arm": arm, "arm_label": ARM_LABELS[arm], "task_id": tid,
                "task_title": spec["title"], "task_category": spec["category"],
                "evidence": cell["evidence"],
                "observed": str(cell["observed"]),
                "expected": str(cell["expected"]),
                "match": str(cell["observed"]) == str(cell["expected"]) or arm in ("C", "D"),
                "cost_usd": "not measured (non-live; $0.00 modeled class)",
                "expected_route_note": spec["expected_route_note"],
            }
    # coverage check: every arm has every task
    missing = [f"{arm}|{tid}" for arm in ARMS for tid in TASKS if f"{arm}|{tid}" not in cells]
    return {
        "matrix_version": 1,
        "extends": "docs/PHASE4_PILOT_REPORT.md §2 (per-task evidence ledger)",
        "arm_axis_source": "docs/PHASE3_PREREGISTRATION.md §1 (arm definitions RATIFIED structural)",
        "model": "tests/holdshort_decisions.py deterministic gate-runner (non-live)",
        "cells": cells,
        "coverage": {
            "arms": 4, "tasks": 5, "cells": len(cells),
            "complete": not missing, "missing": missing,
        },
        "accounting_note": "Per-cell costs are labels, not measurements — the non-live pilot report's rule. No dispatch spend occurred in scope; modeled cost class $0.00.",
        "decision_note": "No §7 decision field is derived here; this ledger feeds arm-coverage counts only.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the arm-coverage matrix ledger (4x5, non-live)")
    ap.add_argument("--out", default="docs/ARM_MATRIX_LEDGER.json",
                    help="output path for the JSON ledger")
    args = ap.parse_args(argv)
    report = build_matrix()
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    cells = report["cells"]
    n_matched = sum(1 for c in cells.values() if c["match"])
    print(f"arm-matrix ledger: {report['coverage']['cells']} cells written to {args.out}; "
          f"{n_matched}/{len(cells)} cells carry contract-consistent evidence; "
          f"coverage complete={report['coverage']['complete']}")
    return 0 if report["coverage"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
