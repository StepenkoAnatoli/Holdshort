"""Run test files by path: python3 tests/run.py FILE [FILE ...]

Each FILE is loaded from its path (its name need not start with test_) and its
unittest cases run together. Exit 0 when every case passes; 1 when a case fails
or errors, a file cannot be loaded, or the files hold no test at all; 2 when no
file is given.
"""
import importlib.util
import sys
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv):
    if not argv:
        print("usage: python3 tests/run.py FILE [FILE ...]", file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT))
    suite = unittest.TestSuite()
    for i, name in enumerate(argv):
        path = Path(name)
        spec = importlib.util.spec_from_file_location(f"run_{i}_{path.stem}", path)
        if spec is None or spec.loader is None:
            print(f"run.py: cannot load {name}", file=sys.stderr)
            return 1
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            traceback.print_exc()
            print(f"run.py: {name} failed to load", file=sys.stderr)
            return 1
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    if suite.countTestCases() == 0:
        print("run.py: no test in " + " ".join(argv), file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
