#!/usr/bin/env python3
"""Autonomous host supervisor with optional, explicitly requested HITL.

Default: run the command, allow one same-profile repair total (R01/R02/R03),
and stop with a redacted `blocked` package on timeouts, exhausted limits,
no progress, or safety violations. No approval question or human action menu
is emitted unless the host passes --human-requested from a user request.
A requested human gate does not waive permissions, budgets, or verification.

Exit codes: 0 command succeeded; 1 one repair granted; 2 terminal stop
(blocked by default, needs-human when requested); 3 invalid configuration.
The supervisor returns one attempt at a time; the host consumes the repair
grant, collects acceptance evidence, and supplies current cash/call totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from redact_text import redact
except ImportError:
    from tools.redact_text import redact

REPAIR_ALLOWANCE_DEFAULT = 1  # plan R01/R02/R03, tightened HITL §9.1: one total
ACTIONS = ["Approve", "Guide", "Take over", "Abort"]


def sanitize(value):
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        return {sanitize(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def safe_print(value, *, file=None):
    print(sanitize(str(value)), file=file)


# ---------------------------------------------------------------- pure policy

def timed_out(*, started: float, now: float, limit_s: float) -> bool:
    """True when the wall-clock budget is exhausted. Equality expires (strictly-before)."""
    return (now - started) >= limit_s


def repair_allowed(*, repairs_used: int, allowance: int = REPAIR_ALLOWANCE_DEFAULT) -> bool:
    return 0 <= repairs_used < min(allowance, REPAIR_ALLOWANCE_DEFAULT)


def no_progress_reason(prev: dict[str, Any] | None, curr: dict[str, Any]) -> str | None:
    """Why `curr` shows no progress over `prev`, or None when progress exists.

    Both records may carry: failing_tests (list), diff_hash (str, "" = no changes),
    error (str, normalized error message). Any single signal fires — a loop that
    repeats the same failure in any dimension is still a loop.
    """
    if prev is None:
        return None
    if prev.get("failing_tests") and prev.get("failing_tests") == curr.get("failing_tests"):
        return "same failing tests after repair attempt"
    pe, ce = (prev.get("error") or ""), (curr.get("error") or "")
    if pe and pe == ce:
        return "repeated identical error message"
    pd, cd = (prev.get("diff_hash") or ""), (curr.get("diff_hash") or "")
    if pd and pd == cd:
        return "no meaningful file changes between attempts"
    if not cd:
        return "no meaningful file changes between attempts"
    return None


def decide(*, repairs_used: int, allowance: int, prev: dict | None, curr: dict,
           calls_used: int, calls_limit: int | None, cash_spent: float,
           cash_cap: float | None, gate_raised: bool = False,
           nongoal_violation: str = "", high_risk: str = "",
           human_requested: bool = False) -> tuple[str, str]:
    """(verdict, reason): repair, blocked, or explicitly requested needs-human.

    Called when the latest attempt FAILED. Success is recorded by the runner, not
    here. Order matters: safety signals first, then ceilings, then progress, then
    the repair allowance — a high-risk signal escalates even when a repair is free.
    """
    stop = "needs-human" if human_requested else "blocked"
    if high_risk:
        return stop, f"high-risk signal: {high_risk}"
    if nongoal_violation:
        return stop, f"non-goal/forbidden-path violation: {nongoal_violation}"
    if gate_raised:
        return stop, "SmartRouter re-evaluation raised HumanGate"
    if calls_limit is not None and calls_used >= calls_limit:
        return stop, f"call limit exhausted: {calls_used}/{calls_limit}"
    if cash_cap is not None and cash_spent >= cash_cap:
        return stop, f"cash ceiling exhausted: {cash_spent} >= {cash_cap}"
    np_reason = no_progress_reason(prev, curr)
    if np_reason is not None:
        return stop, f"no progress: {np_reason}"
    if not repair_allowed(repairs_used=repairs_used, allowance=allowance):
        return stop, (
            f"repair allowance exhausted ({repairs_used}/{allowance} total per task; "
            "plan R01/R02/R03 — a further cycle needs a fresh authorized task)")
    return "repair", "one repair remains within the single-repair allowance"


# ---------------------------------------------------------------- state + package

def load_state(path: Path, task_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"task_id": task_id, "attempts": 0, "repairs_used": 0, "history": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"host_watchdog: FAIL-CLOSED — state file {path} unreadable ({e})")
    if not isinstance(doc, dict) or doc.get("task_id") not in (task_id, None):
        if isinstance(doc, dict) and doc.get("task_id") and doc["task_id"] != task_id:
            raise SystemExit(f"host_watchdog: FAIL-CLOSED — state file holds task "
                             f"{doc.get('task_id')!r}, not {task_id!r} (never reuse across tasks)")
        raise SystemExit(f"host_watchdog: FAIL-CLOSED — state file {path} malformed")
    doc.setdefault("attempts", 0)
    doc.setdefault("repairs_used", 0)
    doc.setdefault("history", [])
    return doc


def save_state(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(sanitize(doc), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def diff_hash_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_package(*, task_id: str, brief_path: str, decision_path: str, reason: str,
                  state: dict, diff_ref: str = "", pr_url: str = "",
                  log_tail: str = "", human_requested: bool = False) -> dict:
    """The HITL §6 escalation package (JSON-serializable). Values are operator-supplied;
    this function never reads secrets — it only assembles paths and history."""
    def _read_maybe(p: str):
        if not p:
            return None
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            return {"_unparsed_path": p}
    return sanitize({
        "status": "needs-human" if human_requested else "blocked",
        "human_requested": human_requested,
        "task_id": task_id,
        "reason": reason,
        "brief": _read_maybe(brief_path),
        "decision": _read_maybe(decision_path),
        "attempt_history": state.get("history", []),
        "diff_ref": diff_ref,
        "pr_url": pr_url,
        "log_tail": sanitize(log_tail)[-4000:],
        "actions": ACTIONS if human_requested else [],
    })


# ---------------------------------------------------------------- runner

def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="Enforce HITL timeouts, repair caps, and no-progress escalation for one agent attempt.")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--state", type=Path, required=True, help="restart-proof counters file (JSON)")
    ap.add_argument("--brief", default="", help="path to the Brief JSON (embedded into escalation package)")
    ap.add_argument("--decision", default="", help="path to the SmartRouter decision JSON")
    ap.add_argument("--timeout", type=float, required=True, help="wall-clock seconds for the command (equality expires)")
    ap.add_argument("--allowance", type=int, default=REPAIR_ALLOWANCE_DEFAULT, help="same-profile repairs allowed total (default 1)")
    ap.add_argument("--calls-used", type=int, default=0)
    ap.add_argument("--calls-limit", type=int, default=None)
    ap.add_argument("--cash-spent", type=float, default=0.0)
    ap.add_argument("--cash-cap", type=float, default=None)
    ap.add_argument("--failing-tests", default="", help="comma-separated failing test ids for no-progress check")
    ap.add_argument("--diff-hash", default="", help="hash of the working-tree diff after the attempt (\"\" = no changes)")
    ap.add_argument("--error", default="", help="normalized error message of this attempt")
    ap.add_argument("--diff-ref", default="", help="diff reference recorded into the escalation package")
    ap.add_argument("--pr-url", default="", help="PR URL recorded into the escalation package")
    ap.add_argument("--gate-raised", action="store_true")
    ap.add_argument("--human-requested", action="store_true",
                    help="enable HITL only when the user explicitly requested it")
    ap.add_argument("--nongoal-violation", default="")
    ap.add_argument("--high-risk", default="")
    ap.add_argument("--escalation-out", type=Path, default=None, help="where to write the terminal JSON package")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="command to run after -- (or without --)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cmd = [c for c in args.command if c != "--"]
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        safe_print("host_watchdog: FAIL-CLOSED — --timeout must be > 0", file=sys.stderr)
        return 3
    if args.allowance not in (0, REPAIR_ALLOWANCE_DEFAULT):
        safe_print("host_watchdog: FAIL-CLOSED — --allowance must be 0 or 1 (R01/R02/R03)", file=sys.stderr)
        return 3
    try:
        state = load_state(args.state, args.task_id)
    except SystemExit as e:
        safe_print(str(e), file=sys.stderr)
        return 3

    if state.get("terminal_reason"):
        return _escalate(args, state, state["terminal_reason"])

    # Pre-run ceilings escalate before spending another dispatch (HITL §9.2).
    if args.calls_limit is not None and args.calls_used >= args.calls_limit:
        reason = f"call limit exhausted: {args.calls_used}/{args.calls_limit}"
        return _escalate(args, state, reason)
    if args.cash_cap is not None and args.cash_spent >= args.cash_cap:
        reason = f"cash ceiling exhausted: {args.cash_spent} >= {args.cash_cap}"
        return _escalate(args, state, reason)
    if args.gate_raised:
        return _escalate(args, state, "SmartRouter re-evaluation raised HumanGate")
    if args.nongoal_violation:
        return _escalate(args, state, f"non-goal/forbidden-path violation: {args.nongoal_violation}")
    if args.high_risk:
        return _escalate(args, state, f"high-risk signal: {args.high_risk}")
    if not cmd:
        safe_print("host_watchdog: FAIL-CLOSED — no command to run", file=sys.stderr)
        return 3

    # A repair grant is consumed once. Repeated invocations after a terminal
    # failure cannot launch another command under the original allowance.
    if state.get("history") and state["history"][-1].get("outcome") == "failed":
        if state["repairs_used"] >= args.allowance and not state.get("repair_pending", False):
            return _escalate(args, state, "repair allowance exhausted (R01/R02/R03)")
    if state.get("repair_pending"):
        state["repair_pending"] = False
        save_state(args.state, state)

    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
        proc.stdout = sanitize(proc.stdout or "")
        proc.stderr = sanitize(proc.stderr or "")
        elapsed = time.monotonic() - started
        expired = elapsed >= args.timeout
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - started
        expired = True
        proc = None
        timeout_out = sanitize(e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
        timeout_err = sanitize(e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
    except FileNotFoundError as e:
        safe_print(f"host_watchdog: FAIL-CLOSED — command not found ({e})", file=sys.stderr)
        return 3

    if expired:
        tail = ""
        if proc is None:
            tail = ((timeout_out or "") + (timeout_err or ""))[-2000:]
        else:
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
        state["attempts"] += 1
        state["history"].append({"ts": time.time(), "outcome": "timeout",
                                 "elapsed_s": round(elapsed, 2), "log_tail": tail[-1000:]})
        save_state(args.state, state)
        return _escalate(args, state, f"wall-clock timeout: {elapsed:.1f}s >= {args.timeout:g}s — session killed",
                         log_tail=tail)

    assert proc is not None
    if proc.returncode == 0:
        state["attempts"] += 1
        state["history"].append({"ts": time.time(), "outcome": "success",
                                 "elapsed_s": round(elapsed, 2),
                                 "log_tail": ((proc.stdout or "")[-1000:])})
        save_state(args.state, state)
        safe_print(f"host_watchdog: task {args.task_id} completed in {elapsed:.1f}s "
              f"(attempt {state['attempts']})")
        return 0

    # Failed attempt: apply the post-failure policy (progress, then the one-repair cap).
    curr = {"failing_tests": [s for s in args.failing_tests.split(",") if s],
            "diff_hash": args.diff_hash, "error": args.error}
    prev = state["history"][-1] if state["history"] else None
    prev_sig = None
    if isinstance(prev, dict) and any(k in prev for k in ("failing_tests", "diff_hash", "error")):
        prev_sig = prev
    verdict, reason = decide(repairs_used=state["repairs_used"], allowance=args.allowance,
                             prev=prev_sig, curr=curr, calls_used=args.calls_used,
                             calls_limit=args.calls_limit, cash_spent=args.cash_spent,
                             cash_cap=args.cash_cap, human_requested=args.human_requested)
    state["attempts"] += 1
    state["history"].append({"ts": time.time(), "outcome": "failed",
                             "elapsed_s": round(elapsed, 2),
                             "failing_tests": curr["failing_tests"], "diff_hash": curr["diff_hash"],
                             "error": curr["error"],
                             "log_tail": ((proc.stdout or "") + (proc.stderr or ""))[-1000:]})
    if verdict in ("needs-human", "blocked"):
        save_state(args.state, state)
        return _escalate(args, state, reason,
                         log_tail=((proc.stdout or "") + (proc.stderr or ""))[-2000:])
    state["repairs_used"] += 1
    state["repair_pending"] = True
    save_state(args.state, state)
    safe_print(f"host_watchdog: attempt failed ({reason}); repair "
          f"{state['repairs_used']}/{args.allowance} consumed — caller may retry once",
          file=sys.stderr)
    return 1


def _escalate(args, state: dict, reason: str, log_tail: str = "") -> int:
    state["terminal_reason"] = reason
    state["repair_pending"] = False
    save_state(args.state, state)
    pkg = build_package(task_id=args.task_id, brief_path=args.brief,
                        decision_path=args.decision, reason=reason, state=state,
                        diff_ref=args.diff_ref, pr_url=args.pr_url, log_tail=log_tail,
                        human_requested=args.human_requested)
    out = args.escalation_out or args.state.with_name(f"{args.state.stem}.{pkg['status']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
    safe_print(f"host_watchdog: {pkg['status']} — {reason} (package: {out}; actions: {', '.join(pkg['actions']) or 'none'})",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
