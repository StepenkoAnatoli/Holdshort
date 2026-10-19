# Conventions every run 4 unit keeps

Collected on 2026-10-19 from the MoonAliza briefs the run 4 briefs used to cite (`router-builder.md`, `common.md`,
`kit-builder.md`, `policy6-builder.md` on MoonAliza `build/github-sign-in`), so that a builder needs nothing from
MoonAliza but the subject code the pack briefs name.

## Commits

- Identity: `git -c user.name=StepenkoAnatoli -c user.email=318295322+StepenkoAnatoli@users.noreply.github.com commit`.
- Every message ends with `Co-Authored-By: <the model writing the commit> <noreply@anthropic.com>` and, when the
  session has one, `Claude-Session: <the session URL>`. No model names anywhere else in committed files.
- One commit per task, each with the five-part report: what changed; why; what it touched; what you verified (each
  claim marked verified, untested or expected); what you got wrong and fixed (or "nothing to report"). Docs-only
  commits may use one line per part.
- SmartRouter's pre-commit hook runs the full regression gate (`python tools/run_regression.py`) on the exact content
  being committed. Never `--no-verify`, never `GATE_OFF`, never unwire the hook. No push: the lead integrates.
- Commit with nothing unstaged or untracked: the hook otherwise sets them aside with `git stash`, and the stash stack
  is shared with every other worktree of the clone.

## Tests

- Red first: each new test is shown failing before the change that makes it pass.
- Guard-removal proof for each guard: remove the check in a scratch copy and name the tests that go red. A guard no
  test catches is a missing test.

## Reports

- The full report goes to `docs/orchestration/2026-10-19-calibration-run-4/reports/<unit>-<n>.md` (the launch prompt
  names `<n>`); the structured return carries a gist of at most five lines plus that path. The lead reads the file.
- A report names commits by sha, every test with its red/green proof, every guard-removal proof, the checks run with
  their results, and what you got wrong and fixed.

## Machine (the lead's Windows host)

- `python3` is a broken Microsoft Store alias there; run `python` (3.14). Bash scripts (`grade.sh`, `make-repo.sh`,
  `historyless-checkout.sh`) run under Git Bash. Node 24.
- SmartRouter's gate takes about 25 minutes there, so each commit through the hook takes that long.
- The MoonAliza clone (read only; the launch prompt names its path) has `node_modules` installed from a lockfile that
  is identical at `16f637f`, `01a8604` and its head; it serves as `MOONALIZA_CLONE`.

## Never

- Keys: never print, copy or commit one; never put one in a prompt. Never commit key-shaped test values (`sk-...`,
  `gh[pousr]_`, `github_pat_`) and never copy example tokens from research captures.
- No absolute host path, session id or run id in a committed pack file.
- Never edit `hosts/claude-code/trace/ledger.jsonl`, `trace/usage.jsonl`, `trace/decisions/*.json`,
  `trace/outcomes/*.json` or any `trace/calibration-*` file by hand.
