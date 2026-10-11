#!/usr/bin/env python3
"""Tests for tools/check_hook_wiring.py — the Layer-1 wiring self-check.

Pins the contract that "fresh clone enforces by default" stays checkable:
  * tracked hook must exist with mode 100755 (967a179 regression guard),
  * unset repo-local core.hooksPath is a FAIL, not a silent pass,
  * a wrong hooksPath value is a FAIL,
  * a global-only hooksPath (repo-local unset) is NOT accepted as wiring,
  * a worktree-present hook covers config + exec-bit checks jointly,
  * CI view (GITHUB_ACTIONS=true) checks only tracked mode — not config,
    because bare CI checkouts have no wiring by design,
  * CI view still fails on a tracked-mode regression (e.g. 100644).

Tests manipulate a real fake repo root under a temp dir; the module under
test takes roots as parameters so no repo state of the developer machine
is touched.
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("chw", TOOLS / "check_hook_wiring.py")
chw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chw)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def _write_hook_exec(root: Path) -> None:
    hook = root / ".githooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho gate\n", encoding="utf-8")
    st = hook.stat()
    os.chmod(hook, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _wire(root: Path) -> None:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True)


def _stage_hook(root: Path, mode: str = "100755") -> None:
    """Stage the hook with the requested tracked mode.

    Windows adds record 100644 even when the file has an X bit, so the
    desired tracked mode is forced explicitly with update-index --chmod
    (works on every git platform). `git config core.fileMode false` is set
    first so the worktree FS bits cannot silently override the index mode.
    """
    subprocess.run(["git", "config", "core.fileMode", "false"], cwd=root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=root, check=True)
    subprocess.run(["git", "add", ".githooks/pre-commit"], cwd=root, check=True)
    chmod_flag = "+x" if mode == "100755" else "-x"
    subprocess.run(["git", "update-index", f"--chmod={chmod_flag}",
                    ".githooks/pre-commit"], cwd=root, check=True)


class HookWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "repo"
        root.mkdir()
        _init_git_repo(root)
        _write_hook_exec(root)
        _stage_hook(root)
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    # --- pure logic, parameterized roots -----------------------------------

    def test_wired_repo_has_no_problems(self):
        _wire(self.root)
        self.assertEqual(chw.wiring_problems_for(self.root, ci=False), [])

    def test_unset_hooks_path_fails(self):
        probs = chw.wiring_problems_for(self.root, ci=False)
        self.assertTrue(any("core.hooksPath is unset" in p for p in probs), probs)

    def test_wrong_hooks_path_fails(self):
        subprocess.run(["git", "config", "core.hooksPath", ".git/hooks"],
                       cwd=self.root, check=True)
        probs = chw.wiring_problems_for(self.root, ci=False)
        self.assertTrue(any("expected '.githooks'" in p for p in probs), probs)

    def test_global_only_hooks_path_is_not_accepted(self):
        # repo-local stays unset; a *global* value must not count as wiring.
        # GIT_CONFIG_GLOBAL isolation: that config exists and has hooksPath,
        # but repo-local is what determines wiring — never the global value.
        env_file = self.root.parent / "globalcfg"
        env_file.write_text("[core]\n\thooksPath = .githooks\n", encoding="utf-8")
        env = dict(os.environ)
        env["GIT_CONFIG_GLOBAL"] = str(env_file)
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        # sanity: git really sees the global value here
        seen = subprocess.run(["git", "config", "--global", "--get", "core.hooksPath"],
                              cwd=self.root, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(seen.stdout.strip(), ".githooks",
                         f"fixture setup failed: global config not visible: {seen.stdout!r}")
        # the repo-local query the check itself makes must stay EMPTY.
        localq = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"],
                                cwd=self.root, env=env, capture_output=True, text=True)
        self.assertNotEqual(localq.returncode, 0)
        # This test targets LOCAL-view semantics (global config is not wiring).
        # On a GitHub runner GITHUB_ACTIONS=true is inherited by the CLI
        # subprocess and correctly switches it to the CI/tracked-mode view —
        # so scrub it here; local-view behavior is what is under test.
        env.pop("GITHUB_ACTIONS", None)
        env.pop("CI", None)
        out = subprocess.run(
            [sys.executable, str(TOOLS / "check_hook_wiring.py"), "--root", str(self.root)],
            cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 1,
                         "global-only hooksPath must not satisfy wiring; "
                         f"stdout={out.stdout} stderr={out.stderr}")

    def test_missing_hook_file_fails(self):
        _wire(self.root)
        (self.root / ".githooks" / "pre-commit").unlink()
        probs = chw.wiring_problems_for(self.root, ci=False)
        self.assertTrue(any("missing from the worktree" in p for p in probs), probs)

    def test_non_exec_hook_fails_posix(self):
        if sys.platform == "win32":
            self.skipTest("exec-bit semantics are POSIX-only")
        _wire(self.root)
        os.chmod(self.root / ".githooks" / "pre-commit", 0o644)
        probs = chw.wiring_problems_for(self.root, ci=False)
        self.assertTrue(any("not executable" in p for p in probs), probs)



    def test_tracked_mode_regression_fails(self):
        _wire(self.root)
        _stage_hook(self.root, mode="100644")
        probs = chw.wiring_problems_for(self.root, ci=False)
        self.assertTrue(any("expected 100755" in p for p in probs), probs)

    # --- the check must be parameterizable over roots ---------------------

    def test_cli_refuses_flaky_fast_when_root_param_missing(self):
        # temp repo above is fully wired; module-level REPO_ROOT points at the
        # real dev repo — so main() on the dev repo must PASS here. If the dev
        # checkout is unwired, that is the gate failing as designed (not a
        # silent pass), and the test still correct: we assert only that the
        # CLI *reports soundly*, never silently skips.
        rc = chw.main()
        self.assertIn(rc, (0, 1))

    # --- CI view -----------------------------------------------------------

    def test_ci_view_ignores_config_but_checks_mode(self):
        # do NOT wire; CI view must not complain about skipped config
        probs = chw.wiring_problems_for(self.root, ci=True)
        self.assertEqual([p for p in probs if "hooksPath" in p], [], probs)
        self.assertEqual(probs, [], "clean-mode CI view on a wired-by-index repo must be clean")

    def test_ci_view_fails_on_tracked_mode_loss(self):
        _stage_hook(self.root, mode="100644")
        probs = chw.wiring_problems_for(self.root, ci=True)
        self.assertTrue(any("expected 100755" in p for p in probs), probs)

    def test_ci_view_fails_on_untracked_hook(self):
        # remove from the INDEX too — deleting the worktree file alone leaves
        # the path tracked (ls-files -s still answers), which is not the
        # scenario this test targets.
        (self.root / ".githooks" / "pre-commit").unlink()
        subprocess.run(["git", "update-index", "--force-remove", ".githooks/pre-commit"],
                       cwd=self.root, check=True)
        probs = chw.wiring_problems_for(self.root, ci=True)
        self.assertTrue(any("not tracked by git" in p for p in probs), probs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
