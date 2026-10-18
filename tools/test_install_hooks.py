#!/usr/bin/env python3
"""Regression tests for the machine-onboarding path (tools/install_hooks.py).

Pins the contract that makes "fresh clone enforces by default" true:
  1. install_hooks sets core.hooksPath LOCALLY to .githooks (repo-local config;
     global config must never be touched or relied on),
  2. it refuses to claim success on a missing tracked hook (no silent no-op),
  3. it refuses on a hook that doesn't even parse (broken wiring must not
     masquerade as enforcement),
  4. the effective hooksPath afterwards really is .githooks,
  5. it refuses cleanly (a message, not a traceback) when `bash` is absent,
     because the tracked gate is a bash script that cannot run without it.

Run as part of the regression gate (tools/run_regression.py). Uses a throwaway
git clone + isolated env so the developer's own repo/global config is never
mutated.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent


def _load_module():
    spec = importlib.util.spec_from_file_location("ih", TOOLS / "install_hooks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fresh_clone(bare_src: Path) -> dict:
    """Clone REPO into a temp dir with fully isolated config; return handles."""
    tmp = Path(tempfile.mkdtemp())
    dst = tmp / "clone"
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(tmp / "gitconfig")   # isolation: no user gitconfig
    empty = tmp / "empty-gitconfig"                       # an empty file, as the other tests isolate:
    empty.write_text("", encoding="utf-8")                # os.devnull is only a config file while it is a device
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    subprocess.run(["git", "clone", "-q", str(bare_src), str(dst)], env=env, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=dst, env=env, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=dst, env=env, check=True)
    return {"tmp": tmp, "dst": dst, "env": env}


class OnboardingPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Build a bare clone of the repo once (no network; local object copy)."""
        cls.bare = Path(tempfile.mkdtemp()) / "src.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(REPO), str(cls.bare)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.bare.parent, ignore_errors=True)

    def test_sets_local_hooks_path_and_verifies_effective_value(self):
        ih = _load_module()
        c = _fresh_clone(self.bare)
        try:
            # wire the CLONE (the module's REPO_ROOT repointed), like the refusal
            # tests do — otherwise install_hooks wires THIS dev repo.
            orig = ih.REPO_ROOT
            ih.REPO_ROOT = c["dst"]
            ih.HOOK = c["dst"] / ".githooks" / "pre-commit"
            try:
                rc = ih.main()
            finally:
                ih.REPO_ROOT, ih.HOOK = orig, ih.HOOK
            self.assertEqual(rc, 0, "install_hooks must succeed on a fresh clone")
            configured = subprocess.run(
                ["git", "config", "--get", "core.hooksPath"],
                cwd=c["dst"], env=c["env"], capture_output=True, text=True, check=True
            ).stdout.strip()
            self.assertEqual(configured.replace("\\", "/").rstrip("/"), ".githooks",
                             "repo-local hooksPath must be .githooks after onboarding")
            # the hook must exist at the wired path and be executable
            hook = c["dst"] / ".githooks" / "pre-commit"
            self.assertTrue(hook.is_file(), "tracked hook must exist in the clone")
            self.assertTrue(os.access(hook, os.X_OK) or sys.platform == "win32",
                            "hook must carry an executable bit (Linux gate skipped silently otherwise)")
        finally:
            shutil.rmtree(c["tmp"], ignore_errors=True)

    def test_refuses_on_missing_hook_file(self):
        c = _fresh_clone(self.bare)
        try:
            (c["dst"] / ".githooks" / "pre-commit").unlink()
            ih = _load_module()
            # point the module at the clone, not this dev repo
            orig = ih.REPO_ROOT
            ih.REPO_ROOT = c["dst"]
            ih.HOOK = c["dst"] / ".githooks" / "pre-commit"
            try:
                rc = ih.main()
            finally:
                ih.REPO_ROOT, ih.HOOK = orig, ih.HOOK
            self.assertEqual(rc, 1, "missing hook must be a refusal (exit 1), not silent success")
            configured = subprocess.run(
                ["git", "config", "core.hooksPath"], cwd=c["dst"], env=c["env"],
                capture_output=True, text=True)
            self.assertNotEqual(configured.stdout.strip().replace("\\", "/"), ".githooks",
                                "refusal must not leave the repo claiming to be wired")
        finally:
            shutil.rmtree(c["tmp"], ignore_errors=True)

    def test_refuses_on_unparseable_hook(self):
        c = _fresh_clone(self.bare)
        try:
            hook = c["dst"] / ".githooks" / "pre-commit"
            hook.write_text("fi fi ( ( syntax garbage", encoding="utf-8")
            ih = _load_module()
            orig = ih.REPO_ROOT
            ih.REPO_ROOT = c["dst"]
            ih.HOOK = hook
            try:
                rc = ih.main()
            finally:
                ih.REPO_ROOT = orig
            self.assertEqual(rc, 1, "a hook that fails bash -n must abort wiring (exit 1)")
        finally:
            shutil.rmtree(c["tmp"], ignore_errors=True)

    def test_refuses_cleanly_when_bash_is_absent(self):
        c = _fresh_clone(self.bare)
        try:
            ih = _load_module()
            orig = ih.REPO_ROOT
            ih.REPO_ROOT = c["dst"]
            ih.HOOK = c["dst"] / ".githooks" / "pre-commit"
            real_run = subprocess.run

            def fake_run(cmd, *args, **kwargs):
                # Simulate a Windows box with no bash on PATH: the syntax probe
                # raises FileNotFoundError, exactly as subprocess does there.
                if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "bash":
                    raise FileNotFoundError(2, "No such file or directory", "bash")
                return real_run(cmd, *args, **kwargs)

            err = io.StringIO()
            try:
                with mock.patch.object(ih.subprocess, "run", side_effect=fake_run):
                    with redirect_stderr(err):
                        rc = ih.main()
            finally:
                ih.REPO_ROOT, ih.HOOK = orig, ih.HOOK
            self.assertEqual(rc, 1, "missing bash must be a clean refusal (exit 1), not a crash")
            self.assertIn("bash", err.getvalue(),
                          "the refusal must name the missing shell, not emit a traceback")
        finally:
            shutil.rmtree(c["tmp"], ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
