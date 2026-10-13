#!/usr/bin/env python3
"""Schema-version guard: every repo-owned `messages` table must carry the redaction triggers.

Fails the gate (exit 1) when a `messages` table exists WITHOUT both triggers
(e.g. the table was recreated bare) or with a wrong schema version. A missing
store file is clean (exit 0): there is nothing unprotected. Trigger stubs are
not enough — each trigger's SQL must contain RAISE plus one shape marker per
audited class, so a neutered trigger still fails.

Scope: repo-owned stores only (default `.local/messages.db`, plus `--store`
repeats). Never points at the Freebuff app store.

Run as part of the regression gate (folded into tools/run_regression.py).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import message_store as ms

DEFAULT_STORE = REPO / ".local" / "messages.db"

# One SQL marker per audited class; each trigger body must contain all of them.
MARKERS = ("github_pat_", "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
           "sk-ant-", "sk-proj-", "sk-")


def check_store(path: Path) -> list[str]:
    findings: list[str] = []
    if not path.exists():
        return findings
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return [f"{path}: unreadable ({e})"]
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "messages" not in tables:
            return findings
        row = None
        if "schema_version" in tables:
            row = conn.execute(
                "SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None or row[0] != ms.SCHEMA_VERSION:
            findings.append(
                f"{path}: messages table without schema_version={ms.SCHEMA_VERSION}")
        trigs = {r[0]: (r[1] or "") for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger'")}
        for want in (ms.TRIGGER_BI, ms.TRIGGER_BU):
            sql = trigs.get(want)
            if sql is None:
                findings.append(f"{path}: messages table missing trigger {want}")
            elif "RAISE" not in sql or any(m not in sql for m in MARKERS):
                findings.append(
                    f"{path}: trigger {want} neutered (RAISE/shape markers incomplete)")
    except sqlite3.Error as e:
        findings.append(f"{path}: inspection failed ({e})")
    finally:
        conn.close()
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guard repo-owned messages tables.")
    ap.add_argument("--store", type=Path, action="append", default=[],
                    help="repo-owned store to guard (repeatable)")
    args = ap.parse_args(argv)
    stores = args.store or [DEFAULT_STORE]
    findings = [f for s in stores for f in check_store(s)]
    if findings:
        print("message_schema: FAIL")
        for f in findings:
            print(f"  - {f}")
        print("Recreate the store through tools/message_store.open_store(), never bare DDL.")
        return 1
    print("message_schema: OK "
          f"({len(stores)} store(s) checked, "
          f"{sum(1 for s in stores if s.exists())} present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
