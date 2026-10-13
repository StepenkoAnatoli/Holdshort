#!/usr/bin/env python3
"""Repo-owned message store with a versioned schema and redaction triggers.

Why this exists: the pre-write filter (`tools/redact_text.py`) sanitizes text
the operator routes through it, but nothing stops a raw `INSERT` from writing
a credential-shaped string into a store the repo owns. This module is that
second layer for repo-owned SQLite stores: every `messages` table it creates
carries `BEFORE INSERT` / `BEFORE UPDATE` triggers that ABORT the write when
`NEW.body` is credential-shaped.

Honest scope:
  * The triggers approximate the nine audited regex classes with `GLOB`
    repetitions (`?` per required character). GLOB cannot restrict character
    classes, so a trigger may refuse a non-secret that happens to share the
    shape (over-approximation). That is acceptable for a refuse-backstop and
    is why the precise Python filter stays the primary path: writers call
    `add_message()`, which redacts first and inserts clean text.
  * This store is repo-owned (default `.local/messages.db`, gitignored). It is
    NOT the Freebuff app store (`desktop-v2.db*`): the app owns that database
    and it must never be edited in place (see docs/CREDENTIAL_ROTATION_RUNBOOK.md §4).
  * `tools/check_message_schema.py` is the guard that fails the gate when a
    `messages` table exists without these triggers (e.g. recreated bare).
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 1

# (class, GLOB fragment with one `?` per required body character)
SHAPE_GLOBS: tuple[tuple[str, str], ...] = (
    ("github-pat-fine-grained", "*github_pat_" + "?" * 20 + "*"),
    ("github-pat-classic", "*ghp_" + "?" * 36 + "*"),
    ("github-oauth", "*gho_" + "?" * 36 + "*"),
    ("github-user-to-server", "*ghu_" + "?" * 36 + "*"),
    ("github-server-to-server", "*ghs_" + "?" * 36 + "*"),
    ("github-refresh", "*ghr_" + "?" * 36 + "*"),
    ("anthropic-key", "*sk-ant-" + "?" * 20 + "*"),
    ("openai-style-key", "*sk-proj-" + "?" * 16 + "*"),
    ("generic-sk-key", "*sk-" + "?" * 24 + "*"),
)

TRIGGER_BI = "trg_messages_redact_bi"
TRIGGER_BU = "trg_messages_redact_bu"


def _trigger_sql(name: str, when: str) -> str:
    whens = " OR ".join(f"NEW.body GLOB '{g}'" for _, g in SHAPE_GLOBS)
    return (
        f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {when} ON messages "
        f"BEGIN SELECT CASE WHEN {whens} THEN "
        f"RAISE(ABORT, 'message_store: credential-shaped body refused; "
        f"route text through tools/redact_text.py') END; END"
    )


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif row[0] != SCHEMA_VERSION:
        raise ValueError(f"message_store: unsupported schema version {row[0]}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY, ts REAL NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL)"
    )
    conn.execute(_trigger_sql(TRIGGER_BI, "INSERT"))
    conn.execute(_trigger_sql(TRIGGER_BU, "UPDATE"))
    conn.commit()


def open_store(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    return conn


def _redact_mod():
    import importlib.util
    import sys
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("ms_redact", here / "redact_text.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def add_message(conn: sqlite3.Connection, body: str) -> tuple[int, list[tuple[str, int]]]:
    """Redact precisely in Python, then insert. Returns (row id, redaction hits)."""
    red, hits = _redact_mod().redact(body)
    digest = hashlib.sha256(red.encode("utf-8")).hexdigest()
    cur = conn.execute(
        "INSERT INTO messages (ts, body, digest) VALUES (?, ?, ?)",
        (time.time(), red, digest),
    )
    conn.commit()
    return cur.lastrowid, hits
