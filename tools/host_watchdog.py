#!/usr/bin/env python3
"""Host watchdog — wall-clock timeouts, no-progress detection, needs-human
escalations (host-hil-policy.md §6 and §9.1/§9.2/§9.3/§9.5).

The host-side supervisor for one task session. It reads a small session state
document (the same counters the plan says must survive restarts) and returns a
deterministic verdict before the host takes its next action:

  continue     the session may proceed (or has already succeeded)
  repair       ONE same-profile corrective dispatch is authorized (the single
               per-original-task allowance; implementation, CI and
               review-feedback corrections share it — plan R01/R02/R03)
  needs-human  the host must stop and escalate (§6)

Rules enforced, in order (fail-closed; a signal never downgrades):
  1. stop triggers / agent status (§6: non-goal violation, raised HumanGate,
     high-risk signal, crashed or unresponsive agent)
  2. wall-clock timeout (§9.5): `now - started` must be STRICTLY BEFORE the
     session limit; equality expires (plan §8 deadline semantics). `started`
     is the persisted anchor — a restart resumes it and never grants a fresh
     window (§9.1: counters are never reset).
  3. last attempt succeeded -> nothing to correct
  4. no-progress detection (§9.3): same failing checks, no meaningful file
     changes, or a repeated identical error between consecutive attempts is
     treated as failure and escalates instead of allowing another loop.
  5. budget caps (§9.2): exhausted call or cash ceilings block even when the
     repair allowance is free.
  6. repair allowance (§9.1): at most one same-profile corrective dispatch per
     original task in total; beyond it the task escalates.

Escalation packages follow §6 exactly and pass through the transcript
redaction layer (tools/redaction.py) before emission — the package is shown to
a human and rendered into transcripts, so no credential-shaped string may ride
along.

Session state document (JSON):
{
  "task_id": "T-007",
  "brief": { ... original Brief (spec-v2 §10.1-shaped or free text) ... },
  "decision": {"route": "delegate", "reasons": ["..."]},
  "session": {"started": 100.0, "wall_clock_limit": 300, "status": "running"},
  "attempts": [
    {"n": 1, "kind": "initial|repair|escalation", "phase": "implementation|ci|review",
     "started": 100.0, "ended": 150.0, "outcome": "failed|succeeded",
     "failing_checks": ["..."], "changed_files_digest": "sha1...",
     "error": "...", "log": "..."}
  ],
  "budget": {"call_limit": 4, "used_calls": 2, "cash_cap": 1.0, "spent": 0.04},
  "repair_allowance": 1,
  "diff_or_pr_url": "https://...",
  "stop_triggers": ["high-risk-signal: ..."],
  "now": 260.0
}

CLI:
    python tools/host_watchdog.py --state session.json [--now T] [--format json|markdown]

Exit codes:
    0  verdict is continue or repair
    1  verdict is needs-human (escalation emitted)
    2  state file missing/unreadable/malformed (fail-closed operational error:
       the watchdog cannot vouch for what it cannot read)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

try:
    import redaction
except ImportError:  # direct import when repo root on path
    from tools import redaction

ACTION_CONTINUE = "continue"
ACTION_REPAIR = "repair"
ACTION_NEEDS_HUMAN = "needs-human"

ACTION_OPTIONS = ["Approve", "Guide", "Take over", "Abort"]  # §6 package


class StateError(Exception):
    """The state document is missing or malformed — never guess from it."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise StateError(msg)


def load_state(path: Path) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise StateError(f"state file {path} is unreadable ({e})") from e
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise StateError(f"state file {path} is not valid JSON ({e})") from e
    _require(isinstance(doc, dict), "state document must be a JSON object")
    return doc


def _validate(state: dict) -> None:
    _require(isinstance(state.get("task_id"), str) and state["task_id"],
             "state.task_id must be a non-empty string")
    sess = state.get("session")
    _require(isinstance(sess, dict), "state.session must be an object")
    _require(isinstance(sess.get("started"), (int, float)),
             "state.session.started must be a number (the persisted anchor)")
    _require(isinstance(sess.get("wall_clock_limit"), (int, float))
             and sess["wall_clock_limit"] > 0,
             "state.session.wall_clock_limit must be a positive number")
    attempts = state.get("attempts", [])
    _require(isinstance(attempts, list) and all(isinstance(a, dict) for a in attempts),
             "state.attempts must be a list of attempt objects")
    budget = state.get("budget")
    if budget is not None:
        _require(isinstance(budget, dict), "state.budget must be an object")
    allowance = state.get("repair_allowance", 1)
    _require(isinstance(allowance, int) and allowance >= 0,
             "state.repair_allowance must be a non-negative integer")


