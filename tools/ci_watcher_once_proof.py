#!/usr/bin/env python3
"""CI proof: the watcher's --once path end-to-end against a synthetic store.

Builds a throwaway Freebuff app dir holding a synthetic `desktop-v2.db` with
concat-built fake tokens, runs `watch_app_db_secrets.py --once` against it
with an empty baseline and temp state, and asserts the continuous path fires:
exit 1, classes named, digests shown, values never echoed or stored. Then a
clean store must exit 0. All fixtures are assembled at runtime — this tracked
file holds no full-pattern literal.

Runs in CI on every PR (see .github/workflows/regression-gate.yml) and locally:
    python tools/ci_watcher_once_proof.py
Exit 0 = proven; 1 = proof failed.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "watch_app_db_secrets.py"

FAKE_FG = "github_pat_" + "A1b2C3d4E5" * 6
FAKE_ANTHROPIC = "sk-ant-" + "fake0123456789" + "abcdef0123"


def fail(msg: str) -> int:
    print(f"watcher-once-proof: FAIL — {msg}")
    return 1


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        proj = root / ".config" / "freebuff-desktop" / "projects" / "synth"
        proj.mkdir(parents=True)
        (proj / "desktop-v2.db").write_bytes(
            b"synthetic transcript before " + FAKE_FG.encode()
            + b" middle " + FAKE_ANTHROPIC.encode() + b" after")
        baseline = root / "baseline.json"
        baseline.write_text(json.dumps({"digests": {}}), encoding="utf-8")
        state = root / "state.json"
        log = root / "watch.log"
        r = subprocess.run(
            [sys.executable, str(TOOL), "--once", "--db-dir", str(root / ".config" / "freebuff-desktop"),
             "--baseline", str(baseline), "--state", str(state), "--log", str(log)],
            capture_output=True, text=True, timeout=120, cwd=str(REPO))
        blob = r.stdout + r.stderr + state.read_text(encoding="utf-8") + log.read_text(encoding="utf-8")
        if r.returncode != 1:
            return fail(f"dirty store exited {r.returncode}, want 1\n{r.stdout}\n{r.stderr}")
        for needle in ("NEW github-pat-fine-grained", "NEW anthropic-key",
                       hashlib.sha256(FAKE_FG.encode()).hexdigest()[:16]):
            if needle not in r.stdout:
                return fail(f"missing {needle!r} in --once output\n{r.stdout}")
        for value in (FAKE_FG, FAKE_ANTHROPIC):
            if value in blob:
                return fail("the proof leaked a fake value into output/state/log")
        (proj / "desktop-v2.db").write_bytes(b"synthetic transcript, nothing shaped")
        r2 = subprocess.run(
            [sys.executable, str(TOOL), "--once", "--db-dir", str(root / ".config" / "freebuff-desktop"),
             "--baseline", str(baseline), "--state", str(root / "state2.json")],
            capture_output=True, text=True, timeout=120, cwd=str(REPO))
        if r2.returncode != 0:
            return fail(f"clean store exited {r2.returncode}, want 0\n{r2.stdout}\n{r2.stderr}")
        if "NEW " in r2.stdout:
            return fail("clean store reported NEW hits")
    print("watcher-once-proof: PASS (dirty alerted exit 1 with digests only; clean silent exit 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
