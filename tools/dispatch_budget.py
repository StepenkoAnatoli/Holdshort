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
import errno
import uuid

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
        if (type(task.get("abandoned", False)) is not bool
                or (task.get("abandoned", False) and task["verified"])):
            raise BudgetStateError("invalid terminal task flags")
        money(task["charged"])
        money(task["review_reserved"])
        pending = task.get("pending")
        if "pending" not in task:
            raise BudgetStateError("task has no reservation state")
        if pending is not None:
            if (not isinstance(pending, dict) or not isinstance(pending.get("id"), str)
                    or len(pending["id"]) != 32 or any(c not in "0123456789abcdef" for c in pending["id"])
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


def read_authority(ledger_path):
    """Read a consistent authority snapshot without creating, recovering or mirroring it."""
    import time
    ledger = Path(ledger_path).resolve()
    path = ledger.with_name(ledger.name + ".budget.sqlite3")
    last_exc = None
    for attempt in range(8):
        connection = None
        try:
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
            row = connection.execute("SELECT payload FROM authority WHERE id=1").fetchone()
            if row is None:
                raise BudgetStateError("budget authority has no committed snapshot")
            doc = decode(row[0])
            validate(doc)
            return doc
        except BudgetStateError:
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            last_exc = exc
            if attempt < 7:
                time.sleep(0.05 * (2 ** attempt))
            continue
        finally:
            if connection is not None:
                connection.close()
    raise BudgetStateError("budget snapshot unavailable or inconsistent; preserved") from last_exc


def _lock(handle):
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise
    return True


def _unlock(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class BudgetStore:
    def __init__(self, ledger_path, caps, task_store=None):
        self.ledger = Path(ledger_path).resolve()
        self.path = self.ledger.with_name(self.ledger.name + ".budget.sqlite3")
        self.task_store = Path(task_store).resolve() if task_store else None
        self.identity = {"caps": caps, "ledger": str(self.ledger),
                         "task_store": str(self.task_store) if self.task_store else None}
        self.recovery_dir = self.path.with_name(self.path.name + ".recovery")
        self.apply_receipt = None
        self.mirror_pending = False

    @contextmanager
    def lease(self, identifier):
        """A kernel-owned lifetime marker; process death releases it without a clock/PID guess."""
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        handle = (self.recovery_dir / (identifier + ".lock")).open("a+b")
        acquired = False
        def release():
            nonlocal acquired
            if acquired:
                try:
                    _unlock(handle)
                except OSError:
                    pass  # Closing the descriptor also releases its kernel lock.
                finally:
                    acquired = False
                    handle.close()
        try:
            if handle.seek(0, 2) == 0:
                handle.write(b"\0")
                handle.flush()
            acquired = _lock(handle)
            if not acquired:
                raise BudgetStateError("reservation already has a live owner")
            yield release
        finally:
            release()
            handle.close()

    def _owned(self, identifier):
        path = self.recovery_dir / (identifier + ".lock")
        try:
            handle = path.open("r+b")
        except FileNotFoundError:
            return False
        try:
            acquired = _lock(handle)
            if acquired:
                _unlock(handle)
            return not acquired
        finally:
            handle.close()

    def write_receipt(self, receipt):
        """Durably retain safe usage before attempting authority settlement."""
        identifier = receipt["reservation_id"]
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        target = self.recovery_dir / (identifier + ".json")
        if target.exists():
            if decode(target.read_text(encoding="utf-8")) != receipt:
                raise BudgetStateError("conflicting reservation receipt; preserved")
            return
        temporary = target.with_suffix(".tmp-" + uuid.uuid4().hex)
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(encode(receipt))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
        if os.name != "nt":
            fd = os.open(self.recovery_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _recover(self, doc, settling=None):
        changed = False
        consumed = []
        for path in sorted(self.recovery_dir.glob("*.json")):
            if path.stem == settling:
                continue  # The live owner applies its receipt in the yielded transaction.
            receipt = decode(path.read_text(encoding="utf-8"))
            identifier = receipt.get("reservation_id")
            if (not isinstance(identifier, str) or path.stem != identifier
                    or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier)
                    or self.apply_receipt is None):
                raise BudgetStateError("invalid or unsupported recovery receipt; preserved")
            before = len(doc["events"])
            self.apply_receipt(doc, receipt)
            changed |= len(doc["events"]) != before
            consumed.append(path)
        for task in doc["tasks"].values():
            pending = task["pending"]
            if pending and pending["status"] == "pending" and not self._owned(pending["id"]):
                pending["status"] = "uncertain"
                changed = True
        halted = bool(doc.get("overrun", False) or any(
            task["pending"] and task["pending"]["status"] == "uncertain" for task in doc["tasks"].values()))
        if doc.get("halted", False) != halted:
            doc["halted"] = halted
            changed = True
        return changed, consumed

    @staticmethod
    def _remove_receipts(paths):
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Replaying an already settled receipt is idempotent.

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
    def transaction(self, *, settling=None):
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
            if self.task_store is None and isinstance(doc.get("identity"), dict):
                # An optional JSON mirror is not part of whether a pilot exists.
                self.identity["task_store"] = doc["identity"].get("task_store")
            if doc.get("identity") != self.identity:
                raise BudgetStateError("pilot ledger path, explicit task-store binding or caps changed; refusing counter reset")
            self._bind_store()
            changed, consumed = self._recover(doc, settling)
            if changed:
                validate(doc)
                connection.execute("INSERT OR REPLACE INTO authority VALUES (1, ?)", (encode(doc),))
                connection.commit()
                self._remove_receipts(consumed)
                connection.execute("BEGIN IMMEDIATE")
                doc = decode(connection.execute("SELECT payload FROM authority WHERE id=1").fetchone()[0])
            else:
                self._remove_receipts(consumed)
            try:
                self._mirror(doc)
            except (OSError, ValueError, TypeError, KeyError, OverflowError, BudgetStateError):
                if settling is None:
                    raise
                # A derived mirror cannot prevent retaining an already observed send.
            # Preserve cents even beside the largest accepted finite float cap.
            # Prices and persisted balances must not lose small increments.
            with localcontext() as arithmetic:
                arithmetic.prec = 1024
                yield doc
            validate(doc)
            connection.execute("INSERT OR REPLACE INTO authority VALUES (1, ?)",
                               (encode(doc),))
            connection.commit()
            # Authority has committed. A later derived-mirror failure cannot
            # change a completed send into a refusal or erase its observed usage.
            self.mirror_pending = False
            try:
                connection.execute("BEGIN IMMEDIATE")
                latest = decode(connection.execute("SELECT payload FROM authority WHERE id=1").fetchone()[0])
                self._mirror(latest)
                connection.commit()
            except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, OverflowError, BudgetStateError):
                connection.rollback()
                self.mirror_pending = True
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
