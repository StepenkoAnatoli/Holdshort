#!/usr/bin/env python3
"""Tests for tools/check_provenance.py — the isolation-provenance check.

  P1. a branch that matches sr/<id>/<slug> and touches only permitted prefixes PROVES
  P2. a file outside permitted-effects is a VIOLATION naming the offender (exit 1)
  P3. a wrongly named branch is a VIOLATION even when the diff is in scope
  P4. an invalid task id is a VIOLATION, not a crash
  P5. a missing branch fails CLOSED (exit 2) — absence is never "clean"
  P6. a rebased base (base not an ancestor) is a VIOLATION — diff re-homing caught
  P7. --worktree verifies the live checkout binding; a stale path is a VIOLATION
Run as part of the regression gate (tools/run_regression.py). Throwaway repos,
isolated git config, no network.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_provenance.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cp = _load("cprov", TOOL)

TASK = "a3f9c1d2"
BRANCH = "sr/a3f9c1d2/auth-refactor"


def _env(tmp: Path) -> dict:
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


class Provenance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.env = _env(self.tmp)
        self.repo = self.tmp / "repo"
        _git(self.tmp, "init", "-q", "-b", "main", str(self.repo), env=self.env)
        _git(self.repo, "config", "user.email", "t@t", env=self.env)
        _git(self.repo, "config", "user.name", "t", env=self.env)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "keep.py").write_text("base\n")
        _git(self.repo, "add", ".", env=self.env)
        _git(self.repo, "commit", "-qm", "seed", env=self.env)
        self.wt = self.tmp / "wt"
        _git(self.repo, "worktree", "add", "-b", BRANCH, str(self.wt), "main", env=self.env)

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, rel: str, body: str = "change\n"):
        p = self.wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        _git(self.wt, "add", ".", env=self.env)
        _git(self.wt, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "work", env=self.env)

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), "--repo", str(self.repo),
                               "--task-id", TASK, "--branch", BRANCH, *extra],
                              capture_output=True, text=True, timeout=120)

    # P1 ----------------------------------------------------------------------
    def test_p1_in_scope_proves(self):
        self._commit("src/keep.py", "base\nchange\n")
        r = self._run("--permitted", "src/")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PROVED", r.stdout)
        self.assertIn("src/keep.py", r.stdout)

    # P2 ----------------------------------------------------------------------
    def test_p2_out_of_scope_is_violation(self):
        self._commit("src/keep.py", "base\nchange\n")
        (self.wt / "billing.py").write_text("oops\n")
        _git(self.wt, "add", ".", env=self.env)
        _git(self.wt, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "scope creep", env=self.env)
        r = self._run("--permitted", "src/")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("billing.py", r.stderr)

    # P3 ----------------------------------------------------------------------
    def test_p3_wrong_branch_name_is_violation(self):
        self._commit("src/keep.py", "base\nchange\n")
        r = subprocess.run([sys.executable, str(TOOL), "--repo", str(self.repo),
                            "--task-id", TASK, "--branch", "feature/stuff",
                            "--permitted", "src/"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("VIOLATION", r.stderr)

    # P4 ----------------------------------------------------------------------
    def test_p4_invalid_task_id_is_violation(self):
        r = subprocess.run([sys.executable, str(TOOL), "--repo", str(self.repo),
                            "--task-id", "NOTHEX!!", "--branch", BRANCH,
                            "--permitted", "src/"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 1)
        self.assertIn("VIOLATION", r.stderr)

    # P5 ----------------------------------------------------------------------
    def test_p5_missing_branch_fails_closed(self):
        r = subprocess.run([sys.executable, str(TOOL), "--repo", str(self.repo),
                            "--task-id", TASK, "--branch", "sr/a3f9c1d2/ghost",
                            "--permitted", "src/"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # P6 ----------------------------------------------------------------------
    def test_p6_rehomed_base_is_violation(self):
        self._commit("src/keep.py", "base\nchange\n")
        _git(self.repo, "checkout", "-qb", "other-base", env=self.env)
        (self.repo / "unrelated.txt").write_text("x\n")
        _git(self.repo, "add", ".", env=self.env)
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "other", env=self.env)
        r = self._run("--permitted", "src/", "--base", "other-base")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ancestor", r.stderr)

    # P7 ----------------------------------------------------------------------
    def test_p7_worktree_binding_checked(self):
        self._commit("src/keep.py", "base\nchange\n")
        r = self._run("--permitted", "src/", "--worktree", str(self.wt))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        stale = self._run("--permitted", "src/", "--worktree", str(self.tmp / "nope"))
        self.assertEqual(stale.returncode, 1)
        self.assertIn("VIOLATION", stale.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
