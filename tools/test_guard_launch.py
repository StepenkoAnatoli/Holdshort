#!/usr/bin/env python3
"""Tests for tools/guard_launch.py — the pre-launch worktree guard.

  G1. launching in the MAIN checkout with worktree+branch is REFUSED (exit 1)
  G2. a directory inside no worktree at all is REFUSED (bare /tmp landing)
  G3. the dedicated linked worktree is ALLOWED, with task/branch binding checked
  G4. right worktree area but wrong task branch is REFUSED
  G5. non-worktree isolation (`none`) launches in place by design (exit 0)
  G6. unreadable repo fails CLOSED (exit 2), never "allowed"
  G7. task-id without branch (or garbage id) is REFUSED, not half-checked
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
TOOL = REPO / "tools" / "guard_launch.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gl = _load("gdl", TOOL)

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


class GuardLaunch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.env = _env(self.tmp)
        self.repo = self.tmp / "repo"
        _git(self.tmp, "init", "-q", "-b", "main", str(self.repo), env=self.env)
        _git(self.repo, "config", "user.email", "t@t", env=self.env)
        _git(self.repo, "config", "user.name", "t", env=self.env)
        (self.repo / "f.txt").write_text("seed\n")
        _git(self.repo, "add", ".", env=self.env)
        _git(self.repo, "commit", "-qm", "seed", env=self.env)
        self.wt = self.tmp / "wt"
        _git(self.repo, "worktree", "add", "-b", BRANCH, str(self.wt), "main", env=self.env)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), *extra],
                              capture_output=True, text=True, timeout=120, env=self.env)

    def _base(self, d: Path, iso: str = "worktree+branch") -> list[str]:
        return ["--repo", str(self.repo), "--dir", str(d), "--isolation", iso]

    # G1 ----------------------------------------------------------------------
    def test_g1_main_checkout_refused(self):
        r = self._run(*self._base(self.repo))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("main checkout", r.stderr)

    # G2 ----------------------------------------------------------------------
    def test_g2_bare_directory_refused(self):
        bare = self.tmp / "landing"
        bare.mkdir()
        r = self._run(*self._base(bare))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no git worktree", r.stderr)

    # G3 ----------------------------------------------------------------------
    def test_g3_dedicated_worktree_allowed(self):
        r = self._run(*self._base(self.wt), "--task-id", TASK, "--branch", BRANCH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALLOWED", r.stdout)

    # G4 ----------------------------------------------------------------------
    def test_g4_wrong_task_branch_refused(self):
        r = self._run(*self._base(self.wt), "--task-id", TASK,
                      "--branch", "sr/a3f9c1d2/other-work")
        self.assertEqual(r.returncode, 1)
        self.assertIn("wrong task", r.stderr)

    # G5 ----------------------------------------------------------------------
    def test_g5_none_isolation_launches_in_place(self):
        r = self._run(*self._base(self.repo, "none"))
        self.assertEqual(r.returncode, 0)

    # G6 ----------------------------------------------------------------------
    def test_g6_unreadable_repo_fails_closed(self):
        r = self._run("--repo", str(self.tmp / "ghost"), "--dir", str(self.wt),
                      "--isolation", "worktree+branch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("FAIL-CLOSED", r.stderr)

    # G8 ----------------------------------------------------------------------
    def test_g8_unattested_launch_refused_when_required(self):
        import json
        reg = self.tmp / "reg.json"
        reg.write_text(json.dumps({"workers": {TASK: {
            "path": str(self.wt), "branch": BRANCH, "profile": "p",
            "shared": {"attested": False}}}}), encoding="utf-8")
        r = self._run(*self._base(self.wt), "--task-id", TASK,
                      "--branch", BRANCH, "--registry", str(reg),
                      "--require-shared-plan")
        self.assertEqual(r.returncode, 1)
        self.assertIn("shared-surface", r.stderr)
        reg.write_text(json.dumps({"workers": {TASK: {
            "path": str(self.wt), "branch": BRANCH, "profile": "p",
            "shared": {"attested": True, "no_shared_surface": True}}}}),
            encoding="utf-8")
        r2 = self._run(*self._base(self.wt), "--task-id", TASK,
                       "--branch", BRANCH, "--registry", str(reg),
                       "--require-shared-plan")
        self.assertEqual(r2.returncode, 0)

    # G7 ----------------------------------------------------------------------
    def test_g7_half_binding_refused(self):
        r = self._run(*self._base(self.wt), "--task-id", TASK)
        self.assertEqual(r.returncode, 1)
        r2 = self._run(*self._base(self.wt), "--task-id", "ZZZ",
                       "--branch", "sr/ZZZ/x")
        self.assertEqual(r2.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