def _verdict(action: str, reasons: List[str], state: dict,
             *, repairs_used: int, escalation: Optional[dict] = None) -> dict:
    return {
        "task_id": state.get("task_id"),
        "action": action,
        "reasons": reasons,
        "repairs_used": repairs_used,
        "repairs_allowed": state.get("repair_allowance", 1),
        "escalation": escalation,
    }


def escalation_package(state: dict, reasons: List[str]) -> dict:
    """The §6 package: everything the human needs, nothing credential-shaped.

    Emission always goes through the transcript redaction layer; callers must
    not re-render the raw state into a transcript by another path.
    """
    package = {
        "task_id": state.get("task_id"),
        "reasons": list(reasons),
        "original_brief": state.get("brief"),
        "smart_router_decision": state.get("decision"),
        "attempt_history": state.get("attempts", []),  # complete history + logs
        "diff_or_pr_url": state.get("diff_or_pr_url"),
        "action_options": list(ACTION_OPTIONS),
    }
    redacted, _findings = redaction.redact_obj(package)
    return redacted


def evaluate(state: dict, now: Optional[float] = None) -> dict:
    """Deterministic watchdog verdict for the session state (fail-closed)."""
    _validate(state)
    if now is None:
        now = state.get("now")
    _require(isinstance(now, (int, float)), "state.now (or --now) must be a number")

    sess = state["session"]
    attempts = state.get("attempts", [])
    repairs_used = sum(1 for a in attempts if a.get("kind") == "repair")
    reasons: List[str] = []

    def human(first_reason: str, extra: Optional[List[str]] = None) -> dict:
        all_reasons = [first_reason] + (extra or [])
        return _verdict(ACTION_NEEDS_HUMAN, all_reasons, state,
                        repairs_used=repairs_used,
                        escalation=escalation_package(state, all_reasons))

    # 1. §6 stop triggers and agent status
    triggers = state.get("stop_triggers") or []
    status = sess.get("status", "running")
    if triggers:
        return human("stop-trigger: " + "; ".join(str(t) for t in triggers))
    if status in ("unresponsive", "crashed"):
        return human(f"agent-{status}: session killed and escalated (§9.5/§6)")

    # 2. §9.5 wall-clock timeout — strictly before; equality expires
    elapsed = now - sess["started"]
    limit = sess["wall_clock_limit"]
    if elapsed >= limit:
        return human(f"wall-clock-timeout: elapsed {elapsed:g}s >= limit {limit:g}s "
                     f"(§9.5; equality expires, restart never grants a fresh window)")

    # 3. a succeeded session has nothing to correct
    if attempts and attempts[-1].get("outcome") == "succeeded":
        return _verdict(ACTION_CONTINUE, ["last attempt succeeded; nothing to correct"],
                        state, repairs_used=repairs_used)

    # 4. §9.3 no-progress detection between consecutive attempts. Each signal
    # must be OBSERVED (fields present), never inferred from missing evidence.
    if len(attempts) >= 2 and attempts[-1].get("outcome") == "failed":
        prev, latest = attempts[-2], attempts[-1]
        signals = []
        if prev.get("failing_checks") and \
                latest.get("failing_checks") == prev.get("failing_checks"):
            signals.append("same failing checks after a repair attempt")
        prev_digest, latest_digest = (prev.get("changed_files_digest"),
                                      latest.get("changed_files_digest"))
        if prev_digest is not None and latest_digest is not None \
                and prev_digest == latest_digest:
            signals.append("no meaningful file changes between attempts")
        if latest.get("error") and latest.get("error") == prev.get("error"):
            signals.append("repeated identical error message")
        if signals:
            return human("no-progress: " + "; ".join(signals) +
                         " — treated as failure and escalated (§9.3)")

    # 5. §9.2 budget caps
    budget = state.get("budget") or {}
    call_limit = budget.get("call_limit")
    used_calls = budget.get("used_calls")
    if call_limit is not None and used_calls is not None and used_calls >= call_limit:
        return human(f"call-limit-exhausted: used_calls {used_calls} >= "
                     f"call_limit {call_limit} (§9.2)")
    cash_cap = budget.get("cash_cap")
    spent = budget.get("spent")
    if cash_cap is not None and spent is not None and spent >= cash_cap:
        return human(f"budget-exhausted: spent ${spent:g} >= cash cap ${cash_cap:g} (§9.2)")

    # 6. §9.1 one same-profile repair per original task in total. A fresh
    # session (no attempts yet) proceeds with its INITIAL dispatch — that is
    # not a repair and consumes no repair allowance.
    if not attempts:
        return _verdict(ACTION_CONTINUE, ["no attempts recorded; proceed with the "
                                         "initial dispatch under the Brief"],
                        state, repairs_used=repairs_used)
    if attempts[-1].get("outcome") == "failed":
        allowance = state.get("repair_allowance", 1)
        if repairs_used >= allowance:
            return human(
                f"repair-allowance-exhausted: {repairs_used}/{allowance} used — one "
                "same-profile corrective dispatch per original task in total (§9.1); "
                "implementation, CI and review-feedback corrections share it")
        return _verdict(
            ACTION_REPAIR,
            [f"same-profile corrective dispatch #{repairs_used + 1} authorized "
             f"({repairs_used}/{allowance} used; shared across implementation/CI/"
             f"review phases; counters never reset by restart or rename)"],
            state, repairs_used=repairs_used)
    return _verdict(ACTION_CONTINUE, ["session in progress; no failure observed"],
                    state, repairs_used=repairs_used)


