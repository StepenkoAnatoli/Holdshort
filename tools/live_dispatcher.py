#!/usr/bin/env python3
"""Pilot dispatcher with durable task/pilot reservations and fail-closed accounting.

Work and mandatory verification cash/call slots are reserved before a send.
SQLite coordinates local instances and processes; attempts, clocks and uncertain
usage survive restarts. Known usage settles the reservation; partial or unknown
usage is retained and stops the pilot. The JSONL journal mirror is append-only.
Provider input counts use an estimate plus a margin, so an overrun is recorded
and stops further sends rather than being hidden as a zero-cost rejection.
Egress remains opt-in through confirm_egress. See docs/DISPATCH_ACCOUNTING.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, localcontext
from copy import deepcopy
from pathlib import Path
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import redaction
except ImportError:
    from tools import redaction

try:
    import pricing
except ImportError:
    from tools import pricing

try:
    from task_persistence import TaskStateStore, ResumableTasks, CorruptState
except ImportError:  # direct import when repo root on path
    from tools.task_persistence import TaskStateStore, ResumableTasks, CorruptState

try:
    from dispatch_budget import BudgetStore, BudgetStateError, money, totals
except ImportError:
    from tools.dispatch_budget import BudgetStore, BudgetStateError, money, totals

try:
    from task_state_owner import TaskStateOwner, authority_view
except ImportError:
    from tools.task_state_owner import TaskStateOwner, authority_view

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "tools" / "prices-2.json"
LEDGER_DEFAULT = REPO_ROOT / "tools" / "pilot_ledger.jsonl"
TASK_STATE_DEFAULT = REPO_ROOT / "tools" / "task_state"

REASON_MAX = 512  # bounded ledger lines, per the pilot observation rules
# The token-counting endpoint documents its count as an estimate that can differ
# from the billed input "by a small amount"; reserve this much above it.
TOKEN_COUNT_MARGIN = 0.05


def _priceable(profile: Any) -> bool:
    """Every rate the row can select (incl. long-context tier) is valid."""
    try:
        pricing.validate_profile(profile)
    except (pricing.UnpriceableProfile, OverflowError, TypeError):
        return False
    return True


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
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cost_usd: Optional[float]
    decision: str
    reason: str
    reservation_id: Optional[str] = None
    reserved_cost_usd: float = 0.0
    review_reserved_usd: float = 0.0
    usage_status: str = "not-dispatched"
    purpose: str = "work"
    review_calls_reserved: int = 0
    known_cost_usd: float = 0.0
    settlement_status: Optional[str] = None
    mirror_status: Optional[str] = None
    transport_started_at: Optional[float] = None
    transport_finished_at: Optional[float] = None


class DispatchFailure(RuntimeError):
    """A failed send can carry complete, known usage for durable settlement."""
    def __init__(self, message, *, input_tokens=None, output_tokens=None):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def load_prices(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("revision") != "prices-2":
        raise SystemExit(
            f"unexpected prices revision {doc.get('revision')!r} in {path} — stop, do not guess rates"
        )
    return doc


class LiveDispatcher:
    """Shared, durable work/review reservations; transport runs outside the lock."""

    def __init__(self, prices, ledger_path, *, now_fn=time.time,
                 dispatch_fn=None, confirm_egress=False, task_store=None):
        caps = prices["pilot_caps"]
        for key in ("max_cost_per_task_usd", "max_cost_per_pilot_usd",
                    "max_elapsed_seconds_per_task"):
            if not finite_nonnegative(caps.get(key)):
                raise ValueError("pilot monetary and time caps must be finite and non-negative")
        for key in ("max_attempts_per_task", "same_profile_repairs_allowed_per_task"):
            if type(caps.get(key)) is not int or caps[key] < 0:
                raise ValueError("pilot attempt and repair caps must be non-negative integers")
        self.caps = CapConfig(caps["max_attempts_per_task"], caps["max_cost_per_task_usd"],
                              caps["max_cost_per_pilot_usd"], caps["max_elapsed_seconds_per_task"],
                              caps["same_profile_repairs_allowed_per_task"])
        self.prices = deepcopy(prices)
        self.ledger_path = Path(ledger_path)
        self.now_fn, self.dispatch_fn = now_fn, dispatch_fn
        self.confirm_egress = confirm_egress
        self._tasks = {}
        self._resumer = (ResumableTasks(TaskStateStore(Path(task_store), now_fn=now_fn))
                         if task_store is not None else None)
        self.budget = BudgetStore(ledger_path, asdict(self.caps), task_store)
        self.budget.apply_receipt = self._settle_receipt
        # Sole read path (ADR-0001). The dispatcher never read the host
        # watchdog's state, and v1 of the owner does not change that: no
        # watchdog path is wired here.
        self.owner = TaskStateOwner(
            self.budget,
            mirror=self._resumer.store if self._resumer is not None else None)

    @property
    def pilot_spent(self):
        with self.budget.transaction() as doc:
            return float(totals(doc)[0])

    @property
    def pilot_reserved(self):
        with self.budget.transaction() as doc:
            return float(totals(doc)[1])

    def _remember(self, task):
        st = authority_view(task)
        self._tasks[st["task_id"]] = st
        if self._resumer is not None:
            self._resumer.persist(st)
        return st

    def _task(self, task_id):
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task ID must be a nonempty string")
        # Sole read path (ADR-0001): a corrupt optional mirror still refuses
        # and is preserved; a valid but stale mirror is repaired from the
        # authority, never used to lower it.
        task = self.owner.read(task_id)
        if task is None:
            legacy = self.owner.read_mirror(task_id)
            if legacy and (legacy["attempts"] or legacy["spent"]):
                raise BudgetStateError("task counters have no authoritative reservation history")
            # Creation is a write and stays here (owner v1 is read-only). The
            # existence check is repeated INSIDE the transaction on purpose: the
            # read above ran outside any lock, so a concurrent creator may have
            # added the task in between. Overwriting it here would erase its
            # attempts and charge (a check-then-create race).
            with self.budget.transaction() as doc:
                if task_id not in doc["tasks"]:
                    now = self.now_fn()
                    created = dict(legacy or {"task_id": task_id, "attempts": 0, "started": now,
                                              "repairs": 0, "last_profile": ""})
                    created.pop("spent", None)
                    created.update(charged="0", review_reserved="0", review_calls_reserved=0,
                                   pending=None, verified=False, abandoned=False)
                    created.setdefault("last_observed", created["started"])
                    created.setdefault("clock_stopped", False)
                    doc["tasks"][task_id] = created
                task = doc["tasks"][task_id]
        return self._remember(task)

    def _record(self, doc, task, profile, decision, reason, **kwargs):
        kwargs.setdefault("review_reserved_usd", float(money(task["review_reserved"])))
        kwargs.setdefault("review_calls_reserved", task["review_calls_reserved"])
        entry = LedgerEntry(self.now_fn(), task["task_id"], task["attempts"], profile,
                            0, 0, 0.0, decision, reason, **kwargs)
        BudgetStore.event(doc, asdict(entry))
        self._remember(task)
        return entry

    def _reject(self, st, profile, decision, reason, *, purpose="work"):
        if st["task_id"] not in self._tasks:
            self._task(st["task_id"])
        with self.budget.transaction() as doc:
            return self._record(doc, doc["tasks"][st["task_id"]], profile, decision, reason, purpose=purpose)

    @staticmethod
    def _cost(profile, in_toks, out_toks):
        return float(LiveDispatcher._decimal_cost(profile, in_toks, out_toks))

    @staticmethod
    def _decimal_cost(profile, in_toks, out_toks):
        rates = pricing.select_rates(profile, in_toks)
        with localcontext() as arithmetic:
            arithmetic.prec = 1024
            return (money(rates[0]) * in_toks + money(rates[1]) * out_toks) / Decimal("1000000")

    def _check(self, doc, task, profile, work, review, purpose, review_calls):
        def reject(decision, reason):
            return self._record(doc, task, profile, decision, reason, purpose=purpose)
        if task.get("abandoned", False):
            return reject("blocked-abandoned", "task was abandoned; counters and evidence retained")
        if task["verified"]:
            return reject("blocked-verified", "task already verified; counters and evidence retained")
        if task["attempts"] >= self.caps.max_attempts:
            return reject("blocked-attempt-cap", "task attempt cap reached")
        future_calls = max(task["review_calls_reserved"], review_calls)
        if purpose == "work" and task["attempts"] + 1 + future_calls > self.caps.max_attempts:
            return reject("blocked-attempt-cap", "work would consume calls reserved for mandatory verification")
        if purpose == "verification" and not task["review_calls_reserved"]:
            return reject("blocked-gate4", "verification has no owned call reservation")
        now = self.now_fn()
        if not finite_nonnegative(now):
            return reject("blocked-deadline", "invalid clock observation")
        if task["clock_stopped"] or now < task["last_observed"]:
            task["clock_stopped"] = True
            return reject("blocked-deadline", "task stopped after an observed wall-clock rollback")
        task["last_observed"] = now
        if now - task["started"] >= self.caps.max_seconds_per_task:
            return reject("blocked-deadline", "task deadline reached (equality expires)")
        held = money(task["review_reserved"])
        review = max(held, review) if purpose == "work" else held
        if purpose == "verification" and work > held:
            return reject("blocked-gate4", "verification call exceeds its owned review reservation")
        if money(task["charged"]) + work + (review if purpose == "work" else 0) > money(self.caps.max_cost_per_task):
            return reject("blocked-cost-cap", "work and mandatory verification exceed remaining task headroom")
        if task["pending"] is not None:
            return reject("blocked-uncertain", "task has an unsettled dispatch; reservation retained")
        if doc.get("halted", False):
            return reject("blocked-uncertain", "pilot stopped after unknown usage or a reservation overrun")
        spent, reserved = totals(doc)
        extra = work + review - held if purpose == "work" else Decimal("0")
        if spent + reserved + extra > money(self.caps.max_cost_per_pilot):
            return reject("blocked-pilot-cap", "work and verification exceed remaining shared pilot headroom")
        is_repair = bool(task["last_profile"]) and task["last_profile"] == profile
        if purpose == "work" and is_repair and task["repairs"] >= self.caps.same_profile_repairs:
            return reject("blocked-repair-cap", "same-profile repair cap reached")
        return None

    def attempt(self, task_id, profile_id, request, *, work_bound, review_bound,
                expected_in=0, expected_out=0, purpose="work", review_calls=None):
        try:
            return self._attempt(task_id, profile_id, request, work_bound=work_bound,
                                 review_bound=review_bound, expected_in=expected_in,
                                 expected_out=expected_out, purpose=purpose, review_calls=review_calls)
        except CorruptState:
            return LedgerEntry(self.now_fn(), task_id, None, profile_id, None, None, None,
                               "blocked:state-corrupt", "persisted state invalid; preserved", usage_status="unknown", purpose=purpose)
        except BudgetStateError as exc:
            safe_reason, _ = redaction.redact_text(str(exc))
            return LedgerEntry(self.now_fn(), task_id, None, profile_id, None, None, None,
                               "blocked:budget-state", safe_reason, usage_status="unknown", purpose=purpose)

    def _attempt(self, task_id, profile_id, request, *, work_bound, review_bound,
                 expected_in, expected_out, purpose, review_calls):
        if any(not isinstance(value, str) or not value.strip() for value in (task_id, profile_id)):
            return LedgerEntry(self.now_fn(), "<invalid>", None, "<invalid>", 0, 0, 0.0,
                               "blocked-gate4", "task and profile IDs must be nonempty strings")
        if not isinstance(purpose, str) or purpose not in ("work", "verification"):
            # An invalid enum cannot enter the durable journal as refusal metadata.
            return LedgerEntry(self.now_fn(), task_id, None, profile_id, 0, 0, 0.0,
                               "blocked-gate4", "dispatch purpose must be work or verification",
                               purpose="work")
        st = self._task(task_id)
        profile = deepcopy(self.prices["profiles"].get(profile_id))
        if profile is None:
            return self._reject(st, profile_id, "unknown-profile", "profile has no known price bound", purpose=purpose)
        if review_calls is None:
            review_calls = 1 if finite_nonnegative(review_bound) and review_bound > 0 and purpose == "work" else 0
        if (not finite_nonnegative(work_bound) or not finite_nonnegative(review_bound)
                or not finite_nonnegative(work_bound + review_bound) or not _priceable(profile)
                or any(type(t) is not int or t < 0 for t in (expected_in, expected_out))
                or type(review_calls) is not int or review_calls < 0
                or (purpose == "verification" and (review_bound != 0 or review_calls != 0))):
            return self._reject(st, profile_id, "blocked-gate4", "invalid bound, rate, token count or dispatch purpose", purpose=purpose)
        work, review = money(work_bound), money(review_bound)
        if purpose == "work" and work + review > money(self.caps.max_cost_per_task):
            return self._reject(st, profile_id, "blocked-gate4", "all-in bound exceeds task cap", purpose=purpose)
        ceiling, count_fn = expected_out, None
        if self.confirm_egress:
            if self.dispatch_fn is None:
                raise RuntimeError("confirm_egress set but no dispatch_fn wired; refusing egress")
            qualified_prices = getattr(self.dispatch_fn, "price_configuration", None)
            if qualified_prices is not None and self.prices != qualified_prices:
                return self._reject(st, profile_id, "blocked-gate4", "dispatcher prices differ from qualified adapter prices", purpose=purpose)
            ceiling = getattr(self.dispatch_fn, "max_tokens", None)
            count_fn = getattr(self.dispatch_fn, "count_tokens", None)
            if type(ceiling) is not int or ceiling <= 0 or not callable(count_fn):
                return self._reject(st, profile_id, "blocked-gate4", "egress requires max_tokens and count_tokens", purpose=purpose)
        with self.budget.transaction() as doc:
            blocked = self._check(doc, doc["tasks"][task_id], profile_id, work, review, purpose, review_calls)
            if blocked:
                return blocked
        reserve_in = expected_in
        if count_fn is not None:
            # No physical model send yet: a count error consumes no send slot.
            counted = count_fn(profile_id, request)
            if type(counted) is not int or counted < 0:
                raise ValueError("token count is not a non-negative integer")
            with localcontext() as arithmetic:
                arithmetic.prec = 1024
                margin = Decimal(counted) if callable(getattr(self.dispatch_fn, "input_token_ceiling", None)) else (
                    Decimal(counted) * (1 + Decimal(str(TOKEN_COUNT_MARGIN)))).to_integral_value(rounding=ROUND_CEILING)
            reserve_in = max(expected_in, int(margin))
        try:
            reserve = max(work, self._decimal_cost(profile, reserve_in, ceiling))
        except ArithmeticError:
            return self._reject(st, profile_id, "blocked-gate4", "unrepresentable price bound", purpose=purpose)
        if not finite_nonnegative(float(reserve)):
            return self._reject(st, profile_id, "blocked-gate4", "unrepresentable price bound", purpose=purpose)
        identifier = uuid.uuid4().hex
        with self.budget.lease(identifier) as release:
            return self._reserved_attempt(task_id, profile_id, profile, request, reserve, review,
                                          purpose, review_calls, identifier, expected_in, expected_out, release)

    def _reserved_attempt(self, task_id, profile_id, profile, request, reserve, review,
                          purpose, review_calls, identifier, expected_in, expected_out, release):
        with self.budget.transaction() as doc:
            task = doc["tasks"][task_id]
            blocked = self._check(doc, task, profile_id, reserve, review, purpose, review_calls)
            if blocked:
                return blocked
            previous = {name: task[name] for name in
                        ("last_profile", "repairs", "review_reserved", "review_calls_reserved")}
            if purpose == "work":
                task["review_reserved"] = str(max(money(task["review_reserved"]), review))
                task["review_calls_reserved"] = max(task["review_calls_reserved"], review_calls)
                if task["last_profile"] and task["last_profile"] == profile_id:
                    task["repairs"] += 1
                task["last_profile"] = profile_id
            else:
                task["review_calls_reserved"] -= 1
            task["attempts"] += 1
            task["pending"] = {"id": identifier, "reserved": str(reserve if purpose == "work" else 0),
                               "bound": str(reserve), "purpose": purpose, "status": "pending",
                               "profile_id": profile_id, "profile": {
                                   key: deepcopy(profile[key]) for key in
                                   ("input_rate_per_mtok", "output_rate_per_mtok", "long_context") if key in profile
                               }, "known_cost": "0",
                               "previous": previous}
            entry = self._record(doc, task, profile_id, "dispatch-reserved", "durable reservation before transport",
                                 reservation_id=identifier, reserved_cost_usd=float(reserve),
                                 review_reserved_usd=float(money(task["review_reserved"])), usage_status="unknown",
                                 purpose=purpose)
            record = doc["events"][-1]
            record.update(input_tokens=None, output_tokens=None, cost_usd=None)
        # Both the authority and mirror have committed. No transaction or lock is
        # held during transport. A crash now retains this attempt and reservation.
        send_now = self.now_fn()
        if (not finite_nonnegative(send_now) or send_now < task["last_observed"]
                or send_now - task["started"] >= self.caps.max_seconds_per_task):
            # Durable writes or lock waits may consume the last deadline margin.
            # This caller knows transport has not begun, so it can cancel only
            # its own reservation and restore counters, with an audit event.
            with self.budget.transaction() as doc:
                task = doc["tasks"][task_id]
                pending = task["pending"]
                if pending is None or pending["id"] != identifier:
                    raise BudgetStateError("unsent reservation identity lost")
                task.update(pending["previous"])
                task["attempts"] -= 1
                task["pending"] = None
                if not finite_nonnegative(send_now) or send_now < task["last_observed"]:
                    task["clock_stopped"] = True
                else:
                    task["last_observed"] = send_now
                result = LedgerEntry(self.now_fn(), task_id, task["attempts"], profile_id, 0, 0, 0.0,
                                     "blocked-deadline", "deadline stopped send after reservation; transport never began",
                                     identifier, 0.0, float(money(task["review_reserved"])), "not-dispatched", purpose,
                                     task["review_calls_reserved"])
                cancelled = asdict(result)
                cancelled["decision"] = "dispatch-cancelled"
                BudgetStore.event(doc, cancelled)
                self._remember(task)
            return result
        failure = False
        try:
            usage = self.dispatch_fn(profile_id, request) if self.confirm_egress else (expected_in, expected_out)
            in_toks, out_toks = usage
        except Exception as exc:
            failure = True
            in_toks = getattr(exc, "input_tokens", None)
            out_toks = getattr(exc, "output_tokens", None)
        finished_at = self.now_fn()
        receipt = {"schema_version": 1, "task_id": task_id, "reservation_id": identifier,
                   "input_tokens": in_toks if type(in_toks) is int and in_toks >= 0 else None,
                   "output_tokens": out_toks if type(out_toks) is int and out_toks >= 0 else None,
                   "transport_failed": failure, "ts": finished_at,
                   "transport_started_at": send_now if self.confirm_egress else None,
                   "transport_finished_at": finished_at if self.confirm_egress and finite_nonnegative(finished_at) and finished_at >= send_now else None}
        if not finite_nonnegative(receipt["ts"]):
            receipt["ts"] = task["last_observed"]
        # Construct the truthful physical outcome before any further authority IO.
        result = self._settle_receipt(deepcopy(doc), receipt)
        try:
            self.budget.write_receipt(receipt)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, BudgetStateError):
            pass  # Still try settlement; on failure the orphan reservation blocks sends.
        finally:
            release()  # The physical transport is finished; pending is no longer live-owned.
        try:
            with self.budget.transaction(settling=identifier) as settled:
                result = self._settle_receipt(settled, receipt)
            result.settlement_status = "committed"
            result.mirror_status = "pending" if self.budget.mirror_pending else "synchronized"
            try:
                self._remember(settled["tasks"][task_id])
            except (OSError, ValueError, CorruptState):
                result.mirror_status = "pending"
            return result
        except (BudgetStateError, CorruptState):
            result.decision = "dispatch-unsettled"
            result.reason = "transport finished; observed usage retained; authority settlement requires recovery"
            result.settlement_status = "unsettled"
            result.mirror_status = "pending"
            return result

    def _restore_verification_slot(self, task, pending):
        if (pending["purpose"] == "verification" and not pending.get("verification_slot_restored", False)
                and task["attempts"] + task["review_calls_reserved"] + 1 <= self.caps.max_attempts):
            task["review_calls_reserved"] += 1
            pending["verification_slot_restored"] = True

    def _settle_receipt(self, doc, receipt):
        """Pure, idempotent application of a safe observation under the authority lock."""
        if (receipt.get("schema_version") != 1 or type(receipt.get("transport_failed")) is not bool
                or not finite_nonnegative(receipt.get("ts"))):
            raise BudgetStateError("invalid observed send receipt; preserved")
        task_id, identifier = receipt["task_id"], receipt["reservation_id"]
        for event in reversed(doc["events"]):
            if event.get("reservation_id") == identifier and event.get("decision") in (
                    "dispatched", "dispatch-error", "dispatch-reconciled"):
                return LedgerEntry(**{key: value for key, value in event.items()
                                      if key in LedgerEntry.__dataclass_fields__})
        task = doc["tasks"][task_id]
        pending = task["pending"]
        if pending is None or pending["id"] != identifier:
            raise BudgetStateError("reservation identity lost; refusing settlement")
        profile = pending["profile"]
        purpose, reserve = pending["purpose"], money(pending["bound"])
        in_toks, out_toks = receipt["input_tokens"], receipt["output_tokens"]
        for value in (in_toks, out_toks):
            if value is not None and (type(value) is not int or value < 0):
                raise BudgetStateError("invalid observed token count; preserved")
        failure = receipt["transport_failed"]
        for key in ("transport_started_at", "transport_finished_at"):
            value = receipt.get(key)
            if value is not None and not finite_nonnegative(value):
                raise BudgetStateError("invalid transport timestamp; preserved")
            pending[key] = value
        if (pending.get("transport_finished_at") is not None and pending.get("transport_started_at") is not None
                and pending["transport_finished_at"] < pending["transport_started_at"]):
            raise BudgetStateError("transport timestamps are reversed; preserved")
        known = all(type(value) is int and value >= 0 for value in (in_toks, out_toks))
        try:
            cost = self._decimal_cost(profile, in_toks, out_toks) if known else None
        except ArithmeticError:
            known, cost = False, None
        if cost is not None and not finite_nonnegative(float(cost)):
            known, cost = False, None
        # Keep independently known partial usage. A partial cost is a lower
        # bound, never substituted for a complete bill or added twice later.
        partial_in = in_toks if type(in_toks) is int and in_toks >= 0 else None
        partial_out = out_toks if type(out_toks) is int and out_toks >= 0 else None
        known_floor = Decimal("0")
        if not known:
            try:
                if partial_in is not None:
                    known_floor = self._decimal_cost(profile, partial_in, partial_out or 0)
                elif partial_out is not None:
                    possible_rates = [profile["output_rate_per_mtok"]]
                    if profile.get("long_context"):
                        possible_rates.append(profile["long_context"]["output_rate_per_mtok"])
                    with localcontext() as arithmetic:
                        arithmetic.prec = 1024
                        known_floor = money(min(possible_rates)) * partial_out / Decimal("1000000")
                if not finite_nonnegative(float(known_floor)):
                    known_floor = Decimal("0")
            except ArithmeticError:
                known_floor = Decimal("0")
        if failure or not known:
            self._restore_verification_slot(task, pending)
        with localcontext() as arithmetic:
            arithmetic.prec = 1024
            if known:
                task["charged"] = str(money(task["charged"]) + cost)
                if purpose == "verification":
                    task["review_reserved"] = str(max(Decimal("0"), money(task["review_reserved"]) - cost))
                task["pending"] = None
                if cost > reserve:
                    doc["halted"] = True
                    doc["overrun"] = True
                reason = "failed send; known usage recorded" if failure else "actual usage settled"
                if cost > reserve:
                    reason += "; actual cost exceeded reservation; pilot stopped"
            else:
                task["pending"]["status"] = "uncertain"
                task["pending"]["known_cost"] = str(known_floor)
                task["charged"] = str(money(task["charged"]) + known_floor)
                if purpose == "work":
                    task["pending"]["reserved"] = str(max(Decimal("0"), reserve - known_floor))
                else:
                    task["review_reserved"] = str(max(Decimal("0"), money(task["review_reserved"]) - known_floor))
                if known_floor > reserve:
                    doc["overrun"] = True
                doc["halted"] = True
                reason = "send usage unknown; attempt and reservations retained; pilot stopped"
            doc["halted"] = bool(doc.get("overrun", False) or any(
                t["pending"] and t["pending"]["status"] == "uncertain" for t in doc["tasks"].values()))
            result = LedgerEntry(receipt["ts"], task_id, task["attempts"], pending["profile_id"],
                                 in_toks if known else partial_in, out_toks if known else partial_out,
                                 float(cost) if known else None,
                                 "dispatch-error" if failure or not known else "dispatched", reason,
                                 identifier, float(reserve), float(money(task["review_reserved"])),
                                 "observed" if known else "unknown", purpose, task["review_calls_reserved"],
                                 float(cost if known else known_floor))
            result.settlement_status = "committed"
            result.transport_started_at = pending.get("transport_started_at")
            result.transport_finished_at = pending.get("transport_finished_at")
            BudgetStore.event(doc, asdict(result))
        return result

    def reconcile_dispatch(self, task_id, reservation_id, *, input_tokens,
                           output_tokens, evidence_ref, transport_finished=False):
        """Host reconciles a retained reservation from a verified provider receipt.

        Requires complete usage, matching reservation ID and confirmation that
        the transport has stopped. Never infer unused cash from a timeout.
        """
        if (transport_finished is not True or not isinstance(evidence_ref, str)
                or not evidence_ref.strip() or any(type(t) is not int or t < 0
                                                 for t in (input_tokens, output_tokens))):
            raise ValueError("reconciliation requires complete usage and finished-transport evidence")
        self._task(task_id)
        with self.budget.transaction() as doc:
            task = doc["tasks"][task_id]
            pending = task["pending"]
            if pending is None or pending["id"] != reservation_id:
                raise BudgetStateError("no matching unsettled reservation")
            cost = self._decimal_cost(pending["profile"], input_tokens, output_tokens)
            if not finite_nonnegative(float(cost)):
                raise ValueError("unrepresentable actual usage cost")
            previously_known = money(pending["known_cost"])
            if cost < previously_known:
                raise BudgetStateError("receipt contradicts already known usage; preserve accounting")
            task["charged"] = str(money(task["charged"]) + cost - previously_known)
            if pending["purpose"] == "verification":
                task["review_reserved"] = str(max(Decimal("0"), money(task["review_reserved"]) - cost + previously_known))
                self._restore_verification_slot(task, pending)
            task["pending"] = None
            if cost > money(pending["bound"]):
                doc["overrun"] = True
            doc["halted"] = bool(doc.get("overrun", False) or any(
                t["pending"] and t["pending"]["status"] == "uncertain" for t in doc["tasks"].values()))
            entry = LedgerEntry(self.now_fn(), task_id, task["attempts"], pending["profile_id"],
                                input_tokens, output_tokens, float(cost), "dispatch-reconciled",
                                "host reconciled finished transport: " + evidence_ref,
                                reservation_id, float(money(pending["bound"])),
                                float(money(task["review_reserved"])), "observed", pending["purpose"],
                                task["review_calls_reserved"], float(cost))
            entry.transport_started_at = pending.get("transport_started_at")
            entry.transport_finished_at = pending.get("transport_finished_at")
            BudgetStore.event(doc, asdict(entry))
            self._remember(task)
            return entry

    def complete_verification(self, task_id, *, evidence_ref):
        """Host records passed acceptance checks; releases unused review cash.

        Call only after the host verifies the acceptance evidence. This terminal
        transition cannot be used to resume the task or reset any spent counters.
        """
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise ValueError("verification completion requires an evidence reference")
        self._task(task_id)
        with self.budget.transaction() as doc:
            task = doc["tasks"][task_id]
            if task["pending"] is not None:
                raise BudgetStateError("this task has an unsettled reservation")
            if not task["attempts"] or task["verified"] or task.get("abandoned", False):
                raise BudgetStateError("task has no unfinished dispatch to verify")
            task["review_reserved"] = "0"
            task["review_calls_reserved"] = 0
            task["verified"] = True
            return self._record(doc, task, task["last_profile"], "verification-complete",
                                "host accepted verification evidence: " + evidence_ref)

    def abandon_task(self, task_id, *, evidence_ref):
        """Close failed/expired work without claiming verification or erasing spend."""
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise ValueError("task abandonment requires an evidence reference")
        self._task(task_id)
        with self.budget.transaction() as doc:
            task = doc["tasks"][task_id]
            if task["pending"] is not None:
                raise BudgetStateError("unsettled task cannot release reservations")
            if task["verified"] or task.get("abandoned", False):
                raise BudgetStateError("task is already terminal")
            task["review_reserved"] = "0"
            task["review_calls_reserved"] = 0
            task["abandoned"] = True
            return self._record(doc, task, task["last_profile"] or "<not-dispatched>", "task-abandoned",
                                "host abandoned task: " + evidence_ref)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Live Phase 4 pilot dispatcher (fail-closed)")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--request", required=True)
    ap.add_argument("--work-bound", type=float, required=True,
                    help="work-call price bound (USD, all-in) used for the Gate-4 preflight")
    ap.add_argument("--review-bound", type=float, required=True,
                    help="required-check price bound (USD), retained until verification completes")
    ap.add_argument("--purpose", choices=("work", "verification"), default="work",
                    help="verification uses this task's existing review reservation; review-bound must be 0")
    ap.add_argument("--review-calls", type=int, default=None,
                    help="mandatory model verification slots; defaults to 1 for a positive review bound, otherwise 0")
    ap.add_argument("--expected-in-tokens", type=int, default=0,
                    help="dry-run mode: input tokens the dispatch would use; with"
                         " --confirm-egress, optional: the prompt is counted through the API"
                         " and the larger of the count (+5%%) and this estimate is reserved")
    ap.add_argument("--expected-out-tokens", type=int, default=0,
                    help="dry-run mode: output tokens the dispatch would use (a live send"
                         " reserves the adapter's max_tokens instead)")
    ap.add_argument("--confirm-egress", action="store_true",
                    help="permit a real network dispatch (Phase 4 owner authorization required)")
    ap.add_argument("--live", action="store_true",
                    help="wire the real Anthropic adapter as dispatch_fn (requires .env key and --confirm-egress)")
    ap.add_argument("--billing-qualification", default=None,
                    help="host qualification record for the approved modeled request billing scope")
    ap.add_argument("--ledger", default=str(LEDGER_DEFAULT))
    ap.add_argument("--task-store", default=None,
                    help="optional JSON state mirrors; authoritative counters always persist beside the ledger")
    args = ap.parse_args(argv)

    prices = load_prices(PRICES_PATH)

    dispatch_fn = None
    refused: tuple = ()
    if args.live:
        from dispatch_adapter import build_dispatch_fn, DispatchRefused
        refused = (DispatchRefused,)
        try:
            kwargs = {}
            if args.billing_qualification:
                qualification_path = Path(args.billing_qualification)
                kwargs["qualification_path"] = qualification_path if qualification_path.is_absolute() else REPO_ROOT / qualification_path
            dispatch_fn = build_dispatch_fn(**kwargs)  # refuses missing key or unqualified billing scope
        except DispatchRefused as e:
            print(json.dumps({"decision": "dispatch-refused", "reason": str(e)}), file=sys.stderr)
            return 2

    def repository_path(value):
        path = Path(value)
        return path if path.is_absolute() else REPO_ROOT / path
    task_store = repository_path(args.task_store) if args.task_store else None
    d = LiveDispatcher(prices, repository_path(args.ledger), confirm_egress=args.confirm_egress,
                       dispatch_fn=dispatch_fn, task_store=task_store)
    try:
        e = d.attempt(args.task_id, args.profile, args.request,
                      work_bound=args.work_bound, review_bound=args.review_bound,
                      expected_in=args.expected_in_tokens, expected_out=args.expected_out_tokens,
                      purpose=args.purpose, review_calls=args.review_calls)
    except refused as exc:  # e.g. no approved model mapping: refused before any request
        print(json.dumps({"decision": "dispatch-refused", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(asdict(e), sort_keys=True))
    return 0 if e.decision == "dispatched" else 1


if __name__ == "__main__":
    sys.exit(main())
