#!/usr/bin/env python3
"""App-DB secrets watcher — scan the app's transcript stores on change, not on commit.

Why this exists: `tools/check_app_db_secrets.py` rides the pre-commit gate, so a token
that lands in a chat is only refused at the *next commit* — which can be hours later, and
never at all if the thread simply ends. This watcher runs the same scan when the store
changes (or on a heartbeat), so the leak is visible while it is still the only copy.

Design, in one place:

  * Cheap between scans, honestly stated. The loop only stats the store files — 0.63 ms for
    all four stores on this machine, measured — and a change is debounced before reading, so
    a run never reads a store mid-write. It scans once at startup to establish a view, then
    on change or on the heartbeat, so an idle watcher costs about a millisecond every five
    seconds. A scan itself is NOT cheap: this store is 23 MB and a pass costs ~2.3 s of CPU,
    which is the check's own cost and is paid only on change or heartbeat.
  * The scan reuses the check's audited pattern set by importing it, never by copying it,
    and adds a literal-prefix prefilter. Every pattern in that set begins with a literal, so
    a store whose bytes contain none of those literals cannot contain a hit: on a 16 MB
    corpus with no token-shaped literal a pass drops from 1.3 s to 0.15 s. That is a
    short-circuit, not a general speedup — this machine's store DOES contain token-shaped
    text (the baselined hits), so a real pass still pays the full regex cost. If any pattern
    ever loses its literal prefix, `prefilter_prefixes` returns None and the prefilter
    disables itself rather than under-scan — the tests pin exactly that.
  * Same reporting discipline as the check: class + byte offset + sha256 digest of the
    match. A value is never printed, logged, or stored, so triaging cannot re-leak.
  * Duplicate alerts are suppressed by digest through a state file that holds digests and
    timestamps only — but suppression never changes the verdict: a leak that is still
    there still exits 1.
  * A watcher must not die on a locked store. An unreadable store is a warning for the
    next cycle; an *unscannable* store (over the size cap) is reported and marks the pass
    incomplete, so "no new hits" is never read as "clean" — the check's fail-closed rule,
    kept here. Only a broken baseline or configuration is fatal (exit 2).

Usage:
    python tools/watch_app_db_secrets.py                     # watch until Ctrl-C
    python tools/watch_app_db_secrets.py --once              # one pass: cron / CI contract
    python tools/watch_app_db_secrets.py --max-scans 1       # one pass through the loop
    python tools/watch_app_db_secrets.py --on-new "notify.cmd"   # WATCH_DIGEST in its env

Exit status: `--once`, `--max-scans` and a Ctrl-C'd loop all report the verdict of the last pass,
mirroring the check: 0 clean, 1 untriaged hit still present, 2 fail-closed or a fatal
configuration error. A watcher you stop while a leak is outstanding therefore still exits 1.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parent
STATE_DEFAULT = REPO_ROOT / ".local" / "app_db_secrets_watch_state.json"
ZERO_WIDTH_ESCAPES = ("\\b", "\\B", "\\A", "\\Z", "^", "$")
LITERAL_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/")


def _load_check():
    """Import the check by path (the repo's fixture idiom), registered in sys.modules."""
    spec = importlib.util.spec_from_file_location("cads", TOOLS / "check_app_db_secrets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cads = _load_check()


# ---------------------------------------------------------------- scan (reuses the check)

def literal_prefix(pattern: str) -> str | None:
    """The literal every match of `pattern` must contain, or None if it cannot be derived.

    Conservative by construction: zero-width anchors and inline flags are stepped over, a
    case-insensitive flag disables the derivation (a case-sensitive substring test would be
    unsound), and the walk gives up at the first character that can consume anything other
    than itself — including escapes and alternation. None means "always scan this one".
    """
    i = 0
    while i < len(pattern):
        if pattern.startswith("(?", i):
            end = pattern.find(")", i)
            if end == -1:
                return None
            if "i" in pattern[i:end].lower():
                return None                     # (?i): a case-sensitive prefilter is unsound
            i = end + 1
            continue
        if pattern[i] == "\\":
            if pattern[i:i + 2] not in ZERO_WIDTH_ESCAPES:
                return None                     # an escape that consumed a class or a char
            i += 2
            continue
        if pattern[i] in LITERAL_CHARS:
            out = []
            while i < len(pattern) and pattern[i] in LITERAL_CHARS:
                out.append(pattern[i])
                i += 1
            return "".join(out)
        return None                             # a metacharacter before any literal
    return ""


def prefilter_prefixes(patterns) -> list[str] | None:
    """Literals that make a full regex pass unnecessary, or None to disable the prefilter."""
    out: list[str] = []
    for _name, pat in patterns:
        prefix = literal_prefix(pat.pattern)
        if not prefix:
            return None                         # unprovable set -> never risk under-scanning
        out.append(prefix)
    return out


def prefilter_hit(text: str, prefixes: list[str] | None) -> bool:
    """True when a full regex pass might match. False is a proof that nothing can match."""
    if prefixes is None:
        return True
    return any(p in text for p in prefixes)


def scan_text(text: str, prefixes: list[str] | None) -> list[tuple[str, int, str]]:
    """(class, offset, digest) hits in one store's text — identical to scan_store's result."""
    if not prefilter_hit(text, prefixes):
        return []
    hits: list[tuple[str, int, str]] = []
    for name, pat in cads.PATTERNS:
        for m in pat.finditer(text):
            hits.append((name, m.start(), hashlib.sha256(m.group(0).encode("latin-1")).hexdigest()))
    return hits


def scan_stores(stores: list[Path], max_bytes: int | None = None) \
        -> tuple[list[tuple[Path, str, int, str]], list[str], bool]:
    """(hits, warnings, incomplete).

    incomplete=True means a store that exists could not be scanned, so a pass with no hits
    must not be reported as clean — the same fail-closed rule the check applies at commit
    time. A store that merely vanished between the listing and the stat is a warning: the
    next cycle's listing will not contain it.
    """
    cap = cads.MAX_BYTES if max_bytes is None else max_bytes
    hits: list[tuple[Path, str, int, str]] = []
    warnings: list[str] = []
    incomplete = False
    prefixes = prefilter_prefixes(cads.PATTERNS)
    for store in stores:
        try:
            size = store.stat().st_size
        except OSError as e:
            warnings.append(f"{store}: cannot stat ({e}) — it may have been rotated away")
            continue
        if size > cap:
            warnings.append(f"{store}: {size} bytes exceeds the {cap}-byte scan cap — "
                            f"unscannable, treated as incomplete rather than clean")
            incomplete = True
            continue
        try:
            data = store.read_bytes()
        except OSError as e:
            warnings.append(f"{store}: unreadable ({e}) — retrying next cycle, but this pass "
                            f"is incomplete because the store could hold anything")
            incomplete = True
            continue
        for name, offset, digest in scan_text(data.decode("latin-1"), prefixes):
            hits.append((store, name, offset, digest))
    return hits, warnings, incomplete


# ---------------------------------------------------------------- loop policy (pure)

def store_signature(stores: list[Path]) -> dict[str, list[int]]:
    """(size, mtime_ns) per store; an unreadable store is a state (-1), not an exception."""
    sig: dict[str, list[int]] = {}
    for store in stores:
        try:
            st = store.stat()
            sig[str(store)] = [st.st_size, st.st_mtime_ns]
        except OSError:
            sig[str(store)] = [-1, -1]
    return sig


def due_reason(*, now: float, last_scan: float | None, changed: bool, quiet_for: float,
               debounce: float, heartbeat: float) -> str | None:
    """Why a scan is due ('startup' | 'changed' | 'heartbeat'), or None.

    Pure, so the whole policy is unit-testable without sleeping: a watcher establishes one
    view at startup (after the same debounce, so it does not read a store mid-write), then
    scans on change or on the heartbeat.
    """
    if last_scan is None:
        return "startup" if quiet_for >= debounce else None
    elapsed = now - last_scan
    if changed and quiet_for >= debounce:
        return "changed"
    if heartbeat and elapsed >= heartbeat:
        return "heartbeat"
    return None


# ---------------------------------------------------------------- state and reporting

def load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception as e:
        print(f"watch_app_db_secrets: state file {path} is unreadable ({e}) — starting fresh "
              f"(digests may repeat)", file=sys.stderr)
        return {}


def save_state(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)                        # atomic: a killed watcher leaves a valid file


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def alert_line(store: Path, name: str, offset: int, digest: str, ts: str) -> str:
    return (f"{ts} NEW {name} in {store} @0x{offset:x} sha256={digest[:16]}… "
            f"— rotate the value; the digest alone identifies it (never the value)")


def run_on_new(command: str, store: Path, name: str, digest: str) -> None:
    """Hand the digest (never the value) to the operator's own notifier."""
    env = dict(os.environ, WATCH_DIGEST=digest, WATCH_CLASS=name, WATCH_STORE=str(store))
    try:
        subprocess.run(command, shell=True, env=env, timeout=60)
    except Exception as e:  # a broken notifier must not stop the watch
        print(f"watch_app_db_secrets: --on-new command failed ({e})", file=sys.stderr)


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(
        description="Watch the Freebuff app stores and report credential-shaped strings as "
                    "they land (digest only, never the value).")
    ap.add_argument("--once", action="store_true", help="one pass, then exit (cron/CI contract)")
    ap.add_argument("--max-scans", type=int, default=0,
                    help="stop after N scans (0 = never); bounded runs report a verdict")
    ap.add_argument("--poll", type=float, default=5.0, help="seconds between stat-only polls")
    ap.add_argument("--debounce", type=float, default=3.0,
                    help="quiet seconds after a change before scanning (default 3)")
    ap.add_argument("--heartbeat", type=float, default=600.0,
                    help="scan anyway after this many seconds (0 = only on change)")
    ap.add_argument("--max-bytes", type=int, default=None,
                    help=f"per-store size cap (default: the check's {cads.MAX_BYTES})")
    ap.add_argument("--db-dir", type=Path, default=None,
                    help=f"app root to watch (sets {cads.APP_DIR_ENV})")
    ap.add_argument("--baseline", type=Path, default=cads.BASELINE_DEFAULT,
                    help=f"baseline allowlist (default: {cads.BASELINE_DEFAULT.name})")
    ap.add_argument("--state", type=Path, default=STATE_DEFAULT,
                    help=f"alert-suppression state, digests only (default: {STATE_DEFAULT})")
    ap.add_argument("--log", type=Path, default=None, help="also append reports to this file")
    ap.add_argument("--on-new", default=None,
                    help="command to run per new hit; WATCH_DIGEST/WATCH_CLASS/WATCH_STORE in env")
    ap.add_argument("--verbose", action="store_true", help="report every scan and its cost")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.db_dir is not None:
        os.environ[cads.APP_DIR_ENV] = str(args.db_dir)

    log = None
    if args.log is not None:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log = args.log.open("a", encoding="utf-8")

    def emit(line: str) -> None:
        print(line, flush=True)
        if log is not None:
            log.write(line + "\n")
            log.flush()

    try:
        cads.load_baseline(args.baseline)      # a malformed baseline is fatal, not "clean"
    except cads.FailClosed as e:
        print(f"watch_app_db_secrets: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2
    try:
        app_dir = cads.resolve_app_dir()
    except cads.FailClosed as e:
        print(f"watch_app_db_secrets: FAIL-CLOSED — {e}", file=sys.stderr)
        return 2
    if app_dir is None:
        emit(f"watch_app_db_secrets: nothing to watch — no Freebuff app dir on this machine "
             f"(expected on CI runners and fresh clones)")
        return 0

    state = load_state(args.state)
    alerted: dict[str, dict] = state.get("alerted", {})
    scans = int(state.get("scans", 0))
    alerts = int(state.get("alerts", 0))
    warned: set[str] = set()
    first_sig: dict[str, list[int]] | None = None
    last_scan: float | None = None
    quiet_since: float | None = None
    verdict = 0

    def one_pass(stores: list[Path], reason: str) -> tuple[int, bool]:
        """Scan, report what is new, record it. Returns (new_count, incomplete)."""
        nonlocal alerts, verdict
        started = time.perf_counter()
        hits, warnings, incomplete = scan_stores(stores, args.max_bytes)
        cost = time.perf_counter() - started
        for w in warnings:
            if w not in warned:
                warned.add(w)
                emit(f"{now_iso()} WARN {w}")
        try:
            baseline = cads.load_baseline(args.baseline)   # re-read: triage can change it
        except cads.FailClosed as e:
            emit(f"{now_iso()} FAIL-CLOSED {e}")
            verdict = 2
            return 0, True
        fresh = [(s, n, o, d) for (s, n, o, d) in hits if d not in baseline]
        new_alerts = [h for h in fresh if h[3] not in alerted]
        for store, name, offset, digest in sorted(new_alerts, key=lambda h: (str(h[0]), h[2])):
            ts = now_iso()
            emit(alert_line(store, name, offset, digest, ts))
            alerted[digest] = {"class": name, "store": str(store), "first_seen": ts}
            alerts += 1
            if args.on_new:
                run_on_new(args.on_new, store, name, digest)
        if args.verbose:
            emit(f"{now_iso()} scan ({reason}): {len(stores)} store(s), "
                 f"{len(hits)} hits, {len(fresh)} outside baseline, "
                 f"{len(new_alerts)} newly alerted, {cost:.2f}s")
        verdict = 1 if fresh else (2 if incomplete else 0)
        return len(fresh), incomplete

    if args.once:
        stores = cads.store_files(app_dir)
        if not stores:
            emit(f"watch_app_db_secrets: nothing to watch — {app_dir} has no "
                 f"{cads.STORE_GLOB} stores")
            return 0
        one_pass(stores, "once")
        state.update({"alerted": alerted, "scans": scans + 1, "alerts": alerts,
                      "last_scan": now_iso()})
        save_state(args.state, state)
        return verdict

    emit(f"{now_iso()} watching {app_dir} ({cads.STORE_GLOB}); poll {args.poll:g}s, "
         f"debounce {args.debounce:g}s, heartbeat {args.heartbeat:g}s; "
         f"state {args.state}")
    try:
        while True:
            stores = cads.store_files(app_dir)          # a new project dir appears at runtime
            now = time.monotonic()
            sig = store_signature(stores)
            if first_sig is None:
                first_sig = sig
                quiet_since = now
            changed = sig != first_sig
            if changed and quiet_since is None:
                quiet_since = now
            quiet_for = math.inf if quiet_since is None else now - quiet_since
            reason = due_reason(now=now, last_scan=last_scan, changed=changed,
                                quiet_for=quiet_for, debounce=args.debounce,
                                heartbeat=args.heartbeat)
            if reason is not None:
                one_pass(stores, reason)
                scans += 1
                last_scan = time.monotonic()
                first_sig = store_signature(cads.store_files(app_dir))
                quiet_since = None
                if args.max_scans and scans >= args.max_scans:
                    break
            time.sleep(max(args.poll, 0.01))
    except KeyboardInterrupt:
        emit(f"{now_iso()} stopped: {scans} scan(s), {alerts} alert(s)")
    finally:
        state.update({"alerted": alerted, "scans": scans, "alerts": alerts,
                      "last_scan": now_iso()})
        save_state(args.state, state)
        if log is not None:
            log.close()
    return verdict


if __name__ == "__main__":
    sys.exit(main())
