#!/usr/bin/env python3
"""Tests for tools/host_dry_run.py — the two-parallel-worker lifecycle proof.

  D1. the harness proves end-to-end (exit 0, all five P-proofs reported)
  D2. --keep retains the tree with both payloads merged and the ledger written
  D3. duplicate task-id spawn is refused BEFORE git (no shared checkout, ever)
  D4. the injected Brief stays out of the branch (merges never conflict on it)
Run as part of the regression gate (tools/run_regression.py). All fixtures are
throwaway repos under temp dirs with isolated git config; no network, no models.
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
TOOL = REPO / "tools" / "host_dry_run.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


hd = _load("hdr", TOOL)


def _isolated_env(tmp: Path) -> dict:
    empty = tmp / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(empty)
    env["GIT_CONFIG_SYSTEM"] = str(empty)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


class HostDryRun(unittest.TestCase):

    # D1 ----------------------------------------------------------------------
    def test_d1_proves_end_to_end(self):
        r = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True,
                           timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for proof in ("P1", "P2", "P3", "P4", "P5"):
            self.assertIn(proof, r.stdout, f"{proof} missing from:\n{r.stdout}")

    # D2 ----------------------------------------------------------------------
    def test_d2_keep_retains_merged_tree_and_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            keep = Path(td) / "kept"
            r = subprocess.run([sys.executable, str(TOOL), "--keep", str(keep)],
                               capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            main = keep / "main"
            self.assertEqual((main / "feature-a.txt").read_text(), "worker-A payload\n")
            self.assertEqual((main / "feature-b.txt").read_text(), "worker-B payload\n")
            ledger = [json.loads(ln) for ln in
                      (keep / "outcome-ledger.jsonl").read_text().splitlines()]
            self.assertEqual([e["outcome"] for e in ledger], ["accepted", "accepted"])
            self.assertNotEqual(ledger[0]["task-id"], ledger[1]["task-id"])

    # D3 ----------------------------------------------------------------------
    def test_d3_duplicate_id_refused_before_git(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = _isolated_env(tmp)
            root = tmp / "root"
            root.mkdir()
            hd._must(root, "init", "-q", "--bare", str(root / "o.git"), env=env, what="o")
            main = tmp / "m"
            hd._must(tmp, "init", "-q", "-b", "main", str(main), env=env, what="m")
            (main / "f.txt").write_text("x")
            hd._must(main, "add", ".", env=env, what="add")
            hd._must(main, "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-qm", "seed", env=env, what="commit")
            wt_root = tmp / "wts"
            wt_root.mkdir()
            registry = tmp / "workers.json"
            first = hd.spawn_worker(main, wt_root, "a3f9", dict(hd.WORKERS[0]), env,
                                    registry)
            try:
                with self.assertRaises(hd.DryRunFailed) as cm:
                    hd.spawn_worker(main, wt_root, "a3f9", dict(hd.WORKERS[1]), env,
                                    registry)
            finally:
                # Fixture teardown, not a merge: abandon the unmerged branch (its zero
                # dispatches stay consumed by definition — nothing was ever sent).
                hd.sw.cleanup(main, registry, "a3f9", allow_unmerged=True, env=env)
            self.assertIn("refus", str(cm.exception).lower(),
                          "the second spawn must be refused, never a shared checkout")

    # D4 ----------------------------------------------------------------------
    def test_d4_brief_never_enters_the_branch(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            env = _isolated_env(tmp)
            root = tmp / "root"
            root.mkdir()
            report = hd.run(root, env)
            # run() already proved P4; here assert the mechanism: no branch ever
            # contained the injected filename, so merges cannot conflict on it
            out = subprocess.run(["git", "log", "--all", "--name-only", "--pretty=format:"],
                                 cwd=root / "main", env=env,
                                 capture_output=True, text=True, timeout=60)
            self.assertNotIn("SMARTROUTER_BRIEF.json", out.stdout)
            self.assertEqual(len(report["proofs"]), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
