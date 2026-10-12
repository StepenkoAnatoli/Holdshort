#!/usr/bin/env python3
"""Tests for tools/watch_app_db_secrets.py — the change-triggered app-DB watcher.

Invariants under test (each a real failure mode):
  W1. a machine with no app store exits 0 with a "nothing to watch" line, not an alert
  W2. a clean store stays silent
  W3. a planted token alerts (exit 1) and the VALUE is never echoed into stdout, stderr,
      the log, or the state file — flagging must not re-leak
  W4. a digest in the baseline is not alerted (triage is respected)
  W5. a store change triggers the scan (the point of the watcher) and the alert names the
      trigger as "changed", with no dependence on the heartbeat
  W6. duplicate suppression: the second pass still exits 1 — a leak that is still there
      is still a leak — but does not re-emit the alert
  W7. the prefilter is sound: prefixes are derivable for the audited pattern set, its
      result AGREES with the check's own scan_store, and a pattern set that cannot be
      proven literal disables the prefilter instead of under-scanning
  W8. an unreadable store fails the pass CLOSED (exit 2) rather than reporting clean
  W9. a malformed baseline is fatal (exit 2)
  W10. --on-new receives the digest (and the class/store) in its environment, never the value
  W11. the loop's scan policy is pure and correct for each trigger

Every subprocess runs against an isolated EMPTY baseline (created in setUpClass), never
`tools/app_db_secrets_baseline.json`: the tracked baseline grows as token-shaped text is
triaged, and a fixture that is baselined there must not change what this suite asserts.

Fixture strings are piece-concatenated so this tracked file never trips
tools/check_secrets.py itself, and no test prints a credential-shaped value.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "watch_app_db_secrets.py"
CHECK = REPO / "tools" / "check_app_db_secrets.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                     # dataclass/typing lookups need the registration
    spec.loader.exec_module(mod)
    return mod


watch = _load("wads", TOOL)
cads = _load("cads", CHECK)

# Two pieces each: the literal in this file is never itself a full token shape.
FAKE = "github_pat_" + "A1b2C3d4E5" * 6
FAKE_ANTHROPIC = "sk-ant-" + "fake0123456789" + "abcdef0123"
PARTIAL = "github_pat_" + "11CL4M2GQ0"


def make_app(root: Path, payloads: dict[str, bytes]) -> Path:
    app = root / ".config" / "freebuff-desktop"
    proj = app / "projects" / "p1"
    proj.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        (proj / name).write_bytes(data)
    return app


class Watcher(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # The suite must not depend on the repo's live triage state. The tracked baseline
        # grows as token-shaped text is triaged — including our own fixtures, whose rendered
        # values have reached the app store through thread transcripts — so a test that used
        # the default baseline would stop asserting an alert the day that fixture was triaged.
        # (That is not hypothetical: W3 failed exactly that way.)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.empty_baseline = Path(cls._tmp.name) / "empty-baseline.json"
        cls.empty_baseline.write_text(json.dumps({"digests": {}}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run(self, app: Path | None, *extra: str, timeout: float = 30.0,
             env: dict | None = None) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(TOOL), *extra]
        if app is not None:
            cmd += ["--db-dir", str(app)]
        if "--baseline" not in extra:
            cmd += ["--baseline", str(self.empty_baseline)]
        e = dict(os.environ)
        e.pop("FREEBUFF_APP_DB_DIR", None)
        if env:
            e.update(env)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)

    def _clean_app(self, td: str) -> Path:
        return make_app(Path(td), {"desktop-v2.db": b"benign transcript text " + b"x" * 400})

    # W1 -------------------------------------------------------------------
    def test_w1_absent_store_is_not_an_alert(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            r = self._run(None, "--once", "--state", str(Path(td) / "s.json"),
                          env={"USERPROFILE": str(empty), "HOME": str(empty)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no Freebuff app dir", r.stdout)

    def test_w1b_app_dir_without_stores_is_not_an_alert(self):
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / ".config" / "freebuff-desktop"
            (app / "projects").mkdir(parents=True)
            r = self._run(app, "--once", "--state", str(Path(td) / "s.json"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no desktop-v2.* stores", r.stdout)

    # W2 -------------------------------------------------------------------
    def test_w2_clean_store_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run(self._clean_app(td), "--once", "--state", str(Path(td) / "s.json"),
                          "--verbose")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("NEW", r.stdout)
        self.assertIn("scan (once)", r.stdout, "verbose mode should report the pass")

    # W3 -------------------------------------------------------------------
    def test_w3_planted_token_alerts_and_value_is_never_echoed(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {
                "desktop-v2.db": b"before " + FAKE.encode() + b" after",
                "desktop-v2.db-wal": b"noise " + FAKE_ANTHROPIC.encode(),
            })
            state = Path(td) / "state.json"
            log = Path(td) / "watch.log"
            r = self._run(app, "--once", "--state", str(state), "--log", str(log))
            blob = r.stdout + r.stderr + state.read_text() + log.read_text()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NEW github-pat-fine-grained", r.stdout)
        self.assertIn("NEW anthropic-key", r.stdout)
        self.assertIn(hashlib.sha256(FAKE.encode()).hexdigest()[:16], r.stdout)
        for value in (FAKE, FAKE_ANTHROPIC):
            self.assertNotIn(value, blob, "the watcher must never echo or store the value")

    # W4 -------------------------------------------------------------------
    def test_w4_baselined_digest_is_not_alerted(self):
        digest = hashlib.sha256(FAKE.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"x " + FAKE.encode()})
            baseline = Path(td) / "b.json"
            baseline.write_text(json.dumps({"digests": {digest: "class=github-pat-fine-grained; triaged"}}))
            r = self._run(app, "--once", "--baseline", str(baseline),
                          "--state", str(Path(td) / "s.json"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("NEW", r.stdout)

    # W5 -------------------------------------------------------------------
    def test_w5_store_change_triggers_the_scan(self):
        with tempfile.TemporaryDirectory() as td:
            app = self._clean_app(td)
            store = app / "projects" / "p1" / "desktop-v2.db"
            cmd = [sys.executable, str(TOOL), "--db-dir", str(app), "--poll", "0.05",
                   "--debounce", "0", "--heartbeat", "2", "--max-scans", "3",
                   "--verbose", "--state", str(Path(td) / "s.json"),
                   "--baseline", str(self.empty_baseline)]
            env = dict(os.environ)
            env.pop("FREEBUFF_APP_DB_DIR", None)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env)
            try:
                time.sleep(0.6)                      # let the first (clean) pass happen
                with store.open("ab") as fh:         # the "leak" lands mid-watch
                    fh.write(b" pasted " + FAKE.encode())
                out, _ = proc.communicate(timeout=25)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
        self.assertEqual(proc.returncode, 1, out)
        self.assertIn("NEW github-pat-fine-grained", out)
        # the pass that alerted is the one reporting a non-zero "newly alerted" count
        alert_scan = [ln for ln in out.splitlines()
                      if "newly alerted" in ln and "0 newly alerted" not in ln]
        self.assertTrue(alert_scan, f"no alerting scan summary in:\n{out}")
        self.assertIn("(changed)", alert_scan[-1],
                      "the alerting pass must be the change-triggered one, not the heartbeat")
        self.assertNotIn(FAKE, out)

    # W6 -------------------------------------------------------------------
    def test_w6_duplicate_suppression_keeps_the_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"x " + FAKE.encode()})
            state = Path(td) / "s.json"
            first = self._run(app, "--once", "--state", str(state))
            second = self._run(app, "--once", "--state", str(state))
        self.assertEqual(first.returncode, 1, first.stdout)
        self.assertEqual(second.returncode, 1,
                         "a leak that is still there must still exit 1:\n" + second.stdout)
        self.assertEqual(first.stdout.count("NEW "), 1)
        self.assertEqual(second.stdout.count("NEW "), 0, "the repeat alert must be suppressed")

    # W7 -------------------------------------------------------------------
    def test_w7_prefilter_is_sound_and_agrees_with_the_check(self):
        prefixes = watch.prefilter_prefixes(cads.PATTERNS)
        self.assertIsNotNone(prefixes, "every audited pattern must yield a literal prefix")
        self.assertEqual(len(prefixes), len(cads.PATTERNS))
        for name, pat in cads.PATTERNS:
            prefix = watch.literal_prefix(pat.pattern)
            self.assertTrue(prefix, f"{name} lost its literal prefix")
            self.assertIsNotNone(pat.search(prefix + "A" * 40),
                                 f"{name}: derived prefix {prefix!r} must begin a real match")

        text = f"nothing to see {PARTIAL} plus {FAKE} and {FAKE_ANTHROPIC}"
        self.assertFalse(watch.prefilter_hit("no shapes here at all", prefixes))
        self.assertTrue(watch.prefilter_hit(text, prefixes))

        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": text.encode()})
            store = app / "projects" / "p1" / "desktop-v2.db"
            mine = watch.scan_text(store.read_bytes().decode("latin-1"), prefixes)
            theirs = cads.scan_store(store)
        self.assertEqual(sorted(mine), sorted(theirs),
                         "the prefilter path must return exactly what the check returns")
        self.assertNotEqual(PARTIAL, FAKE, "the truncated prefix is a different string")
        classes = {n for n, _o, _d in mine}
        self.assertIn("github-pat-fine-grained", classes)
        self.assertIn("anthropic-key", classes)

    def test_w7b_unprovable_pattern_set_disables_the_prefilter(self):
        import re
        class P:  # a compiled pattern whose literal prefix cannot be derived
            def __init__(self, src): self.pattern = src
        synthetic = [("alt", P("(ghp_|gho_)[A-Za-z0-9]{36}")),
                     ("ci-flag", P("(?i)token=[a-z0-9]{10,}")),
                     ("escape-class", P(r"\d{10,}"))]
        for _name, pat in synthetic:
            self.assertIsNone(watch.literal_prefix(pat.pattern),
                              "an unprovable pattern must return None")
        self.assertIsNone(watch.prefilter_prefixes(synthetic))
        self.assertTrue(watch.prefilter_hit("text with no prefixes", None),
                        "a disabled prefilter must always allow the regex pass")

    # W8 -------------------------------------------------------------------
    def test_w8_unreadable_store_fails_the_pass_closed(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {})
            (app / "projects" / "p1" / "desktop-v2.db").mkdir()   # a store that cannot be read
            r = self._run(app, "--once", "--state", str(Path(td) / "s.json"))
        self.assertEqual(r.returncode, 2,
                         "an unscannable store must not read as clean:\n" + r.stdout + r.stderr)
        self.assertIn("WARN", r.stdout)

    def test_w8b_oversized_store_is_incomplete_not_clean(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"x" * 64})
            # a tiny cap stands in for the 512 MB case, so the fixture stays hermetic
            r = self._run(app, "--once", "--max-bytes", "8",
                          "--state", str(Path(td) / "s.json"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("exceeds the 8-byte scan cap", r.stdout + r.stderr)

    # W9 -------------------------------------------------------------------
    def test_w9_malformed_baseline_is_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            app = self._clean_app(td)
            baseline = Path(td) / "b.json"
            baseline.write_text("{ not json")
            r = self._run(app, "--once", "--baseline", str(baseline),
                          "--state", str(Path(td) / "s.json"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # W10 ------------------------------------------------------------------
    def test_w10_on_new_receives_the_digest_not_the_value(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"x " + FAKE.encode()})
            capture = Path(td) / "captured.txt"
            helper = Path(td) / "capture.py"
            helper.write_text("import os, sys\n"
                              "env = os.environ\n"
                              "open(sys.argv[1], 'w').write("
                              "env.get('WATCH_DIGEST', '') + '\\n' + env.get('WATCH_CLASS', ''))\n")
            r = self._run(app, "--once", "--state", str(Path(td) / "s.json"),
                          "--on-new", f'{sys.executable} {helper} {capture}')
            captured = capture.read_text()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(hashlib.sha256(FAKE.encode()).hexdigest(), captured)
        self.assertIn("github-pat-fine-grained", captured)
        self.assertNotIn(FAKE, captured, "the notifier must receive a digest, never the value")

    # W11 ------------------------------------------------------------------
    def test_w11_scan_policy_is_pure_and_correct(self):
        # never scanned, quiet long enough -> the startup pass
        self.assertEqual(watch.due_reason(now=100.0, last_scan=None, changed=False,
                                          quiet_for=3.0, debounce=3.0, heartbeat=600.0),
                         "startup")
        # never scanned, still inside the debounce window -> wait
        self.assertIsNone(watch.due_reason(now=100.0, last_scan=None, changed=False,
                                           quiet_for=1.0, debounce=3.0, heartbeat=600.0))
        # no change yet, quiet long enough -> idle
        self.assertIsNone(watch.due_reason(now=100.0, last_scan=99.0, changed=False,
                                           quiet_for=0.0, debounce=3.0, heartbeat=600.0))
        # a change, but still inside the debounce window -> wait
        self.assertIsNone(watch.due_reason(now=100.0, last_scan=99.0, changed=True,
                                           quiet_for=1.0, debounce=3.0, heartbeat=600.0))
        # a change, quiet past the debounce -> scan
        self.assertEqual(watch.due_reason(now=100.0, last_scan=99.0, changed=True,
                                          quiet_for=3.0, debounce=3.0, heartbeat=600.0),
                         "changed")
        # nothing changed for longer than the heartbeat -> scan anyway
        self.assertEqual(watch.due_reason(now=100.0, last_scan=10.0, changed=False,
                                          quiet_for=90.0, debounce=3.0, heartbeat=60.0),
                         "heartbeat")
        # heartbeat disabled, nothing changed -> never scan
        self.assertIsNone(watch.due_reason(now=100.0, last_scan=10.0, changed=False,
                                           quiet_for=90.0, debounce=3.0, heartbeat=0.0))

    def test_w11b_signature_is_stat_only_and_tolerant(self):
        with tempfile.TemporaryDirectory() as td:
            app = make_app(Path(td), {"desktop-v2.db": b"abc"})
            store = app / "projects" / "p1" / "desktop-v2.db"
            sig = watch.store_signature([store, Path(td) / "gone.db"])
        self.assertEqual(sig[str(store)][0], 3)
        self.assertGreater(sig[str(store)][1], 0)
        self.assertEqual(sig[str(Path(td) / "gone.db")], [-1, -1],
                         "a missing store is a state, not an exception")


if __name__ == "__main__":
    unittest.main(verbosity=2)
