"""Build and install the wheel in isolation; run separately from the stdlib gate.

Needs pip, setuptools and wheel. No provider calls or dependency downloads.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import importlib.util

# Git here runs without config from a calling `git -c`; see tools/git_env.py.
_git_env_spec = importlib.util.spec_from_file_location(
    "git_env", Path(__file__).resolve().parent / "git_env.py")
_git_env = importlib.util.module_from_spec(_git_env_spec)
_git_env_spec.loader.exec_module(_git_env)
_git_env.drop_command_line_config()

ROOT = Path(__file__).resolve().parents[1]


class InstalledPackage(unittest.TestCase):
    def test_installed_resources_and_entry_points(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, wheels, installed = root / "source", root / "wheels", root / "installed"
            source.mkdir()
            paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
            for name in filter(None, paths):
                original = ROOT / name
                if original.is_file():
                    target = source / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original, target)
            def run(args, cwd=root):
                proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=180)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                return proc
            run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                 "--wheel-dir", str(wheels), str(source)])
            wheel, = wheels.glob("*.whl")
            run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                 "--target", str(installed), str(wheel)])
            def script(code):
                return [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, " +
                        repr(str(installed)) + "); " + code]
            run(script("import tools.dispatch_adapter; import tools.offline_deepseek_adapter"))
            entries = json.loads(run(script(
                "import importlib.metadata as m, json; "
                "print(json.dumps({e.name:e.value for e in m.distribution('holdshort-tools').entry_points}))"
            )).stdout)
            self.assertEqual(set(entries), {"holdshort-validate-skills", "holdshort-regression", "holdshort-watchdog"})
            def entry(name, args):
                return script("import importlib.metadata as m; sys.argv = " + repr([name, *args]) +
                              "; e = next(e for e in m.distribution('holdshort-tools').entry_points "
                              "if e.name == " + repr(name) + "); raise SystemExit(e.load()())")
            for name in ("holdshort-validate-skills", "holdshort-regression"):
                proc = subprocess.run(entry(name, []), cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn("source checkout", proc.stderr)
            validated = run(entry("holdshort-validate-skills", ["--repo", str(source), "--strict"]))
            self.assertIn("3 skill(s) validated", validated.stdout)
            run(entry("holdshort-watchdog", ["--help"]))
            supervised = run(entry("holdshort-watchdog", [
                "--task-id", "installed-demo", "--state", str(root / "state.json"),
                "--timeout", "10", "--", sys.executable, "-c", "print('installed command ran')"]))
            self.assertIn("completed", supervised.stdout)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(state["history"][0]["outcome"], "success")
            self.assertIn("installed command ran", state["history"][0]["log_tail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
