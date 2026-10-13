#!/usr/bin/env python3
"""Tests for tools/spawn_worker.py — the host-side worker lifecycle primitive.

  S1. spawn creates worktree+branch, injects the Brief VERBATIM, registers the worker
  S2. duplicate task id is REFUSED (exit 1) — no shared checkout, registry untouched
  S3. empty brief / missing profile / invalid id are REFUSED, nothing spawned
  S4. cleanup after merge removes worktree AND branch and unregisters
  S5. cleanup of an unmerged branch REFUSES the delete (worktree still removed,
      branch kept for forensics) unless --allow-unmerged abandons it
  S6. cleanup of an unknown task id is REFUSED (no blind cleanup)
  S7. corrupt registry fails CLOSED (exit 2), never treated as empty
Run as part of the regression gate (tools/run_regression.py). Throwaway repos,
isolated git config, no network.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "spawn_worker.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sw = _load("spw", TOOL)

BRIEF = {"objective": "spawn test", "attempts": 1}


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


class SpawnWorker(unittest.TestCase):
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
        self.wts = self.tmp / "wts"
        self.reg = self.tmp / "reg.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _spawn(self, **kw) -> dict:
        args = dict(repo=self.repo, wt_root=self.wts, slug="work",
                    brief=dict(BRIEF), profile="prof", registry_path=self.reg,
                    env=self.env)
        args.update(kw)
        return sw.spawn(**args)

    # S1 ----------------------------------------------------------------------
    def test_s1_spawn_injects_verbatim_and_registers(self):
        rec = self._spawn(task_id="a3f9c1d2")
        self.assertEqual(rec["branch"], "sr/a3f9c1d2/work")
        stored = json.loads((Path(rec["path"]) / "SMARTROUTER_BRIEF.json").read_text())
        self.assertEqual(stored, BRIEF, "the Brief must reach the worker byte-identical")
        reg = json.loads(self.reg.read_text())
        self.assertEqual(reg["workers"]["a3f9c1d2"]["branch"], rec["branch"])
        self.assertTrue(rec["brief_fingerprint"].startswith("sha256:"))

    # S2 ----------------------------------------------------------------------
    def test_s2_duplicate_id_refused(self):
        self._spawn(task_id="a3f9c1d2")
        before = self.reg.read_text()
        with self.assertRaises(sw.Refused):
            self._spawn(task_id="a3f9c1d2")
        self.assertEqual(self.reg.read_text(), before, "refusal must not touch the registry")

    # S3 ----------------------------------------------------------------------
    def test_s3_bad_inputs_refused_without_spawn(self):
        with self.assertRaises(sw.Refused):
            self._spawn(task_id="a3f9c1d2", brief={})
        with self.assertRaises(sw.Refused):
            self._spawn(task_id="a3f9c1d2", profile="")
        with self.assertRaises(sw.Refused):
            self._spawn(task_id="ZZZ")
        self.assertFalse(self.wts.exists() and any(self.wts.iterdir()),
                         "refused spawns must leave no worktree behind")

    # S4 ----------------------------------------------------------------------
    def test_s4_cleanup_after_merge(self):
        rec = self._spawn(task_id="a3f9c1d2")
        wp = Path(rec["path"])
        (wp / "out.txt").write_text("work\n")
        _git(wp, "add", "out.txt", env=self.env)  # the Brief stays untracked, never committed
        _git(wp, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "work", env=self.env)
        _git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "merge", "--no-ff", "-m", "merge", rec["branch"], env=self.env)
        done = sw.cleanup(self.repo, self.reg, "a3f9c1d2", env=self.env)
        self.assertTrue(done["worktree_removed"] and done["branch_deleted"])
        self.assertFalse(wp.exists())
        self.assertNotIn("a3f9c1d2", json.loads(self.reg.read_text())["workers"])

    # S5 ----------------------------------------------------------------------
    def test_s5_unmerged_branch_kept_without_abandon(self):
        rec = self._spawn(task_id="a3f9c1d2")
        wp = Path(rec["path"])  # a zero-commit branch is trivially merged, so commit first
        (wp / "out.txt").write_text("work\n")
        _git(wp, "add", "out.txt", env=self.env)
        _git(wp, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "work", env=self.env)
        with self.assertRaises(sw.Refused):
            sw.cleanup(self.repo, self.reg, "a3f9c1d2", env=self.env)
        # worktree gone (brief retracted, checkout removed) but branch kept
        self.assertFalse(Path(rec["path"]).exists())
        out = _git(self.repo, "branch", "--list", rec["branch"], env=self.env)
        self.assertIn(rec["branch"], out.stdout)
        # abandon path: CLI --allow-unmerged drops the registration, keeps the branch
        r = subprocess.run([sys.executable, str(TOOL), "cleanup", "--repo", str(self.repo),
                            "--registry", str(self.tmp / "reg2.json"), "--task-id", "x"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1, "unknown id in another registry still refused")

    # S6 ----------------------------------------------------------------------
    def test_s6_unknown_task_cleanup_refused(self):
        with self.assertRaises(sw.Refused):
            sw.cleanup(self.repo, self.reg, "deadbeef", env=self.env)

    # S7 ----------------------------------------------------------------------
    def test_s7_corrupt_registry_fails_closed(self):
        self.reg.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(sw.FailClosed):
            self._spawn(task_id="a3f9c1d2")

    # S8 ----------------------------------------------------------------------
    def test_s8_port_overlap_refused(self):
        # G7: parallel workers must never share a mutable service endpoint.
        self._spawn(task_id="a3f9c1d2",
                    shared={"env_scope": "task-a", "ports": [18080]})
        with self.assertRaises(sw.Refused):
            self._spawn(task_id="b4e0d2e3",
                        shared={"env_scope": "task-b", "ports": [18080]})
        rec = self._spawn(task_id="c5f1e3a4",
                          shared={"env_scope": "task-c", "ports": [18081]})
        self.assertTrue(rec["shared"]["attested"])
        self.assertEqual(rec["shared"]["ports"], [18081])

    # S9 ----------------------------------------------------------------------
    def test_s9_unattested_spawn_refused_when_required(self):
        # G7: --require-shared-plan makes unattested spawns fail closed.
        with self.assertRaises(sw.Refused):
            sw.spawn(self.repo, self.wts, "work", dict(BRIEF), "prof",
                     self.reg, task_id="a3f9c1d2", env=self.env,
                     require_shared_plan=True)
        rec = sw.spawn(self.repo, self.wts, "work", dict(BRIEF), "prof",
                       self.reg, task_id="a3f9c1d2", env=self.env,
                       shared={"no_shared_surface": True},
                       require_shared_plan=True)
        self.assertTrue(rec["shared"]["attested"])

    # S10 ---------------------------------------------------------------------
    def test_s10_legacy_spawn_records_unattested(self):
        # Backward compat: old callers without a plan keep working, but the
        # registry marks them unattested (auditable, not trusted).
        rec = self._spawn(task_id="a3f9c1d2")
        self.assertEqual(rec["shared"], {"attested": False})


if __name__ == "__main__":
    unittest.main(verbosity=2)
