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
  T13 egress reserves worst-case cost (expected input + the dispatch_fn's
      max_tokens, long-context tier included) before any send, settles to
      actual usage, and records a send that overran its reservation
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

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
    check("T1 reservation then settlement written", len(es) == 2 and es[0]["task_id"] == "T1"
          and es[0]["decision"] == "dispatch-reserved" and es[1]["decision"] == "dispatched", str(len(es)))

# T2 attempt cap -----------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    d = new(tmp)
    # alternate profiles so the repair allowance is never what fires:
    # the §5 attempt cap counts 4 physical dispatches regardless of arm;
    # this counter-only fixture has local checks and no model review slots.
    for pid in ("cloud-S", "cloud-C", "cloud-S", "cloud-C-alt"):
        d.attempt("T2", pid, "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000, expected_out=1_000, review_calls=0)
    e = d.attempt("T2", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000, expected_out=1_000)
    check("T2 attempt cap rejects 5th", e.decision == "blocked-attempt-cap", e.reason)
    check("T2 ledger records block", len(entries(ledger(tmp))) == 9, str(len(entries(ledger(tmp)))))

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
        d.attempt(f"T8a{i}", "cloud-S", "req", work_bound=0.01, review_bound=0, **small)
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
    fake_dispatch.max_tokens = 1_000
    fake_dispatch.count_tokens = lambda pid, req: 0

    d = new(tmp, dispatch_fn=fake_dispatch, confirm_egress=False)
    d.attempt("T10", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
              expected_in=10_000, expected_out=1_000)
    check("T10 no egress without consent", calls == [], str(calls))

    d2 = new(tmp, dispatch_fn=fake_dispatch, confirm_egress=True)
    e = d2.attempt("T10e", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                   expected_in=10_000)
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

    def record(*args):
        calls.append(args)
        return 10_000, 1_000
    record.max_tokens = 1_000
    record.count_tokens = lambda pid, req: 0
    d = new(tmp, confirm_egress=True, dispatch_fn=record)
    for idx, value in enumerate((float('nan'), float('inf'), -float('inf'),
                                 -0.01, True, '0.01', 10**1000)):
        for field in ('work_bound', 'review_bound'):
            bounds = {'work_bound': 0.01, 'review_bound': 0.01, field: value}
            e = d.attempt(f'numeric-{field}-{idx}', 'cloud-C', 'req', expected_in=1_000,
                          **bounds)
            check(f'T12 {field} invalid case {idx}', e.decision == 'blocked-gate4')
    e = d.attempt('overflow-sum', 'cloud-C', 'req', work_bound=1e308, review_bound=1e308,
                  expected_in=1_000)
    check('T12 sum overflow refused', e.decision == 'blocked-gate4')
    for value in (True, -1, 1.5):
        e = d.attempt('bad-tokens', 'cloud-C', 'req', work_bound=0.01,
                      review_bound=0.01, expected_in=value)
        check('T12 invalid expected tokens refused', e.decision == 'blocked-gate4')
    bad_prices = prices()
    bad_prices['profiles']['cloud-C']['input_rate_per_mtok'] = float('nan')
    bad = ld.LiveDispatcher(bad_prices, tmp / 'bad-rate.jsonl', confirm_egress=True,
                            dispatch_fn=record)
    e = bad.attempt('bad-rate', 'cloud-C', 'req', work_bound=0.01, review_bound=0.01,
                    expected_in=1_000)
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


# T13 reserve worst-case cost before any send (usage review F01) ------------------------------
def transport(returns, max_tokens, counts=None):
    """Fake dispatch_fn: hands back queued (in, out) usage, declares its output
    ceiling, and counts each prompt as the next queued count (0 when none)."""
    calls = []

    def fn(pid, req):
        calls.append(pid)
        return returns.pop(0)

    def count_tokens(pid, req):
        fn.counted.append((pid, req))
        return counts.pop(0) if counts else 0
    fn.max_tokens = max_tokens
    fn.count_tokens = count_tokens
    fn.counted = []
    return fn, calls


with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # F01 repro: the first send fills the $1.00 task cap exactly
    # (495k in @ $2 + 1k out @ $10); the second must not reach the transport
    fn, calls = transport([(495_000, 1_000), (1_000, 100)], max_tokens=1_000)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e1 = d.attempt("T13", "cloud-S", "req", work_bound=1.00, review_bound=0,
                   expected_in=495_000)
    e2 = d.attempt("T13", "cloud-C", "req", work_bound=0.01, review_bound=0,
                   expected_in=1_000)
    check("T13 first send fills task cap", e1.decision == "dispatched"
          and abs(e1.cost_usd - 1.00) < 1e-9, f"{e1.decision} {e1.cost_usd}")
    check("T13 no send without task headroom", calls == ["cloud-S"], str(calls))
    check("T13 blocked before send", e2.decision == "blocked-cost-cap", e2.reason)
    check("T13 block consumed no tokens", (e2.input_tokens, e2.output_tokens, e2.cost_usd)
          == (0, 0, 0.0), str(e2))

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # the reservation prices the transport's max_tokens, not the caller's expected_out:
    # 300k in @ $2 + 50k out @ $10 = $1.10 > cap, though this call would cost $0.601
    fn, calls = transport([(300_000, 100)], max_tokens=50_000)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T13b", "cloud-S", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=300_000, expected_out=100)
    check("T13b reservation prices max_tokens", e.decision == "blocked-cost-cap"
          and calls == [], f"{e.decision} {calls}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # long-context tier: after $0.90 spent, a 200k-token Haiku prompt reserves
    # 200k @ $0.50 + 4096 @ $2.50 = $0.110 > $0.10 headroom (base tier would say $0.022)
    fn, calls = transport([(445_000, 1_000), (200_000, 100)], max_tokens=4_096)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    d.attempt("T13c", "cloud-S", "req", work_bound=0.01, review_bound=0.01,
              expected_in=445_000)
    e = d.attempt("T13c", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=200_000)
    check("T13c long-context tier reserved", e.decision == "blocked-cost-cap"
          and calls == ["cloud-S"], f"{e.decision} {calls}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # pilot cap: 22 tasks x $0.90 = $19.80; the next reserves 100k @ $2 + 4096 @ $10
    # = $0.241 > $0.20 pilot headroom and must not be sent
    fn, calls = transport([(445_000, 1_000)] * 22 + [(1_000, 100)], max_tokens=4_096)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    for i in range(22):
        d.attempt(f"T13d{i}", "cloud-S", "req", work_bound=0.01, review_bound=0,
                  expected_in=445_000)
    e = d.attempt("T13d-next", "cloud-S", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=100_000)
    check("T13d pilot headroom checked before send", e.decision == "blocked-pilot-cap"
          and len(calls) == 22, f"{e.decision} {len(calls)}")
    check("T13d pilot spend stays <= cap", d.pilot_spent <= 20.0, str(d.pilot_spent))

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # settle to actual usage, not the reservation
    fn, calls = transport([(9_000, 200)], max_tokens=4_096)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T13e", "cloud-S", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=10_000)
    check("T13e settles to actual cost", e.decision == "dispatched"
          and (e.input_tokens, e.output_tokens) == (9_000, 200)
          and abs(e.cost_usd - 0.02) < 1e-9 and abs(d.pilot_spent - 0.02) < 1e-9,
          f"{e.cost_usd} {d.pilot_spent}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # an underestimated prompt overruns its reservation: the money is already
    # spent, so the send is recorded at actual cost, never dropped as a $0 block
    fn, calls = transport([(600_000, 100), (1_000, 100)], max_tokens=4_096)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T13f", "cloud-S", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=1_000)
    check("T13f overrun recorded as dispatched", e.decision == "dispatched"
          and abs(e.cost_usd - 1.201) < 1e-9, f"{e.decision} {e.cost_usd}")
    check("T13f overrun counted", abs(d.pilot_spent - 1.201) < 1e-9
          and d._task("T13f")["attempts"] == 1, str(d.pilot_spent))
    check("T13f overrun flagged in reason", "reservation" in e.reason, e.reason)
    e2 = d.attempt("T13f", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                   expected_in=1_000)
    check("T13f no send once over cap", e2.decision == "blocked-cost-cap"
          and len(calls) == 1, f"{e2.decision} {calls}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # fail-closed: egress without a declared output ceiling or a token counter
    # cannot reserve a worst case, so nothing is sent and no attempt is consumed
    calls = []

    def bare(pid, req):
        calls.append(pid)
        return 1_000, 100
    bare.count_tokens = lambda pid, req: 1_000
    d = new(tmp, dispatch_fn=bare, confirm_egress=True)
    for ceiling in ("absent", None, 0, -1, True, 1.5, "4096"):
        if ceiling != "absent":
            bare.max_tokens = ceiling
        e = d.attempt("T13g", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                      expected_in=1_000)
        check(f"T13g bad output ceiling {ceiling!r} refused", e.decision == "blocked-gate4",
              e.reason)
    bare.max_tokens = 4_096
    del bare.count_tokens
    e = d.attempt("T13g", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                  expected_in=1_000)
    check("T13g missing token counter refused", e.decision == "blocked-gate4", e.reason)
    check("T13g nothing sent", calls == [], str(calls))
    check("T13g no attempts consumed", d._task("T13g")["attempts"] == 0)


# T14 egress counts the prompt before reserving, so a low estimate cannot slip through ----------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # review repro: a 1-token placeholder estimate for a prompt the API counts at 300k on
    # cloud-F; 315,000 (count + 5%) @ $10 + 4096 @ $50 = $3.36 > $1.00 cap, so no send
    fn, calls = transport([(300_000, 100)], max_tokens=4_096, counts=[300_000])
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T14", "cloud-F", "big prompt", work_bound=0.01, review_bound=0.01,
                  expected_in=1)
    check("T14 counted prompt beats a low estimate", e.decision == "blocked-cost-cap"
          and calls == [], f"{e.decision} {calls} {e.reason}")
    check("T14 counter saw the request", fn.counted == [("cloud-F", "big prompt")],
          str(fn.counted))

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # with a counter, the caller's estimate is optional
    fn, calls = transport([(1_000, 100)], max_tokens=4_096, counts=[1_000])
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T14b", "cloud-C", "req", work_bound=0.01, review_bound=0.01)
    check("T14b counted send needs no estimate", e.decision == "dispatched"
          and calls == ["cloud-C"], f"{e.decision} {e.reason}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # the margin is applied before the rate tier is chosen: Haiku counted at 99,000
    # reserves 103,950 tokens at the >100k rate ($0.0622), which does not fit the $0.05
    # left after $0.95; at the base tier it would have reserved only $0.0119
    fn, calls = transport([(470_000, 1_000), (99_000, 100)], max_tokens=4_096,
                          counts=[0, 99_000])
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    d.attempt("T14c", "cloud-S", "req", work_bound=0.01, review_bound=0.01,
              expected_in=470_000)
    e = d.attempt("T14c", "cloud-C", "req", work_bound=0.01, review_bound=0.01)
    check("T14c margin can cross the long-context tier", e.decision == "blocked-cost-cap"
          and calls == ["cloud-S"], f"{e.decision} {calls} {e.reason}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # a count that fails or is not a non-negative int raises before the send, like a
    # failed send: no ledger line (a blocked-gate4 line would fill a pilot slot for an
    # infrastructure fault), no attempt consumed, nothing billed
    for bad in ("raise", None, -1, True, 1.5, "1000"):
        fn, calls = transport([(1_000, 100)], max_tokens=4_096)
        if bad == "raise":
            def boom(pid, req):
                raise OSError("count endpoint unreachable")
            fn.count_tokens = boom
        else:
            fn.count_tokens = lambda pid, req, v=bad: v
        d = new(tmp, dispatch_fn=fn, confirm_egress=True)
        before = len(entries(ledger(tmp)))
        try:
            d.attempt(f"T14d-{bad}", "cloud-C", "req", work_bound=0.01, review_bound=0.01,
                      expected_in=1_000)
            raised = False
        except (OSError, ValueError):
            raised = True
        check(f"T14d bad count {bad!r} raises before send", raised and calls == []
              and d._task(f"T14d-{bad}")["attempts"] == 0, str(calls))
        check(f"T14d bad count {bad!r} writes no ledger line",
              len(entries(ledger(tmp))) == before)

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # an attempt an earlier gate refuses never reaches the counter
    fn, calls = transport([], max_tokens=4_096)
    d = new(tmp, dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T14e", "cloud-S", "req", work_bound=0.90, review_bound=0.20,
                  expected_in=1_000)
    check("T14e no count after a Gate-4 refusal", e.decision == "blocked-gate4"
          and fn.counted == [], str(fn.counted))

with tempfile.TemporaryDirectory() as td:
    # end to end through the real adapter with mocked transports: the count blocks the
    # send, and the count payload carries no max_tokens
    import dispatch_adapter as da
    sent, counted = [], []
    fn = da.build_dispatch_fn(api_key="placeholder", env_fallback={},
                              transport=lambda p, m, k: sent.append(m) or (1, 1),
                              count_transport=lambda p, m, k: counted.append(
                                  (m, "max_tokens" in p)) or 300_000)
    d = new(Path(td), dispatch_fn=fn, confirm_egress=True)
    e = d.attempt("T14f", "cloud-F", "x", work_bound=0.01, review_bound=0.01, expected_in=1)
    check("T14f adapter count blocks before send", e.decision == "blocked-cost-cap"
          and sent == [] and counted == [("claude-fable-5-1", False)], f"{e.decision} {counted}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # the deadline is checked again after the count: a count that takes 30 s at 290 s
    # into the task must not let the send start past the 300 s cap
    clock = [1_000.0]
    fn, calls = transport([(1_000, 100)], max_tokens=4_096)

    def slow_count(pid, req):
        clock[0] += 30.0
        return 1_000
    fn.count_tokens = slow_count
    d = new(tmp, dispatch_fn=fn, confirm_egress=True, now_fn=lambda: clock[0])
    d._task("T14g")
    clock[0] = 1_290.0
    e = d.attempt("T14g", "cloud-C", "req", work_bound=0.01, review_bound=0.01)
    check("T14g deadline rechecked after the count", e.decision == "blocked-deadline"
          and calls == [], f"{e.decision} {calls}")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    # the CLI refuses a profile with no approved Anthropic mapping as dispatch-refused,
    # exit 2, before any request and without a ledger line
    import dispatch_adapter as da
    sent, counted = [], []
    real_build = da.build_dispatch_fn
    da.build_dispatch_fn = lambda: real_build(
        api_key="placeholder", env_fallback={},
        transport=lambda p, m, k: sent.append(m) or (1, 1),
        count_transport=lambda p, m, k: counted.append(m) or 1)
    try:
        rc = ld.main(["--live", "--confirm-egress", "--profile", "cloud-C-alt",
                      "--task-id", "T14h", "--request", "x", "--work-bound", "0.01",
                      "--review-bound", "0.01", "--ledger", str(ledger(tmp))])
    finally:
        da.build_dispatch_fn = real_build
    check("T14h unmapped profile exits 2", rc == 2, str(rc))
    check("T14h refusal sends nothing, no ledger line", sent == [] and counted == []
          and entries(ledger(tmp)) == [], f"{sent} {counted}")

# T16 real adapter/HTTP/CLI producer path, with synthetic qualification and IO.
import pilot_report
from test_billing_qualification import synthetic_fixture


class Body:
    def __init__(self, raw):
        self.raw = raw
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def read(self):
        return self.raw


for label, raw in (("no usage block", b'{"id":"synthetic","content":[]}'),
                   ("non-JSON body", b"<html>synthetic gateway</html>")):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        import dispatch_adapter as da
        qualification, price_path, _ = synthetic_fixture(tmp)
        sent = []
        real_build = da.build_dispatch_fn
        fn = real_build(api_key="placeholder", qualification_path=qualification,
                        prices_path=price_path, now_fn=lambda: 1500,
                        count_transport=lambda *args: 1000)
        def fake_open(req, timeout):
            sent.append(req.full_url)
            return Body(raw)
        def run(task_id):
            return ld.main(["--live", "--confirm-egress", "--profile", "cloud-S", "--task-id", task_id,
                            "--request", "synthetic", "--work-bound", "0.05", "--review-bound", "0.01",
                            "--ledger", str(ledger(tmp))])
        with patch.object(da, "build_dispatch_fn", return_value=fn), patch.object(da._HTTP_OPENER, "open", fake_open):
            rc, rc_next = run("T16"), run("T16-next")
        es = entries(ledger(tmp))
        errors = [e for e in es if e["task_id"] == "T16" and e["decision"] == "dispatch-error"]
        check(f"T16 {label}: actual HTTP producer retains unknown usage", rc == 1 and len(errors) == 1
              and sent == [da.APPROVED_ENDPOINT + "/v1/messages"]
              and (errors[0]["input_tokens"], errors[0]["output_tokens"], errors[0]["cost_usd"]) == (None, None, None),
              str((rc, sent, errors)))
        report = pilot_report.build_report(prices(), es)
        check(f"T16 {label}: report remains incomplete", report["accounting_status"] == "GAPS_FOUND"
              and not report["pilot"]["total_spend_complete"], str(report["problems"]))
        check(f"T16 {label}: next task is not sent", rc_next == 1 and len(sent) == 1
              and es[-1]["decision"] == "blocked-uncertain", str(es[-1]))

# T17 a relative CLI ledger is repository-relative from either caller directory.
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    one, two = root / "one", root / "two"
    one.mkdir()
    two.mkdir()
    absolute_ledger = root / "pilot" / "ledger.jsonl"
    relative_ledger = os.path.relpath(absolute_ledger, ld.REPO_ROOT)
    argv = [sys.executable, str(Path(ld.__file__).resolve()), "--profile", "cloud-C", "--task-id", "T17",
            "--request", "synthetic", "--work-bound", "0.01", "--review-bound", "0.01",
            "--expected-in-tokens", "1000", "--expected-out-tokens", "100", "--ledger", relative_ledger]
    results = [subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=30) for cwd in (one, two)]
    observed = [json.loads(result.stdout) for result in results]
    check("T17 caller directory does not create a new authority", [e["attempt_no"] for e in observed] == [1, 2]
          and all(result.returncode == 0 for result in results), str(observed))
    check("T17 absolute target holds both physical reservations", absolute_ledger.is_file()
          and len([e for e in entries(absolute_ledger) if e["decision"] == "dispatch-reserved"]) == 2,
          str(absolute_ledger))

print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
sys.exit(0 if failures == 0 else 1)
