#!/usr/bin/env python3
"""Tests for tools/check_skill_adherence.py (G2).

A1. pin passes on the current tree (12 normative sentences present).
A2. pin detects a softened skill (simulated breach fails, original intact).
A3. sample/score round-trips: perfect answers score 1.0, wrong answers fail.
A4. score of a missing results file fails closed (exit 2), never "agreement 0".
Stdlib only, no network, no model calls — the model-graded run itself stays
PENDING (see --sample); this suite proves the harness, not the grading.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sa = _load("ska", TOOLS / "check_skill_adherence.py")

failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failures
    if cond:
        print(f"PASS {name}")
    else:
        failures += 1
        print(f"FAIL {name} {detail}")


# A1 pin on the real tree -------------------------------------------------------
check("A1 pin clean", sa.cmd_pin() == 0)

# A2 breach detection (monkeypatched read) --------------------------------------
_real = Path.read_text


def soft(path, *a, **k):
    t = _real(path, *a, **k)
    return t.replace("never resurrect a candidate rejected at any gate", "usually prefer eligible candidates")


Path.read_text = soft  # type: ignore[method-assign]
try:
    check("A2 softening detected", sa.cmd_pin() == 1)
finally:
    Path.read_text = _real  # type: ignore[method-assign]
check("A2 tree intact after test", sa.cmd_pin() == 0)

# A3 sample/score round-trip ------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    out = tmp / "vign.json"
    check("A3 sample emits", sa.cmd_sample(out, 6) == 0 and out.is_file())
    perfect = {"answers": [{"id": v["id"], "route": v["expected_route"]} for v in sa.VIGNETTES]}
    rp = tmp / "perfect.json"
    rp.write_text(json.dumps(perfect), encoding="utf-8")
    check("A3 perfect scores 1.0", sa.cmd_score(rp, 1.0) == 0)
    wrong = {"answers": [{"id": v["id"], "route": "direct"} for v in sa.VIGNETTES]}
    rw = tmp / "wrong.json"
    rw.write_text(json.dumps(wrong), encoding="utf-8")
    check("A3 wrong fails floor", sa.cmd_score(rw, 1.0) == 1)
    for malformed in ([], {"answers": [None]}, {"answers": [{"id": []}]},
                      {"answers": [perfect["answers"][0]] * 2}):
        rw.write_text(json.dumps(malformed), encoding="utf-8")
        check("A3 malformed results refused", sa.cmd_score(rw, 1.0) == 2)
    check("A3 nonfinite floor refused", sa.cmd_score(rp, float("nan")) == 2)

# A4 missing results fail closed ----------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    check("A4 missing results exit 2", sa.cmd_score(Path(td) / "ghost.json", 1.0) == 2)

print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
sys.exit(0 if failures == 0 else 1)
