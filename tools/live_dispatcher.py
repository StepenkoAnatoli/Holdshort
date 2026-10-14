#!/usr/bin/env python3
"""Live Phase 4 pilot dispatcher — minimal, fail-closed, ledger-writing.

Reads tools/prices-2.json (the machine-readable rate sheet), enforces the §5
caps from the merged preregistration (docs/PHASE3_PREREGISTRATION.md), applies
the plan §8 Gate-4 affordability contract, and records every disposition as a
JSON Lines entry in the pilot observation ledger (append-only).

§5 caps enforced (structural rules plan §7-8; numeric values from prices-2):
  * max attempts per task (any arm), counting physical dispatches; hidden
    host retries belong to the caller's dispatch_fn and its token counts
  * max cost per task and per pilot (USD)
  * max elapsed wall-clock per task — time must be strictly before the
    deadline to pass; equality expires (plan §8)
  * at most N same-profile repairs per task; restart/rename never resets
    counters

Gate-4 blocks (affordability, fail-closed):
  * absent price bound for a profile -> blocked as `unknown-profile`, never
    zero-filled (S06 semantics: unpriced means ineligible to dispatch)
  * all-in work+review bound > per-task cap -> blocked before dispatch
  * a dispatch whose modeled cost would push task or pilot spend past its cap
    -> blocked

Egress is opt-in only: without --confirm-egress no network call is emitted at
all (dry-run mode; callers supply token counts via --expected-*-tokens). With
--live the real Anthropic adapter (tools/dispatch_adapter.py) is wired as the
dispatch_fn — still gated on --confirm-egress; --live alone never sends.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import redaction
except ImportError:
    from tools import redaction

try:
    from task_persistence import TaskStateStore, ResumableTasks, CorruptState
except ImportError:  # direct import when repo root on path
    from tools.task_persistence import TaskStateStore, ResumableTasks, CorruptState

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "tools" / "prices-2.json"
LEDGER_DEFAULT = REPO_ROOT / "tools" / "pilot_ledger.jsonl"
TASK_STATE_DEFAULT = REPO_ROOT / "tools" / "task_state"

REASON_MAX = 512  # bounded ledger lines, per the pilot observation rules


def finite_nonnegative(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


@dataclass
class CapConfig:
    max_attempts: int
    max_cost_per_task: float
    max_cost_per_pilot: float
    max_seconds_per_task: int
    same_profile_repairs: int


@dataclass
class LedgerEntry:
    ts: float
    task_id: str
    attempt_no: Optional[int]
    profile_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    decision: str
    reason: str


def load_prices(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("revision") != "prices-2":
        raise SystemExit(
            f"unexpected prices revision {doc.get('revision')!r} in {path} — stop, do not guess rates"
        )
    return doc


class LiveDispatcher:
    """Enforces §5 caps and Gate-4 blocks; one ledger line per disposition."""

    def __init__(
        self,
        prices: dict,
        ledger_path: Path,
        *,
        now_fn: Callable[[], float] = time.time,
        dispatch_fn: Optional[Callable[[str, str], Tuple[int, int]]] = None,
        confirm_egress: bool = False,
        task_store: Optional[Path] = None,
    ) -> None:
        caps = prices["pilot_caps"]
        for key in ("max_cost_per_task_usd", "max_cost_per_pilot_usd",
                    "max_elapsed_seconds_per_task"):
            if not finite_nonnegative(caps.get(key)):
                raise ValueError("pilot monetary and time caps must be finite and non-negative")
        for key in ("max_attempts_per_task", "same_profile_repairs_allowed_per_task"):
            if type(caps.get(key)) is not int or caps[key] < 0:
                raise ValueError("pilot attempt and repair caps must be non-negative integers")
        self.caps = CapConfig(
            caps["max_attempts_per_task"],
            caps["max_cost_per_task_usd"],
            caps["max_cost_per_pilot_usd"],
            caps["max_elapsed_seconds_per_task"],
            caps["same_profile_repairs_allowed_per_task"],
        )
        self.prices = prices
        self.ledger_path = Path(ledger_path)
        self.now_fn = now_fn
        self.dispatch_fn = dispatch_fn
        self.confirm_egress = confirm_egress
        self.pilot_spent = 0.0
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # optional per-task state persistence — attempt counters + wall-clock
        # anchor survive process restarts (plan §7: restart/rename never resets)
        if task_store is not None:
            self._resumer = ResumableTasks(TaskStateStore(Path(task_store), now_fn=now_fn))
        else:
            self._resumer = None

    # -- internals ---------------------------------------------------------
    def _task(self, task_id: str) -> Dict[str, Any]:
        if task_id not in self._tasks:
            init = lambda: {  # noqa: E731 — clear inline shape for the initializer
                "task_id": task_id,
                "attempts": 0,
                "spent": 0.0,
                "started": self.now_fn(),
                "repairs": 0,
                "last_profile": "",
            }
            if self._resumer is not None:
                st = self._resumer.load_or_init(task_id, init)
            else:
                st = init()
            self._tasks[task_id] = st
        return self._tasks[task_id]

    def _append(self, entry: LedgerEntry) -> None:
        rec = dict(asdict(entry))
        rec, _ = redaction.redact_obj(rec)  # redact BEFORE truncating the reason
        rec["reason"] = str(rec["reason"])[:REASON_MAX]
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    def _reject(
        self,
        st: Dict[str, Any],
        profile_id: str,
        decision: str,
        reason: str,
        in_toks: int = 0,
        out_toks: int = 0,
    ) -> LedgerEntry:
        e = LedgerEntry(self.now_fn(), st["task_id"], st["attempts"], profile_id,
                        in_toks, out_toks, 0.0, decision, reason)
        self._append(e)
        return e

    @staticmethod
    def _cost(profile: dict, in_toks: int, out_toks: int) -> float:
        return (profile["input_rate_per_mtok"] * in_toks
                + profile["output_rate_per_mtok"] * out_toks) / 1_000_000.0

    # -- public ------------------------------------------------------------
    def attempt(
        self,
        task_id: str,
        profile_id: str,
        request: str,
        *,
        work_bound: float,
        review_bound: float,
        expected_in: int = 0,
        expected_out: int = 0,
    ) -> LedgerEntry:
        """One physical dispatch, or a gated rejection. Never zero-fills a price."""
        profile = self.prices["profiles"].get(profile_id)
        try:
            st = self._task(task_id)
        except CorruptState:
            # No dispatch and no replacement state: record only the refusal.
            # Unknown counters remain on disk for explicit recovery.
            e = LedgerEntry(self.now_fn(), task_id, None, profile_id, 0, 0, 0.0,
                            "blocked:state-corrupt", "persisted state unreadable or invalid; preserved")
            self._append(e)
            return e

        # 1) unknown profile — Gate-4 fail-closed (plan §8: unpriced blocks; S06)
        if profile is None:
            return self._reject(st, profile_id, "unknown-profile",
                                f"{profile_id!r} absent from prices-2.json (Gate-4 fail-closed)")

        # NaN comparisons are false: reject non-finite inputs explicitly before
        # any transport or counter mutation, rather than treating them as free.
        if (not finite_nonnegative(work_bound) or not finite_nonnegative(review_bound)
                or not finite_nonnegative(work_bound + review_bound)
                or not isinstance(profile, dict)
                or any(not finite_nonnegative(profile.get(k)) for k in
                       ("input_rate_per_mtok", "output_rate_per_mtok"))
                or any(type(t) is not int or t < 0 for t in (expected_in, expected_out))):
            return self._reject(st, profile_id, "blocked-gate4",
                                "invalid numeric bound, rate, or expected token count")

        # 2) §5 attempt cap (counts every dispatch, any arm)
        if st["attempts"] >= self.caps.max_attempts:
            return self._reject(st, profile_id, "blocked-attempt-cap",
                                f"attempt cap reached: {st['attempts']}/{self.caps.max_attempts}")

        # 3) §5 wall-clock deadline (strictly-before rule: equality expires)
        now = self.now_fn()
        # Retain a high-water mark across optional persisted task restarts.
        # An observed rollback is terminal: a later forward jump cannot renew it.
        previous = st.get("last_observed", st["started"])
        if st.get("clock_stopped", False) or now < previous:
            st["clock_stopped"] = True
            if self._resumer is not None:
                self._resumer.persist(st)
            return self._reject(st, profile_id, "blocked-deadline",
                                "task stopped after an observed wall-clock rollback")
        st["last_observed"] = now
        if self._resumer is not None:
            self._resumer.persist(st)
        if now - st["started"] >= self.caps.max_seconds_per_task:
            return self._reject(st, profile_id, "blocked-deadline",
                                f"elapsed {now - st['started']:.0f}s >= cap {self.caps.max_seconds_per_task}s")

        # 4) Gate-4 preflight: all-in work+review bound must fit the per-task cap
        all_in = work_bound + review_bound
        if all_in > self.caps.max_cost_per_task:
            return self._reject(st, profile_id, "blocked-gate4",
                                f"all-in bound ${all_in:.2f} > cap ${self.caps.max_cost_per_task:.2f}")

        # 5) §5 repair accounting: a same-profile repeat consumes the repair
        #    allowance; restart/rename never resets counters. The allowance is
        #    only consumed when the repair dispatch actually happens — a
        #    dispatch rejected below does not burn the repair.
        is_repair = bool(st["last_profile"]) and profile_id == st["last_profile"]
        if is_repair and st["repairs"] >= self.caps.same_profile_repairs:
            return self._reject(st, profile_id, "blocked-repair-cap",
                                f"exceeded {self.caps.same_profile_repairs} same-profile repair(s)")

        # 6) token counts: live calls only through dispatch_fn under egress consent
        if self.confirm_egress:
            if self.dispatch_fn is None:
                raise RuntimeError(
                    "confirm_egress set but no dispatch_fn wired — fail-closed, refusing egress"
                )
            in_toks, out_toks = self.dispatch_fn(profile_id, request)
        else:
            in_toks, out_toks = expected_in, expected_out

        cost = self._cost(profile, in_toks, out_toks)

        # 7) per-task cost cap (equality passes: spent + cost <= limit)
        if st["spent"] + cost > self.caps.max_cost_per_task:
            return self._reject(st, profile_id, "blocked-cost-cap",
                                f"dispatch ${cost:.4f} puts task at ${st['spent'] + cost:.2f}"
                                f" > cap ${self.caps.max_cost_per_task:.2f}", in_toks, out_toks)

        # 8) pilot-level cost cap
        if self.pilot_spent + cost > self.caps.max_cost_per_pilot:
            return self._reject(st, profile_id, "blocked-pilot-cap",
                                f"dispatch ${cost:.4f} puts pilot at ${self.pilot_spent + cost:.2f}"
                                f" > cap ${self.caps.max_cost_per_pilot:.2f}", in_toks, out_toks)

        st["attempts"] += 1
        st["spent"] += cost
        self.pilot_spent += cost
        if is_repair:
            st["repairs"] += 1
        st["last_profile"] = profile_id
        if self._resumer is not None:
            self._resumer.persist(st)
        e = LedgerEntry(now, task_id, st["attempts"], profile_id, in_toks, out_toks, cost,
                        "dispatched", f"attempt {st['attempts']} of {self.caps.max_attempts}")
        self._append(e)
        return e


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Live Phase 4 pilot dispatcher (fail-closed)")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--request", required=True)
    ap.add_argument("--work-bound", type=float, required=True,
                    help="work-call price bound (USD, all-in) used for the Gate-4 preflight")
    ap.add_argument("--review-bound", type=float, required=True,
                    help="required-check price bound (USD) for the Gate-4 preflight")
    ap.add_argument("--expected-in-tokens", type=int, default=0,
                    help="dry-run mode: input tokens the dispatch would use")
    ap.add_argument("--expected-out-tokens", type=int, default=0,
                    help="dry-run mode: output tokens the dispatch would use")
    ap.add_argument("--confirm-egress", action="store_true",
                    help="permit a real network dispatch (Phase 4 owner authorization required)")
    ap.add_argument("--live", action="store_true",
                    help="wire the real Anthropic adapter as dispatch_fn (requires .env key and --confirm-egress)")
    ap.add_argument("--ledger", default=str(LEDGER_DEFAULT))
    ap.add_argument("--task-store", default=None,
                    help="per-task state dir so attempt counters + 300s deadline survive "
                         "process restarts (default: off = per-process counters, as before)")
    args = ap.parse_args(argv)

    prices = load_prices(PRICES_PATH)

    dispatch_fn = None
    if args.live:
        from dispatch_adapter import build_dispatch_fn, DispatchRefused
        try:
            dispatch_fn = build_dispatch_fn()  # refuses without .env key or on non-approved endpoint
        except DispatchRefused as e:
            print(json.dumps({"decision": "dispatch-refused", "reason": str(e)}), file=sys.stderr)
            return 2

    task_store = Path(args.task_store) if args.task_store else None
    d = LiveDispatcher(prices, Path(args.ledger), confirm_egress=args.confirm_egress,
                       dispatch_fn=dispatch_fn, task_store=task_store)
    e = d.attempt(args.task_id, args.profile, args.request,
                  work_bound=args.work_bound, review_bound=args.review_bound,
                  expected_in=args.expected_in_tokens, expected_out=args.expected_out_tokens)
    print(json.dumps(asdict(e), sort_keys=True))
    return 0 if e.decision == "dispatched" else 1


if __name__ == "__main__":
    sys.exit(main())
