#!/usr/bin/env python3
"""Per-task state persistence — counters survive dispatcher process restarts.

Stores one JSON file per task (or one consolidated store keyed by task_id —
per-task file by default to keep concurrent-task work safe). All writes are
atomic (tmp + rename), all fields carry the §5 counters the dispatcher must
never lose:

  attempts, spent, started (wall-clock anchor), repairs, last_profile

Strictly-before deadline rule carries over: `started` is the wall-clock
anchor persisted at first dispatch; a restarted process resumes against the
same anchor, so the 300 s cap applies across the whole task lifetime, not
per process. Timestamps use time.time() unless a now_fn override is given
(dry-run/harness use).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    import redaction
except ImportError:  # direct import when repo root on path
    from tools import redaction

STATE_FIELDS = ("task_id", "attempts", "spent", "started", "repairs", "last_profile")
DEFAULT_DIR = Path(__file__).resolve().parent / "task_state"


def _sanitize(task_id: str) -> str:
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in task_id)
    while ".." in s:  # path-traversal sequences can never survive sanitization
        s = s.replace("..", "_")
    return s


def _atomic_write(path: Path, doc: dict) -> None:
    # Pre-write redaction (tools/redaction.py): persisted task state can end
    # up quoted into a transcript; strip credential-shaped strings before
    # the write rather than at the scanners after the fact.
    doc, _findings = redaction.redact_obj(doc)
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
        self.now_fn = now_fn

    def path_for(self, task_id: str) -> Path:
        return self.state_dir / f"{_sanitize(task_id)}.json"

    def load(self, task_id: str) -> Optional[dict]:
        p = self.path_for(task_id)
        if not p.is_file():
            return None
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None  # corrupt state treated as absent — callers re-derive caps from ledger
        if not isinstance(doc, dict) or not all(k in doc for k in STATE_FIELDS):
            return None
        return {k: doc[k] for k in STATE_FIELDS}

    def save(self, st: dict) -> None:
        doc = {k: st[k] for k in STATE_FIELDS}
        doc["updated_at"] = self.now_fn()
        _atomic_write(self.path_for(st["task_id"]), doc)


class ResumableTasks:
    """Mixin-style helper wiring the store into LiveDispatcher._task lookup.

    Semantics: a persisted task is resumed EXACTLY as its counters say —
    nothing is reset (the plan's restart/rename-never-resets rule). The store
    is written after every mutation the dispatcher makes (dispatch or reset of
    last_profile), with the tmp+rename atomicity above.
    """

    def __init__(self, store: TaskStateStore) -> None:
        self.store = store

    def load_or_init(self, task_id: str, init_factory: Callable[[], dict]) -> dict:
        loaded = self.store.load(task_id)
        if loaded is None:
            st = init_factory()
            self.store.save(st)
            return st
        return loaded

    def persist(self, st: dict) -> None:
        self.store.save(st)
