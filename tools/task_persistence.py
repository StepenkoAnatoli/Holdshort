#!/usr/bin/env python3
"""Per-task state persistence — counters survive dispatcher process restarts.

Stores one JSON file per task (or one consolidated store keyed by task_id —
per-task file by default to keep concurrent-task work safe). All writes are
atomic (tmp + rename), all fields carry the §5 counters the dispatcher must
never lose:

  attempts, spent, started (interval-clock anchor), repairs, last_profile

Strictly-before deadline rule carries over: `started` is the interval-clock
anchor persisted at first dispatch; a restarted process resumes against the
same anchor, so the 300 s cap applies across the whole task lifetime, not
per process. The dispatcher also keeps authoritative counters and reservations
in the shared database beside its ledger; these JSON files are optional mirrors.
The current dispatcher uses a wall-clock anchor. Monotonic-clock
state is refused until the dispatcher supports its clock domain; persisting a
clock label alone does not make deadline calculations monotonic.

Fail-closed corruption rule (G5, matching tools/spawn_worker.py S7): a
present-but-unreadable state file raises CorruptState and is preserved for
forensics. It is NEVER auto-reinitialized to zeros — callers must refuse the
task (`blocked:state-corrupt`) and require explicit operator recovery.
Only a missing file means "new task".
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    import redaction
except ImportError:
    from tools import redaction

STATE_FIELDS = ("task_id", "attempts", "spent", "started", "repairs", "last_profile")
# Optional extras persisted when present (clock versioning, wall stamp).
EXTRA_FIELDS = ("clock", "started_wall", "last_observed", "clock_stopped")
DEFAULT_DIR = Path(__file__).resolve().parent / "task_state"

CLOCK_MONOTONIC = "monotonic"
CLOCK_WALL_LEGACY = "wall"


class CorruptState(RuntimeError):
    """A task state file exists but is unreadable/invalid — fail closed.

    The file is preserved on disk for forensics. Callers must NOT treat this
    as a new task (that would reset attempts/spend/deadline counters against
    plan §7). Refuse the dispatch and require explicit operator recovery.
    """


def _sanitize(task_id: str) -> str:
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in task_id)
    while ".." in s:  # path-traversal sequences can never survive sanitization
        s = s.replace("..", "_")
    return s


def _atomic_write(path: Path, doc: dict) -> None:
    doc, _ = redaction.redact_obj(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class TaskStateStore:
    """Load/save per-task dicts from a JSON state directory."""

    def __init__(self, state_dir: Path, *, now_fn: Callable[[], float] = time.time) -> None:
        self.state_dir = Path(state_dir)
        self.now_fn = now_fn  # wall clock for `updated_at` stamps only

    def path_for(self, task_id: str) -> Path:
        return self.state_dir / f"{_sanitize(task_id)}.json"

    def load(self, task_id: str) -> Optional[dict]:
        p = self.path_for(task_id)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError, OSError) as e:
            raise CorruptState("task state unreadable; original state preserved") from e
        if not isinstance(doc, dict) or not all(k in doc for k in STATE_FIELDS):
            raise CorruptState("task state missing required fields; original state preserved")
        counters_ok = all(type(doc[k]) is int and doc[k] >= 0
                          for k in ("attempts", "repairs"))
        try:
            numbers_ok = all(type(doc[k]) in (int, float) and math.isfinite(doc[k])
                             and doc[k] >= 0 for k in ("spent", "started"))
            if "last_observed" in doc:
                value = doc["last_observed"]
                numbers_ok = (numbers_ok and type(value) in (int, float)
                              and math.isfinite(value) and value >= doc["started"])
        except (OverflowError, TypeError):
            numbers_ok = False
        if (not counters_ok or not numbers_ok or doc["task_id"] != task_id
                or not isinstance(doc["last_profile"], str)
                or doc["repairs"] > doc["attempts"]
                or ("clock_stopped" in doc and type(doc["clock_stopped"]) is not bool)
                or doc.get("clock", CLOCK_WALL_LEGACY) != CLOCK_WALL_LEGACY):
            raise CorruptState("task state invalid or unsupported clock; original state preserved")
        st = {k: doc[k] for k in STATE_FIELDS}
        for k in EXTRA_FIELDS:
            if k in doc:
                st[k] = doc[k]
        return st

    def save(self, st: dict) -> None:
        doc = {k: st[k] for k in STATE_FIELDS}
        for k in EXTRA_FIELDS:
            if k in st:
                doc[k] = st[k]
        doc["updated_at"] = self.now_fn()
        _atomic_write(self.path_for(st["task_id"]), doc)


class ResumableTasks:
    """Mixin-style helper wiring the store into LiveDispatcher._task lookup.

    Semantics: a persisted task is resumed EXACTLY as its counters say —
    nothing is reset (the plan's restart/rename-never-resets rule). The store
    is written after every mutation the dispatcher makes (dispatch or reset of
    last_profile), with the tmp+rename atomicity above.

    Corruption propagates as CorruptState — load_or_init NEVER auto-creates
    zeros over a corrupt file (G5). The dispatcher catches it and refuses the
    task as `blocked:state-corrupt`.
    """

    def __init__(self, store: TaskStateStore) -> None:
        self.store = store

    def load_or_init(self, task_id: str, init_factory: Callable[[], dict]) -> dict:
        loaded = self.store.load(task_id)  # raises CorruptState; never masked
        if loaded is None:
            st = init_factory()
            self.store.save(st)
            return st
        return loaded

    def persist(self, st: dict) -> None:
        self.store.save(st)
