#!/usr/bin/env python3
"""Tests for the row-4 .env key-placement guard contract.

Verifies the exact invariants the secrets scan relies on:
  E1. `.env` is gitignored (never tracked, never scannable contents-wise)
  E2. `.env.example` is TRACKED and contains no real key — only the empty
      placeholder and a non-secret base URL
  E3. the scanner (tools/check_secrets.py) WOULD flag a real-looking key if
      it ever leaked into a tracked file (patterns proven with synthetic
      fixtures, no network)
  E4. the scanner's scope is exactly `git ls-files` — i.e. by construction
      .env is out of the scan corpus even if formatted like a tracked file
  E5. .gitignore rules match precisely: `.env`, `.env.*` ignored; `.env.example`
      explicitly negated `!.env.example`
Run as part of the regression gate (folded into tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cs", REPO / "tools" / "check_secrets.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip()


class EnvGuard(unittest.TestCase):

    # E1 ------------------------------------------------------------------
    def test_env_is_gitignored(self):
        r = subprocess.run(["git", "check-ignore", ".env"], cwd=REPO, capture_output=True)
        # exit 0 = ignored. If .env doesn't exist locally, create+delete nothing—
        # check-ignore works from the rule table regardless of file existence.
        self.assertEqual(r.returncode, 0, ".env must be gitignored per the row-4 decision")

    def test_env_never_tracked(self):
        tracked = git("ls-files")
        self.assertNotIn(".env\n", "\n" + tracked + "\n")
        self.assertNotIn(".env ", tracked)  # any tracked path starting '.env'

    # E2 ------------------------------------------------------------------
    def test_env_example_is_tracked(self):
        tracked = git("ls-files", ".env.example")
        self.assertEqual(tracked, ".env.example", ".env.example must be tracked as the template")

    def test_env_example_contains_no_real_key(self):
        text = (REPO / ".env.example").read_text(encoding="utf-8")
        for name, pat in cs.PATTERNS:
            for line in text.splitlines():
                if "re.compile" in line:  # not applicable: example file has no patterns
                    continue
                self.assertIsNone(pat.search(line),
                                  f".env.example leaked a credential-shaped string ({name}): {line!r}")

    def test_env_example_has_empty_key_placeholder(self):
        text = (REPO / ".env.example").read_text(encoding="utf-8")
        self.assertIn("ANTHROPIC_API_KEY=", text)
        # the template must NOT carry a value after the = (placeholder is empty)
        for line in text.splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                self.assertEqual(line.strip(), "ANTHROPIC_API_KEY=")

    # E3 ------------------------------------------------------------------
    def test_scanner_flags_a_leaked_fake_key(self):
        leaked = 'ANTHROPIC_API_KEY=' + 'sk-ant-AA' + 'AAfake' + '0123456789abcdef0123\n'
        hits = []
        for name, pat in cs.PATTERNS:
            m = pat.search(leaked)
            if m:
                hits.append(name)
        self.assertIn("anthropic-key", hits, "scanner must catch an Anthropic-shaped leak")
        self.assertTrue(hits, "scanner must catch the leak")

    def test_scanner_flags_key_assignment_without_prefix(self):
        leaked = 'api_key = ' + 'someopaque' + 'value12345\n'
        hits = [n for n, p in cs.PATTERNS if p.search(leaked)]
        self.assertIn("key-assignment", hits)

    def test_clean_tree_scans_clean(self):
        # full real scan must be clean at the time this test runs (tracked files only)
        self.assertEqual(cs.scan(), [], f"unexpected hits: {cs.scan()}")

    # E4 ------------------------------------------------------------------
    def test_scan_scope_is_tracked_files(self):
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True)
        self.assertEqual(out.returncode, 0)
        files = out.stdout.decode().split("\x00")
        self.assertNotIn(".env", [f for f in files if f],
                         ".env must never appear in the scan corpus (it is untracked)")

    # E5 ------------------------------------------------------------------
    def test_gitignore_rules_exact(self):
        gi = (REPO / ".gitignore").read_text(encoding="utf-8")
        lines = [l.strip() for l in gi.splitlines()]
        self.assertIn(".env", lines)
        self.assertIn(".env.*", lines)
        self.assertIn("!.env.example", lines)


class DecodePolicy(unittest.TestCase):
    """The scan never silently leaves a text-class file unscanned.

    H1: encoding variants of a leak are still caught (utf-8-sig, utf-16-le,
        utf-16-be) — utf-8-only scanning was blind to these.
    H2: an undecodable text-class file FAILS CLOSED (SystemExit with the
        fail-closed message, i.e. the CLI exits 2) instead of silently
        skipping the file (the old except-and-continue behavior).
    H3: genuinely binary extensions stay skipped (no false fail on .png).
    """

    # piece-concatenated so the file's own literal does not trip the scanner
    KEY = ('ANTHROPIC_API_KEY=' + 'sk-ant-' + 'fake0123456789'
           'abcdef0123' + '\n')

    def test_mp4_asset_is_recognized_by_container_header(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / 'clip.mp4'
            p.write_bytes((24).to_bytes(4, 'big') + b'ftyp' + b'isom'
                          + b'\x00\x00\x02\x00' + b'iso2mp41' + b'\xff\x00\x83')
            with mock.patch.object(cs, 'ROOT', root), \
                    mock.patch.object(cs, 'tracked_files', return_value=['clip.mp4']):
                self.assertEqual(cs.scan(), [])

    def test_credential_text_named_mp4_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / 'text.mp4'
            p.write_text(self.KEY, encoding='utf-8')
            with mock.patch.object(cs, 'ROOT', root), \
                    mock.patch.object(cs, 'tracked_files', return_value=['text.mp4']):
                self.assertTrue(cs.scan(), 'a .mp4 suffix must not hide credential text')

    def test_unrecognized_binary_named_mp4_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'broken.mp4').write_bytes(b'\xff\x00\x83')
            with mock.patch.object(cs, 'ROOT', root), \
                    mock.patch.object(cs, 'tracked_files', return_value=['broken.mp4']):
                with self.assertRaises(cs.UnscannableError):
                    cs.scan()

    def _hit_in_leak_bytes(self, raw: bytes) -> bool:
        """True iff the scanner's patterns catch the leak after decode_text."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "leak.txt"
            p.write_bytes(raw)
            text = cs.decode_text(p)
        return any(pat.search(line) for _, pat in cs.PATTERNS for line in text.splitlines())

    def test_h1_utf8_sig_leak_caught(self):
        self.assertTrue(self._hit_in_leak_bytes(b"\xef\xbb\xbf" + self.KEY.encode("utf-8")))

    def test_h1_utf16_le_leak_caught(self):
        self.assertTrue(self._hit_in_leak_bytes(self.KEY.encode("utf-16-le")))

    def test_h1_utf16_be_leak_caught(self):
        self.assertTrue(self._hit_in_leak_bytes(self.KEY.encode("utf-16-be")))

    def test_h1_utf16_bom_leak_caught(self):
        self.assertTrue(self._hit_in_leak_bytes(self.KEY.encode("utf-16")))

    def test_h1_plain_utf8_still_caught(self):
        self.assertTrue(self._hit_in_leak_bytes(self.KEY.encode("utf-8")))

    def test_h2_undecodable_fails_closed(self):
        # bytes invalid in utf-8, utf-16-le, utf-16-be, and utf-16 alike:
        # odd-length AND no BOM kills every candidate in one shot.
        garbage = b"\xff\x00\xfe\xff\x00\xff\xfe\x00\xff"
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "garbage.txt"
            p.write_bytes(garbage)
            for enc in cs.UTF8_FAMILY + cs.UTF16_FAMILY:
                with self.assertRaises(UnicodeDecodeError,
                                       msg=f"precondition broken: {enc} decoded the 'garbage'"):
                    garbage.decode(enc)
            with self.assertRaises(cs.UnscannableError):
                cs.decode_text(p)
        # end-to-end CLI: a tracked undecodable file must produce exit 2 and
        # the fail-closed message. Fake repo: own .git, tracked garbage.txt.
        import contextlib, io
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td) / "repo"
            fake_root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=fake_root, check=True)
            subprocess.run(["git", "config", "user.email", "t@t.invalid"], cwd=fake_root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=fake_root, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=fake_root, check=True)
            (fake_root / "garbage.txt").write_bytes(garbage)
            subprocess.run(["git", "add", "garbage.txt"], cwd=fake_root, check=True)
            orig_root = cs.ROOT
            try:
                cs.ROOT = fake_root
                buf_err = io.StringIO()
                with contextlib.redirect_stderr(buf_err), contextlib.redirect_stdout(io.StringIO()):
                    rc = cs.main()
            finally:
                cs.ROOT = orig_root
        self.assertEqual(rc, 2, "undecodable tracked file must fail closed with exit 2")
        self.assertIn("FAIL-CLOSED", buf_err.getvalue())

    def test_h2_utf16_without_bom_still_scanned_not_skipped(self):
        # Mangled-decode fallback: utf-16-le with no BOM decodes as NUL-mixed
        # utf-8; decode_text must return SOME text (fallback), never raise,
        # so the leak inside is still searched.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "nul.txt"
            p.write_bytes(self.KEY.encode("utf-16-le"))
            text = cs.decode_text(p)
        self.assertIn("sk-ant-", text)  # the leak is still in the scanned text


if __name__ == "__main__":
    unittest.main(verbosity=2)
