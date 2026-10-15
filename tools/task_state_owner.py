#!/usr/bin/env python3
"""Sole read path for the three task-state stores (ADR-0001, migration step 1).

Task state lives in three places today:

  * the shared SQLite budget authority (`dispatch_budget.BudgetStore`) — the
    record; its task dicts carry `charged` as a Decimal string;
  * the optional JSON mirror (`task_persistence.TaskStateStore`) — `spent`,
    `repairs`, validated fail-closed under rule G5;
  * the host watchdog's per-run JSON (`host_watchdog.load_state`) — the same
    repair counter under the name `repairs_used`, plus `history`,
    `repair_pending` and `terminal_reason`.

This module reads all three through one fail-closed interface and compares
them. The vocabulary mapping lives here, once; no on-disk name changes (agent
hosts read and write these files by the runbook prose — formats are a
published contract, ADR-0001). Step 1 ships imported by nothing but its
tests: the dispatcher keeps its behavior while the owner soaks. Step 2 routes
`LiveDispatcher._task` through `read()`; step 3 retires `task_crosscheck`'s
raw reader in favor of `reconcile()`.

Contract:
  read()          the authority's record wins; a valid stale mirror never
                  lowers it; a CORRUPT mirror still refuses the task (G5,
                  preserved exactly as task_persistence documents it).
  read_mirror()   the validated mirror, or None when absent.
  read_watchdog() watchdog state with `repairs_used` mapped to `repairs`.
  reconcile()     all three, side by side, with findings. Mere disagreement
                  between stores is a finding, never an error: the watchdog
                  counts host launches while the authority counts dispatches,
                  so the two can legitimately differ.

No writes, no cache, no new files: this module owns no state (ADR-0001).
Reads reuse `BudgetStore.transaction()`, the same sanctioned read path the
dispatcher itself uses, so the authority's invariants (validation, journal
replay) hold on every read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

try:
    from dispatch_budget import BudgetStore, money
    from task_persistence import TaskStateStore
    from host_watchdog import load_state
except ImportError:  # direct import when repo root on path
    from tools.dispatch_budget import BudgetStore, money
    from tools.task_persistence import TaskStateStore
    from tools.host_watchdog import load_state


class WatchdogStateUnreadable(RuntimeError):
    """The watchdog state file exists but cannot be read; fail closed.

    host_watchdog.load_state reports corruption by raising SystemExit (it is a
    CLI contract). The owner renames that failure without swallowing it, so a
    library caller gets an ordinary exception carrying the same message.
    """


def from_watchdog(doc: Dict) -> Dict:
    """One vocabulary: the watchdog's `repairs_used` is the shared `repairs`."""
    view = dict(doc)
    view["repairs"] = view.pop("repairs_used")
    return view


class TaskStateOwner:
    """Read-only view over authority + mirror + watchdog state (ADR-0001).

    Constructed with explicit store objects and paths — no globals, no
    location guessing: a pilot's identity is its resolved ledger path (#82),
    so the owner never invents one.
    """

    def __init__(self, budget: BudgetStore, *,
                 mirror: Optional[TaskStateStore] = None,
                 watchdog_state_path: Optional[Path] = None) -> None:
        self.budget = budget
        self.mirror = mirror
        self.watchdog_state_path = (Path(watchdog_state_path)
                                    if watchdog_state_path is not None else None)

    def read(self, task_id: str) -> Optional[Dict]:
        """The authority's record for task_id, normalized, or None if unknown.

        Raises CorruptState when a present mirror is unreadable or invalid
        (G5): a corrupt optional mirror still refuses the task even though the
        authority could answer — the file is preserved for forensics.
        Raises BudgetStateError when the authority itself is unavailable.
        """
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task ID must be a nonempty string")
        if self.mirror is not None:
            self.mirror.load(task_id)  # validation only; raises CorruptState, never masked
        with self.budget.transaction() as doc:
            task = doc["tasks"].get(task_id)
            if task is None:
                return None
            view = dict(task)
            # Vocabulary mapping, stated once: the authority's Decimal-string
            # `charged` is the shared float `spent` — the same conversion the
            # dispatcher's _remember persists into the mirror.
            view["spent"] = float(money(view["charged"]))
            return view

    def read_mirror(self, task_id: str) -> Optional[Dict]:
        """The validated mirror record, or None when no mirror is configured
        or the task has no mirror file."""
        if self.mirror is None:
            return None
        return self.mirror.load(task_id)

    def read_watchdog(self, task_id: str) -> Optional[Dict]:
        """Watchdog state with repairs_used mapped to repairs, or None when
        no watchdog state path is configured."""
        if self.watchdog_state_path is None:
            return None
        try:
            doc = load_state(self.watchdog_state_path, task_id)
        except SystemExit as exc:
            raise WatchdogStateUnreadable(
                f"watchdog state unreadable; original preserved: {exc}") from exc
        return from_watchdog(doc)

    def reconcile(self, task_id: str) -> Dict:
        """All three stores side by side, with findings (authority wins).

        A finding is a report, not a verdict: callers decide what to do with
        it. A corrupt mirror or an unreadable watchdog file raises instead of
        yielding findings — refusal is not a finding (G5).
        """
        authority = self.read(task_id)
        mirror = self.read_mirror(task_id)
        watchdog = self.read_watchdog(task_id)
        findings: List[Dict] = []
        if mirror is not None and (mirror["attempts"] or mirror["spent"]):
            if authority is None:
                findings.append({
                    "kind": "mirror-without-authority",
                    "detail": "mirror carries counters for a task the authority "
                              "does not know; the dispatcher refuses this case",
                })
            elif (mirror["attempts"] > authority["attempts"]
                    or mirror["spent"] > authority["spent"]):
                findings.append({
                    "kind": "mirror-ahead-of-authority",
                    "detail": (f"mirror attempts/spent {mirror['attempts']}/"
                               f"{mirror['spent']} exceed the authority's "
                               f"{authority['attempts']}/{authority['spent']}"),
                })
        if watchdog is not None:
            if authority is None:
                findings.append({
                    "kind": "watchdog-without-authority",
                    "detail": "watchdog state exists for a task the authority "
                              "does not know",
                })
            else:
                for name in ("attempts", "repairs"):
                    if watchdog[name] > authority[name]:
                        findings.append({
                            "kind": f"watchdog-{name}-ahead",
                            "detail": (f"watchdog {name} {watchdog[name]} exceed "
                                       f"the authority's {authority[name]}; "
                                       "watchdog counts host launches, so this "
                                       "may be legitimate — investigate"),
                        })
        return {"task_id": task_id, "authority": authority, "mirror": mirror,
                "watchdog": watchdog, "findings": findings}
