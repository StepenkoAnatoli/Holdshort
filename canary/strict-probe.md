Disposable marker for the strict-mode canary.

Written by tools/strict_canary.py (run 38239682926) on a throwaway branch that
the probe deletes before it exits. See it on `main` and the branch
protection that requires a green `regression-gate` check in strict mode has
regressed: a stale base was allowed to merge.
