#!/usr/bin/env python3
"""Tests for tools/task_ids.py — the task-id semantics the companions imply.

  T1. format: `a3f9` valid; uppercase / non-hex / too-short / too-long refused
  T2. minting uses secrets entropy, default 8 hex chars, even-length 4..16 enforced
  T3. derivation: branch `sr/<id>/<slug>`, slug sanitization, invalid id refused
  T4. uniqueness: ensure_unique avoids the taken set; exhausts fail-closed
  T5. collect_taken sees live worktrees and sr/<id>/ branches in a temp repo
  T6. CLI: --validate / --branch / --mint contracts
Run as part of the regression gate (tools/run_regression.py).
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "task_ids.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ti = _load("tids", TOOL)


def _isolated_env(tmp: Path) -> dict:
    empty = tmp / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(cwd: Path, *args: str, env: dict):
    proc = subprocess.run(["git", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stdout}{proc.stderr}")
    return proc


class TaskIds(unittest.TestCase):

    # T1 ----------------------------------------------------------------------
    def test_t1_format(self):
        self.assertTrue(ti.valid("a3f9"), "the companions' example must validate")
        for bad in ("A3F9", "a3f9!", "a3", "xyz", "", "a" * 3, "b" * 17, "sr/a3f9/x", "a3f9 "):
            self.assertFalse(ti.valid(bad), f"{bad!r} must be refused")

    # T2 ----------------------------------------------------------------------
    def test_t2_mint_defaults_and_bounds(self):
        seen = {ti.mint() for _ in range(50)}
        self.assertGreater(len(seen), 40, "mints must vary (secrets entropy)")
        for m in seen:
            self.assertTrue(re.fullmatch(r"[0-9a-f]{8}", m), m)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{4}", ti.mint(4)))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{16}", ti.mint(16)))
        for bad in (2, 3, 5, 17, 18):
            with self.assertRaises(ValueError):
                ti.mint(bad)

    # T3 ----------------------------------------------------------------------
    def test_t3_derivation(self):
        self.assertEqual(ti.branch_for("a3f9", "Auth Refactor!!"), "sr/a3f9/auth-refactor")
        self.assertEqual(ti.branch_for("a3f9", "caching-layer"), "sr/a3f9/caching-layer")
        with self.assertRaises(ValueError):
            ti.branch_for("NOTHEX!!", "x")
        main = Path("/repo/main")
        self.assertEqual(ti.worktree_path_outside(main, "a3f9"),
                         Path("/repo/.sr-worktrees/a3f9"))

    # T4 ----------------------------------------------------------------------
    def test_t4_uniqueness_and_fail_closed(self):
        got = ti.ensure_unique({"a3f9"}, 4)
        self.assertNotEqual(got, "a3f9")
        self.assertTrue(ti.valid(got))
        # Exhaustion is infeasible to enumerate (65k 4-hex ids), so force it by
        # monkey-minting a constant already in the taken set: every retry
        # collides and the scope fails closed instead of reusing the id.
        orig = ti.mint
        ti.mint = lambda n=8: "a3f9"  # noqa: E731 — deterministic-collision fixture
        try:
            with self.assertRaises(ti.ScopeUnreachable):
                ti.ensure_unique({"a3f9"}, 4, retries=3)
        finally:
            ti.mint = orig

    # T5 ----------------------------------------------------------------------
    def test_t5_collect_taken_sees_live_state(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = _isolated_env(tmp)
            repo = tmp / "repo"
            _git(tmp, "init", "-q", "-b", "main", str(repo), env=env)
            _git(repo, "config", "user.email", "t@t", env=env)
            _git(repo, "config", "user.name", "t", env=env)
            (repo / "f.txt").write_text("x")
            _git(repo, "add", ".", env=env)
            _git(repo, "commit", "-qm", "init", env=env)
            _git(repo, "worktree", "add", "-b", "sr/a3f9/auth-refactor",
                 str(tmp / ".sr-worktrees" / "a3f9"), env=env)
            taken = ti.collect_taken(repo, {"99aa"}, {"77bb"})
            self.assertIn("a3f9", taken)
            self.assertIn("99aa", taken)
            self.assertIn("77bb", taken)

    # T6 ----------------------------------------------------------------------
    def test_t6_cli_contracts(self):
        v = subprocess.run([sys.executable, str(TOOL), "--validate", "a3f9"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(v.returncode, 0)
        self.assertIn("valid", v.stdout)
        v2 = subprocess.run([sys.executable, str(TOOL), "--validate", "ZZZ"],
                            capture_output=True, text=True, timeout=60)
        self.assertEqual(v2.returncode, 1)
        b = subprocess.run([sys.executable, str(TOOL), "--branch", "a3f9", "Auth Refactor!!"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(b.stdout.strip(), "sr/a3f9/auth-refactor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
