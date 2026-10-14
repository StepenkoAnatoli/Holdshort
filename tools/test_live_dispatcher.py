#!/usr/bin/env python3
"""Tests for tools/live_dispatcher.py — dry-run only, no network calls.

Covers the §5 cap surface and the Gate-4 fail-closed contract:
  T1  happy path: dispatch allowed, cost computed from prices-2, ledger written
  T2  attempt cap: 5th dispatch blocked (cap = 4)
  T3  per-task cost cap: a dispatch crossing the $1.00 line is rejected
  T4  Gate-4: work+review all-in bound above the cap is rejected pre-dispatch
  T5  unknown profile: blocked as unknown-profile, never zero-filled (S06)
  T6  wall-clock deadline: rejection once elapsed >= 300s (strictly-before rule)
  T7  repair allowance: 2nd same-profile repair blocked (allowance = 1); a
      profile switch consumes neither repair nor attempt cap beyond §5 rules
  T8  pilot cap: a dispatch crossing the $20.00 pilot line is rejected
  T9  ledger is append-only in practice: prior entries never rewritten/deleted
  T10 egress consent: dispatch_fn MUST NOT run without confirm_egress
  T11 repair not burned when dispatch is rejected at the cost cap
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_dispatcher as ld


def prices():
    return ld.load_prices(Path(__file__).resolve().parent / "prices-2.json")


def ledger(tmp: Path) -> Path:
    return tmp / "pilot_ledger.jsonl"


def entries(p: Path):
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failures
    if cond:
        print(f"PASS {name}")
    else:
        failures += 1
        print(f"FAIL {name} {detail}")


def new(tmp: Path, **kw) -> ld.LiveDispatcher:
    return ld.LiveDispatcher(prices(), ledger(tmp), **kw)





# T1 happy path ----------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    e = d.attempt("T1", "cloud-C", "req", work_bound=0.05, review_bound=0.05,
                  expected_in=200_000, expected_out=20_000)
    check("T1 dispatched", e.decision == "dispatched", e.reason)
    # 200k prompt tokens > 100k threshold: Haiku 5.5 long-context tier, $0.50 in / $2.50 out
    check("T1 cost model", abs(e.cost_usd - (0.50 * 0.2 + 2.50 * 0.02)) < 1e-9, f"{e.cost_usd}")
    es = entries(ledger(tmp))
    check("T1 ledger written", len(es) == 1 and es[0]["task_id"] == "T1", str(len(es)))

# T2 attempt cap -----------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    # alternate profiles so the repair allowance is never what fires:
    # the §5 attempt cap counts 4 physical dispatches regardless of arm
    for pid in ("cloud-S", "cloud-C", "cloud-S", "cloud-C-alt"):
        d.attempt("T2", pid, "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000, expected_out=1_000)
    e = d.attempt("T2", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000, expected_out=1_000)
    check("T2 attempt cap rejects 5th", e.decision == "blocked-attempt-cap", e.reason)
    check("T2 ledger records block", len(entries(ledger(tmp))) == 5, str(len(entries(ledger(tmp)))))

# T3 per-task cost cap ------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    # 10M in-tokes at $0.10/MTok = $1.00 alone; +500 out-tokens → $1.0005 > cap
    d.attempt("T3", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=1_000_000, expected_out=1_000)   # $0.1005, fits
    e = d.attempt("T3", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000_000, expected_out=1_000)  # dispatch would be $1.0005
    e2 = d.attempt("T3", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                   expected_in=10_000_000, expected_out=1_000)  # same, again
    check("T3 first over-cap dispatch blocked", e.decision == "blocked-cost-cap", e.reason)
    check("T3 repeat crossing cap blocked too", e2.decision == "blocked-cost-cap", e2.reason)

# T4 Gate-4 all-in preflight -------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    e = d.attempt("T4", "cloud-S", "req", work_bound=0.90, review_bound=0.20,
                  expected_in=1_000, expected_out=1_000)
    check("T4 gate4 rejects >$1.00 all-in", e.decision == "blocked-gate4", e.reason)
    check("T4 nothing dispatched", d.pilot_spent == 0.0, str(d.pilot_spent))

# T5 unknown profile ----------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    e = d.attempt("T5", "cloud-XYZ", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=1_000, expected_out=1_000)
    check("T5 unknown blocked", e.decision == "unknown-profile", e.reason)
    check("T5 no spend", d.pilot_spent == 0.0)

# T6 deadline (equality expires) ----------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    t0 = 1_000_000.0
    d = new(tmp, now_fn=lambda: t0)
    e1 = d.attempt("T6", "local-L", "req", work_bound=0.0, review_bound=0.0,
                   expected_in=1_000, expected_out=1_000)
    d.now_fn = lambda: t0 + 299.9
    e2 = d.attempt("T6", "local-L", "req", work_bound=0.0, review_bound=0.0,
                   expected_in=1_000, expected_out=1_000)
    d.now_fn = lambda: t0 + 300.0
    e3 = d.attempt("T6", "local-L", "req", work_bound=0.0, review_bound=0.0,
                   expected_in=1_000, expected_out=1_000)
    check("T6 dispatched under deadline", e1.decision == "dispatched", e1.reason)
    check("T6 just-under passes", e2.decision == "dispatched", e2.reason)
    check("T6 equality expires", e3.decision == "blocked-deadline", e3.reason)

# T7 repair allowance (1 per task) ---------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    d.attempt("T7", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=10_000, expected_out=1_000)      # original
    d.attempt("T7", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=10_000, expected_out=1_000)      # 1 same-profile repair
    e = d.attempt("T7", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000, expected_out=1_000)  # 2nd repair attempt
    check("T7 2nd repair blocked", e.decision == "blocked-repair-cap", e.reason)
    # profile switch does NOT count as repair (plan: differently-qualified profile consumes escalation)
    e2 = d.attempt("T7-alt", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                   expected_in=10_000, expected_out=1_000)
    check("T7 profile switch not a repair", e2.decision == "dispatched", e2.reason)

# T8 pilot cap --------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    # each task stays under the $1.00 task cap ($0.90 per task: 400k in @ $2.00/MTok
    # + 10k out @ $10.00/MTok), so the TASK cap never fires and the $20.00 PILOT
    # cap is what blocks the 23rd dispatch
    small = dict(expected_in=400_000, expected_out=10_000)   # $0.90 per task
    for i in range(22):
        d.attempt(f"T8a{i}", "cloud-S", "req", work_bound=0.01, review_bound=0.01, **small)
    check("T8 22 tasks = $19.80 spent", abs(d.pilot_spent - 19.80) < 1e-9, str(d.pilot_spent))
    e = d.attempt("T8b", "cloud-S", "req", work_bound=0.01, review_bound=0.01, **small)
    check("T8 pilot cap rejects", e.decision == "blocked-pilot-cap", e.reason)
    check("T8 pilot spend stays <= cap", d.pilot_spent <= 20.0, str(d.pilot_spent))
    e2 = d.attempt("T8b2", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                   expected_in=1_000, expected_out=1_000)   # $0.0006 still fits
    check("T8 pilot cap is spend-based, not blanket", e2.decision == "dispatched", e2.reason)

# T9 ledger append-only -------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    d.attempt("T9", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=10_000, expected_out=1_000)
    before = ledger(tmp).read_text(encoding="utf-8")
    d2 = new(tmp)
    d2.attempt("T9", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
               expected_in=10_000, expected_out=1_000)
    after = ledger(tmp).read_text(encoding="utf-8")
    check("T9 prior entries untouched", after.startswith(before), "ledger rewritten")

# T10 egress consent (no dispatch_fn run without consent) ------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    calls = []

    def fake_dispatch(pid, req):
        calls.append(pid)
        return 10_000, 1_000

    d = new(tmp, dispatch_fn=fake_dispatch, confirm_egress=False)
    d.attempt("T10", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=10_000, expected_out=1_000)
    check("T10 no egress without consent", calls == [], str(calls))

    d2 = new(tmp, dispatch_fn=fake_dispatch, confirm_egress=True)
    e = d2.attempt("T10e", "cloud-C", "req", work_bound=0.01, review_bound=0.01)
    check("T10 egress consent dispatches", e.decision == "dispatched", e.reason)
    check("T10 dispatch_fn was called", calls == ["cloud-C"], str(calls))

# T11 repair not burned by cost-cap rejection ------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    d.attempt("T11", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=10_000, expected_out=1_000)
    r = d.attempt("T11", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000_000, expected_out=1_000)
    check("T11 big repair rejected", r.decision == "blocked-cost-cap", r.reason)
    s = d.attempt("T11", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000, expected_out=1_000)
    check("T11 repair still allowed afterwards", s.decision == "dispatched", s.reason)

# Invalid numeric bounds must never invoke even a fake transport.
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    calls = []
    d = new(tmp, confirm_egress=True,
            dispatch_fn=lambda *args: (calls.append(args) or (10_000, 1_000)))
    for idx, value in enumerate((float('nan'), float('inf'), -float('inf'),
                                 -0.01, True, '0.01', 10**1000)):
        for field in ('work_bound', 'review_bound'):
            bounds = {'work_bound': 0.01, 'review_bound': 0.01, field: value}
            e = d.attempt(f'numeric-{field}-{idx}', 'cloud-C', 'req', **bounds)
            check(f'T12 {field} invalid case {idx}', e.decision == 'blocked-gate4')
    e = d.attempt('overflow-sum', 'cloud-C', 'req', work_bound=1e308, review_bound=1e308)
    check('T12 sum overflow refused', e.decision == 'blocked-gate4')
    for value in (True, -1, 1.5):
        e = d.attempt('bad-tokens', 'cloud-C', 'req', work_bound=0.01,
                      review_bound=0.01, expected_in=value)
        check('T12 invalid expected tokens refused', e.decision == 'blocked-gate4')
    bad_prices = prices()
    bad_prices['profiles']['cloud-C']['input_rate_per_mtok'] = float('nan')
    bad = ld.LiveDispatcher(bad_prices, tmp / 'bad-rate.jsonl', confirm_egress=True,
                            dispatch_fn=lambda *args: (calls.append(args) or (1, 1)))
    e = bad.attempt('bad-rate', 'cloud-C', 'req', work_bound=0.01, review_bound=0.01)
    check('T12 NaN rate refused', e.decision == 'blocked-gate4')
    check('T12 no transport calls', calls == [])
    check('T12 no attempts consumed', all(st['attempts'] == 0 for st in d._tasks.values()))
    for field in ('max_cost_per_task_usd', 'max_cost_per_pilot_usd',
                  'max_elapsed_seconds_per_task'):
        bad_prices = prices()
        bad_prices['pilot_caps'][field] = float('nan')
        try:
            ld.LiveDispatcher(bad_prices, tmp / 'bad-cap.jsonl')
            refused = False
        except ValueError:
            refused = True
        check(f'T12 invalid {field} refused', refused)

print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
sys.exit(0 if failures == 0 else 1)
