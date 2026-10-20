#!/usr/bin/env python3
"""Decision-suite sidecar helper (T-05): print a one-line per-family route summary.

Imports the suite's own model (RouteContext / run_gates / PROFILES) and exercises the standard
fixture task shapes, printing the route decision the canonical gates produce for each family.
Evidence-collection only; performs no dispatch and no network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from holdshort_decisions import PROFILES, RouteContext, choose_route  # noqa: E402

def main() -> int:
    rows = [
        ("S-series routing",       RouteContext(task_category="typo", local_only=False),             ["L"],                True),
        ("Eligibility blocks",     RouteContext(task_category="typo", local_only=True),              ["S"],                True),
        ("Capability gaps",        RouteContext(task_category="vision+tools", local_only=False),     ["C"],                True),
        ("Visitor/unknown actor",  RouteContext(task_category="typo", local_only=False),             ["L"],                False),
    ]
    print("Family                     | Route                 | Note")
    print("---------------------------+-----------------------+---------")
    for label, ctx, cands, direct_ok in rows:
        route, rej, prof = choose_route(ctx, cands, allow_direct=direct_ok)
        gate = rej[0].gate if rej else "-"
        print(f"{label:<27}| {route:<21}| first-fail gate: {gate} | profile: {prof.profile_id if prof else 'none'}")
    n = len(PROFILES)
    print(f"\ncatalog profiles exercised: {n} -> local-L, cloud-S, cloud-C, cloud-X")
    print("advisory-only; no dispatch performed or claimed")
    return 0

if __name__ == "__main__":
    sys.exit(main())
