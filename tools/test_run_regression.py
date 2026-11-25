#!/usr/bin/env python3
"""Tests for tools/run_regression.py: each check runs without the caller's `git -c` settings.

`git -c name=value commit` puts the setting in GIT_CONFIG_PARAMETERS (newer Git can also
use GIT_CONFIG_COUNT with GIT_CONFIG_KEY_<n> and GIT_CONFIG_VALUE_<n>). The pre-commit hook
inherits it, so the gate and every git process its checks start would read it as config.
tools/setup_machine.sh makes its proof commits that way. Inside the hook, the identity it
passed reached tools/test_install_hooks.py, which then read "setup-gate-proof" where it
expected the test repository's own user.name. The gate refused the proof commit, and the
scheduled onboarding-proof job failed. The gate is green when run on its own, so the
other jobs did not catch it.

Pins:
  * check_env() drops GIT_CONFIG_PARAMETERS, GIT_CONFIG_COUNT and every
    GIT_CONFIG_KEY_<n> / GIT_CONFIG_VALUE_<n>, and keeps everything else, including
    GIT_CONFIG_GLOBAL and GIT_CONFIG_SYSTEM (the tests' own isolation);
  * a real git process given check_env() reads the repository's config, while the same
    git given the unscrubbed environment reads the injected value (so this test can fail);
  * main() passes that environment to every check;
  * every test file that starts git drops that config itself when it loads (tools/git_env.py),
    so it is isolated when run on its own too: checked over the source of each test file, and
    end to end by running tools/test_task_ids.py under `-c commit.gpgsign=true`, which made
    its fixture commits ask for a signing key before the drop was added.
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
from unittest import mock

# Git here runs without config from a calling `git -c`; see tools/git_env.py.
_git_env_spec = importlib.util.spec_from_file_location(
    "git_env", Path(__file__).resolve().parent / "git_env.py")
_git_env = importlib.util.module_from_spec(_git_env_spec)
_git_env_spec.loader.exec_module(_git_env)
_git_env.drop_command_line_config()

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("run_regression", TOOLS / "run_regression.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

INJECTED = {
    "GIT_CONFIG_PARAMETERS": "'user.name'='setup-gate-proof'",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "user.email",
    "GIT_CONFIG_VALUE_0": "setup-gate-proof@example.invalid",
}


class CheckEnv(unittest.TestCase):
    def test_command_line_config_is_dropped_and_the_rest_kept(self):
        parent = {
            **INJECTED,
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_VALUE_1": "/elsewhere",
            "GIT_CONFIG_GLOBAL": "/tmp/isolated-global",
            "GIT_CONFIG_SYSTEM": "/tmp/isolated-system",
            "GIT_AUTHOR_NAME": "kept",
            "PATH": "/usr/bin",
            "HOME": "/repo",
        }
        env = gate.check_env(parent)
        for name in (*INJECTED, "GIT_CONFIG_KEY_1", "GIT_CONFIG_VALUE_1"):
            self.assertNotIn(name, env)
        for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_AUTHOR_NAME", "PATH", "HOME"):
            self.assertEqual(env[name], parent[name])
        self.assertIn("GIT_CONFIG_PARAMETERS", parent, "the caller's mapping must not be changed")

    def test_git_reads_the_repository_config_not_the_callers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            empty = tmp / "empty-config"
            empty.write_text("", encoding="utf-8")
            base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            base.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_SYSTEM=str(empty))
            repo = tmp / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, env=base, check=True)
            subprocess.run(["git", "config", "user.name", "Original Developer"],
                           cwd=repo, env=base, check=True)

            def user_name(env):
                return subprocess.run(["git", "config", "user.name"], cwd=repo, env=env,
                                      capture_output=True, text=True, check=True).stdout.strip()

            leaked = {**base, **INJECTED}
            self.assertEqual(user_name(leaked), "setup-gate-proof",
                             "precondition: git reads the injected value when it is not dropped")
            self.assertEqual(user_name(gate.check_env(leaked)), "Original Developer")


class MainUsesCheckEnv(unittest.TestCase):
    def test_every_check_gets_the_scrubbed_environment(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(kwargs)
            return subprocess.CompletedProcess(cmd, 0)

        checks = [("a", ["true"]), ("b", ["true"])]
        with mock.patch.dict(os.environ, INJECTED), \
                mock.patch.object(gate, "CHECKS", checks), \
                mock.patch.object(gate.subprocess, "run", side_effect=fake_run), \
                mock.patch("builtins.print"):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(len(calls), len(checks))
        for kwargs in calls:
            self.assertIn("env", kwargs)
            for name in INJECTED:
                self.assertNotIn(name, kwargs["env"])


# A test file starts git when its source holds an argument list beginning "git".
_STARTS_GIT = re.compile(r"""\[\s*["']git["']\s*,""")


class TestsDropCommandLineConfig(unittest.TestCase):
    def test_every_test_file_that_starts_git_drops_it(self):
        root = TOOLS.parent
        files = sorted([*TOOLS.glob("test_*.py"), *TOOLS.glob("*/test_*.py"),
                        *(root / "tests").glob("*.py")])
        starting_git = [f for f in files if _STARTS_GIT.search(f.read_text(encoding="utf-8"))]
        self.assertIn(TOOLS / "test_install_hooks.py", starting_git,
                      "precondition: the pattern finds the file this bug was seen in")
        missing = [str(f.relative_to(root)) for f in starting_git
                   if "drop_command_line_config()" not in f.read_text(encoding="utf-8")]
        self.assertEqual(missing, [], "these test files start git without calling "
                         "drop_command_line_config() from tools/git_env.py when they load")

    def test_a_test_run_on_its_own_ignores_a_calling_git_c(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_CONFIG_PARAMETERS"] = "'commit.gpgsign'='true' 'gpg.program'='false'"
        done = subprocess.run([sys.executable, str(TOOLS / "test_task_ids.py")], cwd=TOOLS.parent,
                              env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
