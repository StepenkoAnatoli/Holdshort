#!/usr/bin/env python3
"""Tests for tools/check_app_db_secrets.py — the pre-commit app-DB scan.

Invariants under test (each one is a real failure mode, not decoration):
  A1. a machine without the app store exits 0 with SKIP (CI runners, fresh clones)
  A2. a clean store passes
  A3. a planted credential-shaped string REFUSES the run (exit 1) and the value
      itself is never echoed into stdout/stderr (triaging must not re-leak)
  A4. a digest recorded in the baseline stops blocking (pre-triaged residue)
  A5. --update-baseline records digests (and only digests) so the next run is clean
  A6. the hook's `export HOME=<repo root>` cannot mask a real store: USERPROFILE
      wins, so a decoy app dir under HOME must not shadow the real one
  A7. an unreadable store fails CLOSED (exit 2), never "clean"
  A8. a malformed baseline fails CLOSED (exit 2) instead of silently disabling
      the allowlist
  A9. truncated token prefixes (the harmless `github_pat_` + 11 chars that a
      diagnostic once echoed) do NOT trip the scan — precision matters

Run as part of the regression gate (tools/run_regression.py). Fixture strings
are piece-concatenated so this tracked file never trips tools/check_secrets.py
itself, and no test ever prints a credential-shaped value.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_app_db_secrets.py"
spec = importlib.util.spec_from_file_location("cads", TOOL)
cads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cads)

# Two pieces, so the literal in this file is never itself a full token shape.
FAKE = "github_pat_" + "A1b2C3d4E5" * 6
PARTIAL = "github_pat_" + "11CL4M2GQ0"          # 11 chars after prefix: sub-threshold
FAKE_ANTHROPIC = "sk-ant-" + "fake0123456789" + "abcdef0123"


def make_app(root: Path, payloads: dict[str, bytes]) -> Path:
    """A minimal app-store fixture where the tool expects it:
    <root>/.config/freebuff-desktop/projects/p1/<name>."""
    app = root / ".config" / "freebuff-desktop"
    proj = app / "projects" / "p1"
    proj.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        (proj / name).write_bytes(data)
    return app


class AppDbSecrets(unittest.TestCase):

    def _env(self, **overrides) -> dict:
        env = dict(os.environ)
        env.pop("FREEBUFF_APP_DB_DIR", None)
        env.update(overrides)
        return env

    def _run(self, app_dir: Path | None, baseline: Path, *extra: str,
             env: dict | None = None) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(TOOL), "--baseline", str(baseline), *extra]
        if app_dir is not None:
            cmd += ["--db-dir", str(app_dir)]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                              env=env or self._env())

    # A1 -------------------------------------------------------------------
    def test_a1_absent_store_skips(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            r = self._run(None, Path(td) / "b.json",
                          env=self._env(USERPROFILE=str(empty), HOME=str(empty)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SKIP", r.stdout)

    # A2 -------------------------------------------------------------------
    def test_a2_clean_store_passes(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"benign transcript text " + b"x" * 200})
            r = self._run(app, Path(td) / "b.json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean (0 new hits", r.stdout)

    # A3 -------------------------------------------------------------------
    def test_a3_planted_token_refused_and_value_not_echoed(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {
                "desktop-v2.db": b"before " + FAKE.encode() + b" after",
                "desktop-v2.db-wal": b"noise " + FAKE_ANTHROPIC.encode(),
            })
            r = self._run(app, Path(td) / "b.json")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NEW token-shaped hit", r.stdout)
        self.assertIn("github-pat-fine-grained", r.stdout)
        self.assertIn("anthropic-key", r.stdout)
        for out in (r.stdout, r.stderr):
            self.assertNotIn(FAKE, out, "the scan must never echo the value")
            self.assertNotIn(FAKE_ANTHROPIC, out, "the scan must never echo the value")

    # A4 -------------------------------------------------------------------
    def test_a4_baselined_digest_stops_blocking(self):
        digest = hashlib.sha256(FAKE.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"x " + FAKE.encode()})
            baseline = Path(td) / "b.json"
            baseline.write_text(json.dumps({"digests": {digest: "pre-existing (triaged)"}}),
                                encoding="utf-8")
            r = self._run(app, baseline)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 baselined", r.stdout)

    # A5 -------------------------------------------------------------------
    def test_a5_update_baseline_records_digest_only(self):
        digest = hashlib.sha256(FAKE.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"x " + FAKE.encode()})
            baseline = Path(td) / "b.json"
            first = self._run(app, baseline)
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            upd = self._run(app, baseline, "--update-baseline", "--note", "unit-test triage")
            self.assertEqual(upd.returncode, 0, upd.stdout + upd.stderr)
            again = self._run(app, baseline)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            doc = json.loads(baseline.read_text(encoding="utf-8"))
        self.assertIn(digest, doc["digests"])
        self.assertNotIn(FAKE, json.dumps(doc), "baseline must hold digests, never values")

    # A6 -------------------------------------------------------------------
    def test_a6_home_override_cannot_shadow_real_store(self):
        with tempfile.TemporaryDirectory() as td:
            real_parent = Path(td) / "real-user"
            decoy_parent = Path(td) / "hook-home"
            real_app = make_app(real_parent, {"desktop-v2.db": b"x " + FAKE.encode()})
            make_app(decoy_parent, {"desktop-v2.db": b"harmless decoy"})
            # The hook exports HOME=<repo root>; a decoy store lives there and
            # the real one is reachable only via USERPROFILE.
            r = self._run(None, Path(td) / "b.json",
                          env=self._env(USERPROFILE=str(real_parent), HOME=str(decoy_parent)))
        self.assertEqual(r.returncode, 1,
                         "USERPROFILE must win over HOME, else the hook run skips the real store")
        self.assertIn(str(real_app), r.stdout)

    # A7 -------------------------------------------------------------------
    def test_a7_unreadable_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {})
            (app / "projects" / "p1" / "desktop-v2.db").mkdir()  # unreadable as a file
            r = self._run(app, Path(td) / "b.json")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # A8 -------------------------------------------------------------------
    def test_a8_malformed_baseline_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"harmless"})
            baseline = Path(td) / "b.json"
            baseline.write_text("{ this is not json", encoding="utf-8")
            r = self._run(app, baseline)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # A9 -------------------------------------------------------------------
    def test_a9_truncated_prefix_is_not_a_hit(self):
        for name, pat in cads.PATTERNS:
            self.assertIsNone(pat.search(PARTIAL),
                              f"{name} must not fire on a truncated prefix")
        hits = [n for n, p in cads.PATTERNS if p.search(FAKE)]
        self.assertIn("github-pat-fine-grained", hits)

    def test_a9b_reused_check_secrets_patterns_still_present(self):
        names = [n for n, _ in cads.PATTERNS]
        for expected in ("anthropic-key", "openai-style-key", "generic-sk-key"):
            self.assertIn(expected, names)
        self.assertIn("github-oauth", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
