#!/usr/bin/env python3
"""Tests for tools/check_clone_freshness.py — the clone-parity contract.

Pins the runbook §0 precondition: "this clone IS origin/main exactly" must be
decidable, and every way of *not* being exact must surface as a finding:

  * a fresh clone of the pushed tip is OK (exit 0),
  * a local-only commit is flagged by subject, with the ahead count — exit 1,
  * a dirty worktree is flagged, tracked and untracked separately, and a path
    containing spaces arrives intact (`git status -z`),
  * a STALE origin/main tracking ref is named as stale while the live tip has
    moved — the silent-drift bug this tool exists for — exit 1,
  * behind-only (after a fetch) is named as behind and NOT as stale,
  * diverged is named as diverged,
  * a commit reachable from a local branch but from no remote at all is
    flagged even when HEAD itself is exactly origin/main — exit 1,
  * an unborn HEAD is reported, not crashed on — exit 1,
  * an unreachable remote is FAIL-CLOSED exit 2 — never a silent pass — and
  * --offline compares against the last fetch, still flags local-only work,
    and discloses that the remote tip was NOT verified.

Every fixture is a temp bare "origin" plus clones under a temp dir, with
GIT_CONFIG_GLOBAL/SYSTEM pointed at an empty file so the developer's real git
config cannot leak in; the module under test takes roots as parameters, so no
repo state of the developer machine is touched.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REMOTE, BRANCH = "origin", "main"

# Loaded by path (the repo's fixture idiom). Registering the module matters:
# @dataclass resolves the class's defining module through sys.modules, and
# exec_module without registration leaves that lookup empty -> AttributeError
# on Python 3.14+ (first CI-local version mismatch this suite caught). One
# line, version-proof.
spec = importlib.util.spec_from_file_location("ccf", TOOLS / "check_clone_freshness.py")
ccf = importlib.util.module_from_spec(spec)
sys.modules["ccf"] = ccf
spec.loader.exec_module(ccf)


def _isolated_env(tmp: Path) -> dict:
    """os.environ with both git config scopes pointed at one empty file."""
    empty = tmp / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(cwd: Path, *args: str, env: dict, check: bool = True):
    proc = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(
            f"fixture git {' '.join(args)} failed (exit {proc.returncode}):\n"
            f"{proc.stdout}{proc.stderr}")
    return proc


class CloneFreshness(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.env = _isolated_env(self.tmp)
        self._others = 0
        self.origin = self.tmp / "origin.git"
        _git(self.tmp, "init", "-q", "--bare", str(self.origin), env=self.env)
        _git(self.origin, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}", env=self.env)
        self.work = self.tmp / "work"
        _git(self.tmp, "clone", "-q", str(self.origin), str(self.work), env=self.env)
        self._identify(self.work)
        self._commit(self.work, "README.md", "one\n", "first")
        _git(self.work, "push", "-q", "-u", REMOTE, BRANCH, env=self.env)

    def tearDown(self):
        self._tmpdir.cleanup()

    # --- fixture helpers ----------------------------------------------------

    def _identify(self, root: Path) -> None:
        _git(root, "config", "user.email", "t@example.invalid", env=self.env)
        _git(root, "config", "user.name", "t", env=self.env)
        _git(root, "config", "core.autocrlf", "false", env=self.env)

    def _commit(self, root: Path, name: str, content: str, message: str) -> str:
        (root / name).write_text(content, encoding="utf-8")
        _git(root, "add", "--", name, env=self.env)
        _git(root, "commit", "-q", "-m", message, env=self.env)
        return _git(root, "rev-parse", "HEAD", env=self.env).stdout.strip()

    def _advance_remote(self, message: str) -> str:
        """A second clone pushes: the remote moves while `work` never fetches."""
        self._others += 1
        other = self.tmp / f"other-{self._others}"
        _git(self.tmp, "clone", "-q", str(self.origin), str(other), env=self.env)
        self._identify(other)
        sha = self._commit(other, "remote.txt", f"{message}\n", message)
        _git(other, "push", "-q", REMOTE, BRANCH, env=self.env)
        return sha

    def _head(self) -> str:
        return _git(self.work, "rev-parse", "HEAD", env=self.env).stdout.strip()

    def _check(self, *args: str, root: Path | None = None):
        """Run the CLI the operator runs, against the fixture."""
        return subprocess.run(
            [sys.executable, str(TOOLS / "check_clone_freshness.py"),
             "--root", str(root or self.work), *args],
            cwd=TOOLS, env=self.env, capture_output=True, text=True)

    # --- the contract -------------------------------------------------------

    def test_fresh_clone_is_ok(self):
        out = self._check()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("clone_freshness: OK", out.stdout)
        self.assertIn(self._head()[:10], out.stdout)
        self.assertIn(f"'{BRANCH}'", out.stdout)

    def test_local_only_commit_flagged_by_subject(self):
        sha = self._commit(self.work, "local.txt", "x\n", "local-only work")
        out = self._check()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("ahead 1", out.stdout)
        self.assertIn("local-only commit(s)", out.stdout)
        self.assertIn(sha[:7], out.stdout)
        self.assertIn("local-only work", out.stdout)

    def test_dirty_worktree_flagged_tracked_and_untracked(self):
        (self.work / "README.md").write_text("changed\n", encoding="utf-8")
        (self.work / "untracked file with spaces.txt").write_text("x\n", encoding="utf-8")
        out = self._check()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("1 tracked change(s)", out.stdout)
        self.assertIn("1 untracked file(s)", out.stdout)
        self.assertIn("README.md", out.stdout)
        self.assertIn("untracked file with spaces.txt", out.stdout)

    def test_stale_tracking_ref_flagged_without_fetch(self):
        # The exact silent-drift bug: HEAD still equals the local origin/main,
        # but the remote has moved on and this clone has no idea — the new tip
        # is not even an object here yet, so no ahead/behind count exists to
        # report and none may be invented.
        self._advance_remote("remote moved")
        out = self._check()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("tracking ref is STALE", out.stdout)
        self.assertIn("not present in this clone", out.stdout)
        self.assertIn(f"git fetch {REMOTE}", out.stdout)
        self.assertNotIn("ahead", out.stdout)
        self.assertNotIn("behind", out.stdout)

    def test_behind_only_after_fetch_is_behind_not_stale(self):
        self._advance_remote("remote moved")
        _git(self.work, "fetch", "-q", REMOTE, env=self.env)
        out = self._check()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("behind 1", out.stdout)
        self.assertNotIn("STALE", out.stdout)

    def test_diverged_flagged(self):
        self._advance_remote("remote moved")
        self._commit(self.work, "local.txt", "x\n", "local work")
        _git(self.work, "fetch", "-q", REMOTE, env=self.env)
        out = self._check()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("diverged — ahead 1, behind 1", out.stdout)

    def test_commit_on_no_remote_flagged_even_when_head_is_exact(self):
        _git(self.work, "checkout", "-q", "-b", "wip", env=self.env)
        sha = self._commit(self.work, "wip.txt", "x\n", "unpushed wip work")
        _git(self.work, "checkout", "-q", BRANCH, env=self.env)
        out = self._check()
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("on no remote at all", out.stdout)
        self.assertIn(sha[:7], out.stdout)
        self.assertIn("unpushed wip work", out.stdout)
        self.assertNotIn("is NOT", out.stdout)  # HEAD itself is exact; the finding is elsewhere

    def test_unborn_head_reported_when_remote_main_exists(self):
        bare = self.tmp / "fresh-origin.git"
        _git(self.tmp, "init", "-q", "--bare", str(bare), env=self.env)
        _git(bare, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}", env=self.env)
        unborn = self.tmp / "unborn-clone"
        _git(self.tmp, "clone", "-q", str(bare), str(unborn), env=self.env)
        # the remote gets main from elsewhere AFTER the unborn clone was created
        _git(self.work, "push", "-q", str(bare), f"{BRANCH}:{BRANCH}", env=self.env)
        out = self._check(root=unborn)
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("HEAD is unborn", out.stdout)

    def test_unreachable_remote_fails_closed_exit_2(self):
        _git(self.work, "remote", "set-url", REMOTE,
             str(self.tmp / "does-not-exist.git"), env=self.env)
        out = self._check()
        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        self.assertIn("FAIL-CLOSED", out.stderr)
        self.assertIn("--offline", out.stderr)
        self.assertNotIn("OK", out.stdout)

    def test_offline_compares_last_fetch_and_discloses(self):
        self._advance_remote("remote moved")
        out = self._check("--offline")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("OK-LOCAL", out.stdout)
        self.assertIn("NOT verified", out.stdout)

    def test_offline_still_flags_local_only_commit(self):
        self._commit(self.work, "local.txt", "x\n", "local-only work")
        out = self._check("--offline")
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertIn("local-only work", out.stdout)
        self.assertIn("NOT verified", out.stdout)  # a FAIL report still discloses its basis

    def test_module_report_fields_are_usable_programmatically(self):
        sha = self._commit(self.work, "local.txt", "x\n", "local-only work")
        report = ccf.inspect(self.work)
        self.assertEqual(report.ahead, 1)
        self.assertEqual(report.behind, 0)
        self.assertEqual(report.tip_source, "live")
        self.assertEqual(len(report.local_only), 1)
        self.assertIn("local-only work", report.local_only[0])
        self.assertEqual(report.head, sha)
        self.assertTrue(report.problems)
        (self.work / "README.md").write_text("changed\n", encoding="utf-8")
        dirty = ccf.inspect(self.work)
        self.assertEqual(len(dirty.dirty_tracked), 1)
        self.assertEqual(dirty.dirty_untracked, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
