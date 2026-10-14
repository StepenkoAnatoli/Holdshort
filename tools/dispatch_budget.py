"""Durable pilot authority and append-only JSONL mirror (stdlib SQLite).

BEGIN IMMEDIATE serializes reservations and settlements across processes. The
database commits before any send. Its event journal is authoritative; JSONL is
a replayable mirror. Missing suffixes are recovered, divergent/partial mirrors
are preserved and block execution. An existing legacy ledger is never treated
as a fresh pilot: it needs reconciliation before it can acquire an authority.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3

try:
    import redaction
except ImportError:
    from tools import redaction


class BudgetStateError(RuntimeError):
    """Authority unavailable, inconsistent or unreconciled; no send is allowed."""


def encode(doc):
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return json.dumps({"document": doc, "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}, allow_nan=False)


def decode(payload):
    envelope = json.loads(payload)
    doc = envelope["document"]
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not isinstance(envelope.get("sha256"), str) or not hmac.compare_digest(envelope["sha256"], expected):
        raise BudgetStateError("budget payload checksum mismatch; preserved")
    return doc


def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise BudgetStateError("invalid monetary counter") from exc
    if isinstance(value, bool) or not result.is_finite() or result < 0:
        raise BudgetStateError("invalid monetary counter")
    return result


def totals(doc):
    spent = reserved = Decimal("0")
    for task in doc["tasks"].values():
        spent += money(task["charged"])
        reserved += money(task["review_reserved"])
        if task["pending"]:
            reserved += money(task["pending"]["reserved"])
    return spent, reserved


def validate(doc):
    if (not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or doc.get("schema_version") != 1
            or not isinstance(doc.get("tasks"), dict) or not isinstance(doc.get("events"), list)):
        raise BudgetStateError("invalid budget schema")
    for identifier, task in doc["tasks"].items():
        if not isinstance(task, dict) or task.get("task_id") != identifier:
            raise BudgetStateError("invalid task identity")
        for name in ("attempts", "repairs", "review_calls_reserved"):
            if type(task.get(name)) is not int or task[name] < 0:
                raise BudgetStateError("invalid task counters")
        if task["repairs"] > task["attempts"] or not isinstance(task.get("last_profile"), str):
            raise BudgetStateError("invalid repair counters")
        for name in ("started", "last_observed"):
            value = task.get(name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise BudgetStateError("invalid task clock")
        if (task["last_observed"] < task["started"] or type(task.get("clock_stopped")) is not bool
                or type(task.get("verified")) is not bool):
            raise BudgetStateError("invalid task flags")
        money(task["charged"])
        money(task["review_reserved"])
        pending = task.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or not isinstance(pending.get("id"), str)
                    or pending.get("status") not in ("pending", "uncertain")):
                raise BudgetStateError("invalid reservation")
            money(pending["reserved"])
            money(pending["bound"])
            known_cost = money(pending["known_cost"])
            if pending.get("purpose") not in ("work", "verification") or not isinstance(pending.get("profile"), dict):
                raise BudgetStateError("invalid reserved dispatch profile")
            with localcontext() as arithmetic:
                arithmetic.prec = 1024
                expected = max(Decimal("0"), money(pending["bound"]) - known_cost) if pending["purpose"] == "work" else Decimal("0")
            if money(pending["reserved"]) != expected:
                raise BudgetStateError("reservation ownership mismatch")
    for name in ("halted", "overrun"):
        if name in doc and type(doc[name]) is not bool:
            raise BudgetStateError("invalid pilot stop flag")
    if not all(isinstance(event, dict) for event in doc["events"]):
        raise BudgetStateError("invalid event journal")


class BudgetStore:
    def __init__(self, ledger_path, caps, task_store=None):
        self.ledger = Path(ledger_path).resolve()
        self.path = self.ledger.with_name(self.ledger.name + ".budget.sqlite3")
        self.task_store = Path(task_store).resolve() if task_store else None
        self.identity = {"caps": caps, "ledger": str(self.ledger),
                         "task_store": str(self.task_store) if self.task_store else None}

    def _bind_store(self):
        if self.task_store is None:
            return
        self.task_store.mkdir(parents=True, exist_ok=True)
        binding = self.task_store / ".dispatch-budget-owner.json"
        expected = {"budget": str(self.path)}
        try:
            with binding.open("x", encoding="utf-8") as handle:
                json.dump(expected, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if json.loads(binding.read_text(encoding="utf-8")) != expected:
                raise BudgetStateError("task store belongs to another pilot authority")

    def _initial(self):
        if self.ledger.exists() and self.ledger.stat().st_size:
            raise BudgetStateError("legacy ledger has no budget authority; reconcile before dispatch")
        if self.task_store is not None:
            for path in self.task_store.glob("*.json"):
                state = json.loads(path.read_text(encoding="utf-8"))
                if (not isinstance(state, dict) or state.get("attempts", 0) != 0
                        or money(state.get("spent", 0)) != 0):
                    raise BudgetStateError("legacy task counters require reconciliation")
        return {"schema_version": 1, "identity": self.identity, "tasks": {}, "events": []}

    def _mirror(self, doc):
        # Compare parsed records so a line-ending change cannot reset accounting.
        # A partial final line is never silently truncated or rewritten.
        existing = []
        if self.ledger.exists():
            text = self.ledger.read_text(encoding="utf-8")
            if text and not text.endswith("\n"):
                raise BudgetStateError("partial ledger tail; preserved for reconciliation")
            existing = [json.loads(line) for line in text.splitlines()]
        if existing != doc["events"][:len(existing)] or len(existing) > len(doc["events"]):
            raise BudgetStateError("ledger diverges from budget journal; preserved")
        missing = doc["events"][len(existing):]
        if missing:
            with self.ledger.open("a", encoding="utf-8", newline="\n") as handle:
                for event in missing:
                    handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    @contextmanager
    def transaction(self):
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS authority (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            row = connection.execute("SELECT payload FROM authority WHERE id=1").fetchone()
            doc = decode(row[0]) if row else self._initial()
            validate(doc)
            if doc.get("identity") != self.identity:
                raise BudgetStateError("pilot identity or caps changed; refusing counter reset")
            self._bind_store()
            self._mirror(doc)
            # Preserve cents even beside the largest accepted finite float cap.
            # Prices and persisted balances must not lose small increments.
            with localcontext() as arithmetic:
                arithmetic.prec = 1024
                yield doc
            validate(doc)
            connection.execute("INSERT OR REPLACE INTO authority VALUES (1, ?)",
                               (encode(doc),))
            connection.commit()
            # A crash here leaves a durable journal suffix. The next transaction
            # replays it. No caller gets permission to send before this completes.
            connection.execute("BEGIN IMMEDIATE")
            latest = decode(connection.execute("SELECT payload FROM authority WHERE id=1").fetchone()[0])
            self._mirror(latest)
            connection.commit()
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            if connection is not None:
                connection.rollback()
            raise BudgetStateError("budget authority unavailable or inconsistent; preserved") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def event(doc, record):
        record, _ = redaction.redact_obj(record)
        record["reason"] = str(record["reason"])[:512]
        doc["events"].append(record)
