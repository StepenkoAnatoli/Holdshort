#!/usr/bin/env python3
"""Fake-key fixture hygiene: concatenation-only, never literal, never echoed.

Invariants (task: no pattern-matching secret literal may be captured into
transcripts again):
  F1. No tracked text file contains a full-pattern secret literal. Pattern
      *definitions* (re.compile lines) are excluded; everything else fails.
  F2. Every fixture line in test/fixture sources that mentions a key prefix
      builds it by concatenation (contains `+`) or is a pattern definition.
      A contiguous literal can never be typed into a fixture by accident.
  F3. Concatenation-built fakes still match the scanner patterns, so they
      remain effective fixtures (no network).
  F4. Closed loop on runtime output: the scanner and every fixture-bearing
      test script are executed with output captured, and the assembled fakes
      are absent from all of it. A fake that never appears whole on disk or
      on stdout cannot be captured into a transcript.
Run as part of the regression gate (folded into tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

def load_mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cs = load_mod("cs", "tools/check_secrets.py")
appdb = load_mod("appdb", "tools/check_app_db_secrets.py")
SCANNER_PATTERNS = [pat for _, pat in list(cs.PATTERNS) + list(appdb.PATTERNS)]

# Assembled ONLY by concatenation, mirroring the existing fixture style.
FAKE_PAT = "ghp_" + "A1b2C3d4E5" * 4
FAKE_FG_PAT = "github_pat_" + "A1b2C3d4E5" * 6
FAKE_ANTHROPIC = "sk-ant-" + "fake0123456789" + "abcdef0123"
PARTIAL_FG = "github_pat_" + "11CL4M2GQ0"
ALL_FAKES = (FAKE_PAT, FAKE_FG_PAT, FAKE_ANTHROPIC, PARTIAL_FG)

FULL_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"gho_[A-Za-z0-9]{36}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{24,}\b"),
)
PREFIXES = ("ghp_", "gho_", "github_pat_", "sk-ant-", "sk-proj-")
ASSIGN_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*[\"\']")
TEXT_SUFFIXES = {".py", ".md", ".sh", ".json", ".yml", ".yaml", ".txt", ".example"}
FIXTURE_SCOPE = ("tools/test_", "tests/", "fixture_checks.py")


def tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, cwd=REPO)
    for rel in out.stdout.split(b"\x00"):
        rel = rel.decode("utf-8", errors="replace")
        if not rel or ".git/" in rel or "__pycache__" in rel:
            continue
        if Path(rel).suffix in TEXT_SUFFIXES:
            yield rel


def is_fixture_scope(rel: str) -> bool:
    return rel == "fixture_checks.py" or rel.startswith(FIXTURE_SCOPE)


class FixtureKeyHygiene(unittest.TestCase):
    def test_f1_no_full_literal_in_tracked_files(self):
        hits = []
        for rel in tracked_text_files():
            try:
                lines = (REPO / rel).read_text(encoding="utf-8", errors="strict").splitlines()
            except (OSError, UnicodeError):
                continue
            for i, ln in enumerate(lines, 1):
                if "re.compile" in ln:
                    continue
                for pat in FULL_PATTERNS:
                    if pat.search(ln):
                        hits.append(f"{rel}:{i}")
                        break
        self.assertEqual(hits, [], f"full-pattern literals in tracked files: {hits[:10]}")

    def test_f2_fixture_prefixes_only_by_concatenation(self):
        bad = []
        for rel in tracked_text_files():
            if not is_fixture_scope(rel):
                continue
            try:
                lines = (REPO / rel).read_text(encoding="utf-8", errors="strict").splitlines()
            except (OSError, UnicodeError):
                continue
            for i, ln in enumerate(lines, 1):
                if "re.compile" in ln or "FULL_PATTERNS" in ln or "PREFIXES" in ln:
                    continue
                if ASSIGN_RE.match(ln) and any(px in ln for px in PREFIXES) and "+" not in ln:
                    bad.append(f"{rel}:{i}: {ln.strip()[:70]}")
        self.assertEqual(bad, [], f"non-concatenated fixture prefixes: {bad[:10]}")

    def test_f3_concat_fakes_still_match_scanner(self):
        for fake in (FAKE_PAT, FAKE_FG_PAT, FAKE_ANTHROPIC):
            self.assertTrue(
                any(p.search(fake) for p in SCANNER_PATTERNS),
                "concat-built fake no longer matches any scanner pattern",
            )

    def test_f4_fakes_absent_from_runtime_output(self):
        scripts = [
            ["tools/check_secrets.py"],
            ["tools/test_app_db_secrets.py"],
            ["tools/test_credential_hygiene.py"],
            ["tools/test_watch_app_db_secrets.py"],
            ["tools/test_secrets_env_guard.py"],
        ]
        for cmd in scripts:
            proc = subprocess.run(
                [sys.executable] + cmd, capture_output=True, text=True, cwd=REPO
            )
            blob = proc.stdout + proc.stderr
            for fake in ALL_FAKES:
                self.assertNotIn(fake, blob, f"{cmd[0]} echoes a full fake key")


if __name__ == "__main__":
    unittest.main(verbosity=2)
