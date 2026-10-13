#!/usr/bin/env python3
"""Tests for the repo-owned message store and its schema-version guard.

Invariants:
  T1. open_store() creates schema_version=1, the messages table, and both triggers.
  T2. raw INSERT/UPDATE of every audited class is refused by the triggers
      (fixtures piece-built; this file stays literal-free).
  T3. add_message() redacts in Python first: the stored body holds the
      placeholder and the raw value appears nowhere in the file bytes.
  T4. a messages table recreated bare (triggers lost) fails the guard.
  T5. a neutered trigger stub (no RAISE/markers) fails the guard.
  T6. a wrong schema version fails the guard.
  T7. a missing store is clean (nothing unprotected).
  T8. a healthy store passes the guard (exit 0).
Run as part of the regression gate (folded into tools/run_regression.py).
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import message_store as ms
import check_message_schema as guard

# Piece-built per class: each satisfies its regex minimum. No literal here is whole.
RAW = {
    "github-pat-fine-grained": "github_pat_" + "A1b2C3d4E5" * 6,
    "github-pat-classic": "ghp_" + "A1b2C3d4E5" * 4,
    "github-oauth": "gho_" + "B2c3D4e5F6" * 4,
    "github-user-to-server": "ghu_" + "C3d4E5f6G7" * 4,
    "github-server-to-server": "ghs_" + "D4e5F6g7H8" * 4,
    "github-refresh": "ghr_" + "E5f6G7h8I9" * 4,
    "anthropic-key": "sk-ant-" + "fake0123456789" + "abcdef0123",
    "openai-style-key": "sk-proj-" + "Abcdef0123456789" + "XYZ",
    "generic-sk-key": "sk-" + "Z" * 24,
}


def fresh_db(td: Path) -> Path:
    p = td / "m.db"
    ms.open_store(p).close()
    return p


class MessageSchema(unittest.TestCase):
    def test_t1_schema_and_triggers_created(self):
        with tempfile.TemporaryDirectory() as td:
            p = fresh_db(Path(td))
            conn = sqlite3.connect(str(p))
            ver = conn.execute("SELECT version FROM schema_version").fetchone()[0]
            self.assertEqual(ver, ms.SCHEMA_VERSION)
            trigs = dict(conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger'").fetchall())
            for want in (ms.TRIGGER_BI, ms.TRIGGER_BU):
                self.assertIn(want, trigs)
                self.assertIn("RAISE", trigs[want])
            conn.close()

    def test_t2_raw_writes_refused_every_class(self):
        with tempfile.TemporaryDirectory() as td:
            p = fresh_db(Path(td))
            conn = sqlite3.connect(str(p))
            for name, value in RAW.items():
                with self.subTest(cls=name):
                    with self.assertRaises(sqlite3.IntegrityError, msg=name):
                        conn.execute(
                            "INSERT INTO messages (ts, body, digest) VALUES (0, ?, 'd')",
                            ("prefix " + value + " suffix",))
                    conn.rollback()
            rid = conn.execute(
                "INSERT INTO messages (ts, body, digest) VALUES (0, 'clean', 'd')").lastrowid
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE messages SET body=? WHERE id=?",
                             ("now " + RAW["github-pat-classic"], rid))
            conn.close()

    def test_t3_add_message_redacts_before_insert(self):
        with tempfile.TemporaryDirectory() as td:
            p = fresh_db(Path(td))
            conn = sqlite3.connect(str(p))
            value = RAW["anthropic-key"]
            rid, hits = ms.add_message(conn, "before " + value + " after")
            conn.close()
            self.assertIn("anthropic-key", [h for h, _ in hits])
            body = sqlite3.connect(str(p)).execute(
                "SELECT body FROM messages WHERE id=?", (rid,)).fetchone()[0]
            self.assertIn("[REDACTED-anthropic-key]", body)
            raw = p.read_bytes()
            self.assertNotIn(value.encode(), raw, "raw value must not reach the file")

    def _guard(self, *stores: Path) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(REPO / "tools" / "check_message_schema.py")]
        for s in stores:
            cmd += ["--store", str(s)]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    def test_t4_recreated_bare_table_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = fresh_db(Path(td))
            conn = sqlite3.connect(str(p))
            conn.execute("DROP TRIGGER trg_messages_redact_bi")
            conn.execute("DROP TRIGGER trg_messages_redact_bu")
            conn.execute("DROP TABLE messages")
            conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
            conn.commit()
            conn.close()
            r = self._guard(p)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("missing trigger", r.stdout)

    def test_t5_neutered_trigger_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = fresh_db(Path(td))
            conn = sqlite3.connect(str(p))
            conn.execute("DROP TRIGGER trg_messages_redact_bi")
            conn.execute("CREATE TRIGGER trg_messages_redact_bi "
                         "BEFORE INSERT ON messages BEGIN SELECT 1; END")
            conn.commit()
            conn.close()
            r = self._guard(p)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("neutered", r.stdout)

    def test_t6_wrong_version_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = fresh_db(Path(td))
            conn = sqlite3.connect(str(p))
            conn.execute("UPDATE schema_version SET version=999")
            conn.commit()
            conn.close()
            r = self._guard(p)
            self.assertEqual(r.returncode, 1, r.stdout)

    def test_t7_missing_store_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._guard(Path(td) / "absent.db")
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_t8_healthy_store_passes(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._guard(fresh_db(Path(td)))
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
