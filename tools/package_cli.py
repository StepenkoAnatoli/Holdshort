"""Installed commands for checks that require a Holdshort source checkout."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def _run(script: str, argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check a Holdshort source checkout")
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="Holdshort checkout to check (default: current directory)")
    args, forwarded = parser.parse_known_args(argv)
    root = args.repo.resolve()
    required = ("skills/holdshort/SKILL.md", "tests/holdshort_decisions.py",
                ".githooks/pre-commit", f"tools/{script}")
    if not all((root / path).is_file() for path in required):
        print("REFUSED: these checks require a Holdshort source checkout; "
              "pass --repo PATH. The wheel does not contain the repository's "
              "skills, tests, or Git hooks.", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(root / "tools" / script), *forwarded], cwd=root)


def validate_skills(argv=None) -> int:
    return _run("validate_skills.py", argv)


def regression(argv=None) -> int:
    return _run("run_regression.py", argv)