def render_markdown(verdict: dict) -> str:
    """Human-facing escalation rendering (already-redacted verdict input)."""
    lines = [f"# Host watchdog — {verdict.get('task_id', '?')}",
             "",
             f"**Verdict:** `{verdict['action']}`", ""]
    lines.append("**Reasons:**")
    lines.extend(f"- {r}" for r in verdict["reasons"])
    pkg = verdict.get("escalation")
    if pkg:
        lines += ["", "## Escalation package (§6)", "",
                  f"- **Task:** {pkg.get('task_id')}",
                  f"- **Diff / PR URL:** {pkg.get('diff_or_pr_url')}",
                  "", "### Original Brief", "",
                  "```json", json.dumps(pkg.get("original_brief"), indent=2,
                                        sort_keys=True, default=str), "```",
                  "", "### SmartRouter decision", "",
                  "```json", json.dumps(pkg.get("smart_router_decision"), indent=2,
                                        sort_keys=True, default=str), "```",
                  "", "### Attempt history + logs", "",
                  "```json", json.dumps(pkg.get("attempt_history"), indent=2,
                                        sort_keys=True, default=str), "```",
                  "", "### Action options",
                  ""]
        lines.extend(f"- **{opt}**" for opt in pkg.get("action_options", []))
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser(
        description="Host watchdog: wall-clock timeouts, no-progress repair "
                    "detection, needs-human escalations (HITL policy §6/§9).")
    ap.add_argument("--state", type=Path, required=True,
                    help="session state JSON (see module docstring)")
    ap.add_argument("--now", type=float, default=None,
                    help="override state.now (deterministic runs / tests)")
    ap.add_argument("--format", choices=("json", "markdown"), default="json")
    return ap.parse_args(argv)


def run(args) -> int:
    try:
        state = load_state(args.state)
        verdict = evaluate(state, now=args.now)
    except StateError as e:
        print(f"host_watchdog: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2
    # Redact the whole verdict before it can render into a transcript.
    verdict, _findings = redaction.redact_obj(verdict)
    if args.format == "markdown":
        out = render_markdown(verdict)
    else:
        out = json.dumps(verdict, indent=2, sort_keys=True, default=str)
    # UTF-8 regardless of the console codepage: this output is transcript-bound
    sys.stdout.buffer.write(out.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()
    return 1 if verdict["action"] == ACTION_NEEDS_HUMAN else 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
