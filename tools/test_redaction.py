#!/usr/bin/env python3
"""Tests for tools/redaction.py — the pre-write transcript redaction layer.

Fixture discipline (learned the hard way, see app_db_secrets_baseline.json):
credential-shaped fixture values are built by CONCATENATION so no literal
token shape exists in this source file, and no assertion message ever prints
a fixture value — only classes and digests — so a failing run cannot leak
token-shaped text into a thread transcript (and from there into the app's
desktop-v2.db stores).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import redaction  # noqa: E402
import check_secrets as cs  # noqa: E402
import check_app_db_secrets as appdb  # noqa: E402

REPO_ROOT = TOOLS.parent

SAMPLES = {
    "anthropic-key": "sk-ant-" + "fake0123456789" + "abcdef0123",
    "openai-style-key": "sk-proj-" + "f" * 20,
    "generic-sk-key": "sk-" + "x" * 30,
    "github-pat-fine-grained": "github_pat_" + "f" * 24,
    "github-pat-classic": "ghp_" + "a" * 36,
    "github-oauth": "gho_" + "b" * 36,
    "github-user-to-server": "ghu_" + "c" * 36,
    "github-server-to-server": "ghs_" + "d" * 36,
    "github-refresh": "ghr_" + "e" * 36,
    "key-assignment": "api_key = " + "z" * 20,
    # "Authoriz"+"ation" split: contiguous, the line "bearer-token":
    # "Authorization…" would itself match the key-assignment pattern
    "bearer-token": "Authoriz" + "ation: Bearer " + "t" * 20,
}


def scanner_hits(text: str) -> list:
    """(class) for anything either audited scanner would still flag."""
    hits = []
    for name, pat in cs.PATTERNS + appdb.PATTERNS:
        if pat.search(text):
            hits.append(name)
    return hits


def digest16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class Coverage(unittest.TestCase):
    def test_every_class_has_a_sample(self):
        self.assertEqual(set(SAMPLES), {n for n, _ in redaction.PATTERNS})

    def test_sample_really_matches_its_class(self):
        by_name = dict(redaction.PATTERNS)
        for name, sample in SAMPLES.items():
            self.assertIsNotNone(by_name[name].search(sample), name)

    def test_redacted_output_defeats_every_scanner(self):
        # THE invariant: anything the gate would flag is stripped before write.
        for name, sample in SAMPLES.items():
            out, findings = redaction.redact_text(sample)
            self.assertTrue(findings, name)
            left = scanner_hits(out)
            self.assertEqual(left, [], f"{name}: {left} shapes survived redaction")

    def test_value_never_reaches_output(self):
        for name, sample in SAMPLES.items():
            out, findings = redaction.redact_text(sample)
            self.assertFalse(sample in out,
                             f"{name} value leaked (sha256={digest16(sample)}...)")
            self.assertEqual(findings[0]["digest"],
                             hashlib.sha256(sample.encode("utf-8")).hexdigest(), name)
            self.assertEqual(findings[0]["class"], name)
            self.assertIn(digest16(sample), out)  # triage handle is kept

    def test_idempotent(self):
        for name, sample in SAMPLES.items():
            once, _ = redaction.redact_text(sample)
            twice, f2 = redaction.redact_text(once)
            self.assertEqual(once, twice, name)
            self.assertEqual(f2, [], name)

    def test_clean_text_unchanged(self):
        text = "route delegate; acceptance checks pass; spend $0.04"
        out, findings = redaction.redact_text(text)
        self.assertEqual(out, text)
        self.assertEqual(findings, [])

    def test_mixed_line_keeps_context(self):
        sample = SAMPLES["github-pat-classic"]
        out, findings = redaction.redact_text("pushed with " + sample + " in env")
        self.assertTrue(out.startswith("pushed with "), out[:20])
        self.assertTrue(out.endswith(" in env"), out[-20:])
        self.assertEqual(len(findings), 1)
        self.assertFalse(sample in out, "value leaked")

    def test_overlapping_classes_prefer_specific(self):
        for name in ("anthropic-key", "openai-style-key"):
            _out, findings = redaction.redact_text(SAMPLES[name])
            self.assertEqual(findings[0]["class"], name)

    def test_bytes_roundtrip(self):
        sample = SAMPLES["github-oauth"]
        raw = b"ledger note: " + sample.encode() + b" end"
        out, findings = redaction.redact_bytes(raw)
        self.assertFalse(sample.encode() in out, "value leaked")
        self.assertEqual(len(findings), 1)

    def test_utf16_logs_redacted_with_and_without_bom(self):
        sample = SAMPLES["github-oauth"]
        for encoding, bom in (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")):
            for prefix in (b"", bom):
                raw = prefix + ("note " + sample + " end").encode(encoding)
                out, findings = redaction.redact_bytes(raw)
                decoded = out[len(prefix):].decode(encoding)
                self.assertFalse(sample in decoded, "credential shape survived UTF-16 filtering")
                self.assertTrue(out.startswith(prefix))
                self.assertEqual(len(findings), 1)

    def test_ambiguous_bytes_refused_without_output(self):
        result = subprocess.run([sys.executable, "tools/redaction.py", "--quiet"],
                                cwd=REPO_ROOT, input=b"\x00oddx", capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")

    def test_json_recursion(self):
        doc = {"reason": "via " + SAMPLES["generic-sk-key"], "n": 3,
               "nested": [{"k": SAMPLES["key-assignment"]}], "none": None, "ok": True}
        out, findings = redaction.redact_obj(doc)
        self.assertEqual(len(findings), 2)
        dumped = json.dumps(out)
        self.assertFalse(SAMPLES["generic-sk-key"] in dumped, "value leaked")
        self.assertFalse(SAMPLES["key-assignment"] in dumped, "value leaked")
        self.assertEqual(out["n"], 3)
        self.assertIsNone(out["none"])
        self.assertTrue(out["ok"])
        self.assertEqual(scanner_hits(dumped), [])

    def test_dict_keys_redacted_too(self):
        sample = SAMPLES["github-pat-classic"]
        out, findings = redaction.redact_obj({sample: "v"})
        self.assertEqual(len(findings), 1)
        self.assertEqual(scanner_hits(json.dumps(out)), [])


class CLI(unittest.TestCase):
    def _run(self, args, input_bytes: bytes):
        return subprocess.run([sys.executable, "tools/redaction.py"] + args,
                              cwd=REPO_ROOT, input=input_bytes,
                              capture_output=True, timeout=60)

    def test_stdin_roundtrip_redacts(self):
        sample = SAMPLES["anthropic-key"]
        r = self._run(["--quiet"], b"note " + sample.encode() + b" end")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(sample.encode() in r.stdout, "value leaked")
        self.assertTrue(r.stdout.startswith(b"note "))
        self.assertTrue(r.stdout.endswith(b" end"))

    def test_fail_on_hit_gates(self):
        sample = SAMPLES["github-refresh"]
        r1 = self._run(["--fail-on-hit", "--quiet"], b"clean text")
        self.assertEqual(r1.returncode, 0)
        r2 = self._run(["--fail-on-hit", "--quiet"], sample.encode())
        self.assertEqual(r2.returncode, 1)
        self.assertFalse(sample.encode() in r2.stdout, "value leaked")

    def test_summary_reports_digests_not_values(self):
        sample = SAMPLES["github-pat-classic"]
        r = self._run([], b"x " + sample.encode() + b" y")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(sample.encode() in r.stderr, "value leaked to summary")
        self.assertIn(b"sha256=", r.stderr)

    def test_clean_run_is_silent_on_stderr(self):
        r = self._run([], b"nothing to see")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, b"")


class WriterIntegration(unittest.TestCase):
    """The repo's transcript-bound writers must pass through the layer."""

    def test_task_state_is_redacted(self):
        import task_persistence as tp
        token = SAMPLES["anthropic-key"]
        with tempfile.TemporaryDirectory() as td:
            store = tp.TaskStateStore(Path(td))
            store.save({"task_id": "T-1", "attempts": 1, "spent": 0.0,
                        "started": 1.0, "repairs": 1, "last_profile": token})
            raw = (Path(td) / "T-1.json").read_text(encoding="utf-8")
            self.assertFalse(token in raw, "value leaked")
            self.assertEqual(scanner_hits(raw), [])
            self.assertIn("[REDACTED:", raw)

    def test_ledger_line_is_redacted(self):
        import live_dispatcher as ld
        token = SAMPLES["github-pat-classic"]
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "ledger.jsonl"
            prices = {"pilot_caps": {
                "max_attempts_per_task": 4,
                "max_cost_per_task_usd": 1.0,
                "max_cost_per_pilot_usd": 20.0,
                "max_elapsed_seconds_per_task": 300,
                "same_profile_repairs_allowed_per_task": 1,
            }}
            d = ld.LiveDispatcher(prices, ledger)
            d._reject({"task_id": "T-2", "attempts": 0}, "profile-a",
                      "blocked", "reason with " + token)
            raw = ledger.read_text(encoding="utf-8")
            self.assertFalse(token in raw, "value leaked")
            self.assertEqual(scanner_hits(raw), [])
            self.assertIn("[REDACTED:", raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
