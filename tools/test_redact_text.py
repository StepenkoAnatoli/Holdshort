#!/usr/bin/env python3
"""Tests for tools/redact_text.py — the pre-write redaction filter.

Invariants (each a real failure mode):
  R1. the filter reuses check_app_db_secrets.PATTERNS by import (no copied set to drift)
  R2. every audited class is redacted (one synthetic per class, piece-built so this
      tracked file never trips tools/check_secrets.py itself)
  R3. the value is never echoed into --stats / --check output (class+count only)
  R4. redaction is idempotent: redact(redact(x)) == redact(x)
  R5. truncated token prefixes are NOT redacted (precision, mirroring A9)
  R6. --check exits 1 on shapes, 0 when clean; plain filter exits 0 and writes redacted text
  R7. --file mode matches the stdin filter byte-for-byte
  R8. redacted output scans clean under the check's own patterns (placeholders hold no shapes)
  R9. known-miss cases per class: sub-threshold tails, bare prefixes, wrong
      separators/case, and boundary lookalikes are left untouched (no over-redaction)

Run as part of the regression gate (tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "redact_text.py"
CHECK = REPO / "tools" / "check_app_db_secrets.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rt = _load("rt_redact", TOOL)
cads = _load("cads_redact_test", CHECK)

# Piece-built fixtures: no literal in this file is itself a full token shape.
FAKE_FG = "github_pat_" + "A1b2C3d4E5" * 6
FAKE_CLASSIC = "ghp_" + "A1b2C3d4E5" * 4  # 40 chars, satisfies {36}
FAKE_OAUTH = "gho_" + "B2c3D4e5F6" * 4
FAKE_UTS = "ghu_" + "C3d4E5f6G7" * 4
FAKE_STS = "ghs_" + "D4e5F6g7H8" * 4
FAKE_REFRESH = "ghr_" + "E5f6G7h8I9" * 4
FAKE_ANTHROPIC = "sk-ant-" + "fake0123456789" + "abcdef0123"
FAKE_OPENAI = "sk-proj-" + "Abcdef0123456789" + "XYZ"
FAKE_GENERIC = "sk-" + "Z" * 24
PARTIAL = "github_pat_" + "11CL4M2GQ0"  # sub-threshold, must not redact


def _run_stdin(text: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *extra], input=text,
                          capture_output=True, text=True, timeout=60)


class Redact(unittest.TestCase):

    # R1 -------------------------------------------------------------------
    def test_r1_reuses_check_pattern_set(self):
        self.assertEqual([n for n, _ in rt.cads.PATTERNS],
                         [n for n, _ in cads.PATTERNS],
                         "redaction must reuse the check's audited pattern set by import")
        self.assertGreater(len(rt.cads.PATTERNS), 0)

    # R2 -------------------------------------------------------------------
    def test_r2_every_class_is_redacted(self):
        per_class = {
            "github-pat-fine-grained": FAKE_FG,
            "github-pat-classic": FAKE_CLASSIC,
            "github-oauth": FAKE_OAUTH,
            "github-user-to-server": FAKE_UTS,
            "github-server-to-server": FAKE_STS,
            "github-refresh": FAKE_REFRESH,
            "anthropic-key": FAKE_ANTHROPIC,
            "openai-style-key": FAKE_OPENAI,
            "generic-sk-key": FAKE_GENERIC,
        }
        for name, value in per_class.items():
            with self.subTest(cls=name):
                red, hits = rt.redact("before " + value + " after")
                self.assertNotIn(value, red)
                self.assertIn("[REDACTED-" + name + "]", red)
                self.assertIn(name, [h for h, _ in hits])

    # R3 -------------------------------------------------------------------
    def test_r3_stats_and_check_never_echo_values(self):
        values = [FAKE_FG, FAKE_ANTHROPIC, FAKE_GENERIC]
        text = " ".join(values)
        for extra in (["--stats"], ["--check"]):
            r = _run_stdin(text, *extra)
            blob = r.stdout + r.stderr
            for v in values:
                self.assertNotIn(v, blob, f"{extra} must never echo the value")

    # R4 -------------------------------------------------------------------
    def test_r4_idempotent(self):
        text = "a " + FAKE_FG + " b " + FAKE_ANTHROPIC + " c"
        once, _ = rt.redact(text)
        twice, hits2 = rt.redact(once)
        self.assertEqual(once, twice)
        self.assertEqual(hits2, [], "placeholders must hold no further shapes")

    # R5 -------------------------------------------------------------------
    def test_r5_truncated_prefix_not_redacted(self):
        red, hits = rt.redact("harmless " + PARTIAL + " end")
        self.assertEqual(red, "harmless " + PARTIAL + " end")
        self.assertEqual(hits, [])

    # R6 -------------------------------------------------------------------
    def test_r6_check_exit_codes(self):
        dirty = _run_stdin("x " + FAKE_FG, "--check")
        self.assertEqual(dirty.returncode, 1)
        self.assertIn("would redact", dirty.stderr)
        clean = _run_stdin("harmless transcript text", "--check")
        self.assertEqual(clean.returncode, 0)

    def test_r6b_filter_writes_redacted_text(self):
        r = _run_stdin("x " + FAKE_FG + " y")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn(FAKE_FG, r.stdout)
        self.assertIn("[REDACTED-github-pat-fine-grained]", r.stdout)

    # R7 -------------------------------------------------------------------
    def test_r7_file_mode_matches_stdin(self):
        text = "note " + FAKE_OAUTH + " tail"
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "draft.md"
            f.write_text(text, encoding="utf-8")
            via_file = subprocess.run([sys.executable, str(TOOL), "--file", str(f)],
                                      capture_output=True, text=True, timeout=60)
            via_stdin = _run_stdin(text)
        self.assertEqual(via_file.returncode, 0)
        self.assertEqual(via_file.stdout, via_stdin.stdout)
        self.assertNotIn(FAKE_OAUTH, via_file.stdout)

    # R9 -------------------------------------------------------------------
    def test_r9_known_misses_left_untouched(self):
        # Every entry is one char short, wrongly cased/separated, or a boundary
        # lookalike. Piece-built throughout so this file stays literal-free.
        misses = {
            "github-pat-fine-grained": [
                "github_pat_" + "A" * 19,
                "github_pat_",
                "github_pat-" + "A" * 30,
                "GITHUB_PAT_" + "A" * 30,
            ],
            "github-pat-classic": [
                "ghp_" + "A" * 35,
                "ghp_",
                "GHP_" + "A" * 36,
            ],
            "github-oauth": ["gho_" + "B" * 35, "gho_"],
            "github-user-to-server": ["ghu_" + "C" * 35, "ghu_"],
            "github-server-to-server": ["ghs_" + "D" * 35, "ghs_"],
            "github-refresh": ["ghr_" + "E" * 35, "ghr_"],
            "anthropic-key": ["sk-ant-" + "f" * 19, "sk-ant-", "sk-ant-short"],
            "openai-style-key": ["sk-proj-" + "A" * 15, "sk-proj-"],
            "generic-sk-key": ["sk-" + "Z" * 23, "mask-" + "Z" * 24],
        }
        for name, cases in misses.items():
            for case in cases:
                with self.subTest(cls=name, case=case[:20]):
                    red, hits = rt.redact("before " + case + " after")
                    self.assertEqual(red, "before " + case + " after",
                                     f"{name} over-redacted a known miss")
                    self.assertEqual(hits, [])

    # R8 -------------------------------------------------------------------
    def test_r8_redacted_output_scans_clean(self):
        text = " ".join([FAKE_FG, FAKE_CLASSIC, FAKE_OAUTH, FAKE_UTS, FAKE_STS,
                         FAKE_REFRESH, FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_GENERIC])
        red, _ = rt.redact(text)
        for name, pat in cads.PATTERNS:
            self.assertIsNone(pat.search(red), f"placeholder reintroduced {name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
