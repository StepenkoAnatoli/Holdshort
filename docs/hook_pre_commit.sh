#!/bin/sh
# Holdshort pre-commit hook — runs the full regression gate before every commit.
# Bypass intentionally discouraged: use `git commit --no-verify` only with a
# recorded reason (the gate's purpose is that future commits never silently
# weaken §5 cap enforcement or the accounting checks).
set -e
cd "$(git rev-parse --show-toplevel)"
python tools/run_regression.py
rc=$?
if [ $rc -ne 0 ]; then
  echo ""
  echo "PRE-COMMIT: regression gate FAILED (exit $rc) — commit blocked."
  echo "Fix the failing check, or use --no-verify with a recorded reason."
  exit $rc
fi
exit 0
