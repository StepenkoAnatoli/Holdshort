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
`LiveDispatcher._task` through `read()` (PR #86). Step 3's fail-loud fix also
landed in #86 (`task_crosscheck` reports `invalid-task-mirror` instead of
swallowing corruption); delegating `task_crosscheck` to `reconcile()` was set
aside there (ADR-0001 Appendix B.2). Step 4 (PR #92) maps `pilot_report`'s
authority charges through `authority_view()`, not `reconcile()`. `read()` and
`authority_view()` are the production surface; `reconcile()`, `read_mirror()` and
`read_watchdog()` are the owner's supported library API, exercised by tests
(ADR-0002).

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

No writes, no cache, no new files: this module owns no state (ADR-0001). The
authority read is `dispatch_budget.read_authority()`, the side-effect-free
read-only snapshot the dispatcher's crosscheck already uses, so a read never
rewrites the authority row, replays a recovery receipt, or mirrors the ledger.
The authority's invariants (decode, validation) still hold on every read.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dispatch_budget import BudgetStore, BudgetStateError, money, read_authority
    from task_persistence import TaskStateStore
    from host_watchdog import load_state
except ImportError:  # direct import when repo root on path
    from tools.dispatch_budget import BudgetStore, BudgetStateError, money, read_authority
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


def authority_view(task: Dict) -> Dict:
    """The authority's record in the shared vocabulary: `charged` -> `spent`.

    This is the single mapping (ADR-0001). The owner's read() and the
    dispatcher's _remember() both call it, so the two can never drift. The
    deepcopy matches _remember's original semantics (the cached/persisted view
    shares no mutable structure with the authority document) and `spent` is
    byte-for-byte the float the mirror already persists.
    """
    view = deepcopy(task)
    view["spent"] = float(money(view["charged"]))
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

        The authority is read through the side-effect-free
        `dispatch_budget.read_authority()`, a read-only snapshot: unlike the
        dispatcher's write transactions it never rewrites the authority row,
        replays a recovery receipt, or mirrors the ledger, so a read observes
        no state a later reader could notice (ADR-0001).

        Raises CorruptState when a present mirror is unreadable or invalid
        (G5): a corrupt optional mirror still refuses the task even though the
        authority could answer — the file is preserved for forensics.
        Raises BudgetStateError when the authority itself is unavailable, or
        when a legacy ledger / bare task counters exist with no committed
        authority (the same rule the first transaction applies, #72).
        """
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task ID must be a nonempty string")
        if self.mirror is not None:
            self.mirror.load(task_id)  # validation only; raises CorruptState, never masked
        if not self.budget.path.exists():
            # No committed authority yet. Reuse the authority's own read-only
            # admissibility check (`_initial` only reads): a legacy ledger or
            # bare task counters must still refuse, otherwise the pilot is
            # simply new and the task is unknown. A read never creates it.
            self.budget._initial()
            return None
        try:
            doc = read_authority(self.budget.ledger)
        except BudgetStateError:
            # The authority exists but is not yet a readable committed snapshot
            # (e.g. a peer is creating it concurrently). Fall back to the
            # serialized/creation-path semantics: if a legacy ledger exists,
            # _initial() raises; otherwise treat as not yet committed and let
            # the caller materialise it in a serialized transaction.
            try:
                self.budget._initial()
            except BudgetStateError:
                raise
            return None
        task = doc["tasks"].get(task_id)
        # The single mapping lives in authority_view (shared with the
        # dispatcher's _remember, step 2).
        return None if task is None else authority_view(task)

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

        Finding shape and kind names come from `task_crosscheck`
        ({"task_id", "kind", "detail"}), so an authority<->mirror divergence is
        named once across both modules instead of in two vocabularies
        (ADR-0001 Appendix B.2). Kinds the crosscheck has no counterpart for
        (watchdog, mirror-without-authority) stay owner-local.

        A finding is a report, not a verdict: callers decide what to do with
        it. A corrupt mirror or an unreadable watchdog file raises instead of
        yielding findings — refusal is not a finding (G5).

        No production caller yet: `read()` and `authority_view()` are the
        owner's production surface; this is the owner's library API (ADR-0002).
        """
        authority = self.read(task_id)
        mirror = self.read_mirror(task_id)
        watchdog = self.read_watchdog(task_id)
        findings: List[Dict] = []
        if mirror is not None:
            if authority is None:
                if mirror["attempts"] or mirror["spent"]:
                    findings.append({
                        "task_id": task_id,
                        "kind": "mirror-without-authority",
                        "detail": "mirror carries counters for a task the authority "
                                  "does not know; the dispatcher refuses this case",
                    })
            elif (mirror["attempts"] != authority["attempts"]
                    or mirror["spent"] != authority["spent"]):
                # Same kind, condition and meaning as task_crosscheck's
                # authority-side finding (any difference — including a lagging
                # mirror, which the crosscheck also reports).
                findings.append({
                    "task_id": task_id,
                    "kind": "optional-mirror-stale",
                    "detail": (f"optional task mirror attempts/spent "
                               f"{mirror['attempts']}/{mirror['spent']} differ "
                               f"from the authority's {authority['attempts']}/"
                               f"{authority['spent']}"),
                })
        if watchdog is not None:
            if authority is None:
                findings.append({
                    "task_id": task_id,
                    "kind": "watchdog-without-authority",
                    "detail": "watchdog state exists for a task the authority "
                              "does not know",
                })
            else:
                for name in ("attempts", "repairs"):
                    if watchdog[name] > authority[name]:
                        findings.append({
                            "task_id": task_id,
                            "kind": f"watchdog-{name}-ahead",
                            "detail": (f"watchdog {name} {watchdog[name]} exceed "
                                       f"the authority's {authority[name]}; "
                                       "watchdog counts host launches, so this "
                                       "may be legitimate — investigate"),
                        })
        return {"task_id": task_id, "authority": authority, "mirror": mirror,
                "watchdog": watchdog, "findings": findings}
